import threading
import time
import traceback
import logging

from flask import render_template, current_app, abort
from flask import request as flask_request
from flask_socketio import emit, join_room, leave_room

from app.blueprints.console import bp
from app.extensions import db, socketio
from app.models.server import GameServer
from app.services.ssh import SSHManager

log = logging.getLogger(__name__)
ssh_mgr = SSHManager()

# Track active console sessions: server_id -> set of socket sid
_active_sessions: dict[str, set] = {}
# Lock to protect _active_sessions from race conditions
_sessions_lock = threading.Lock()


@bp.route('/<server_id>')
def console(server_id):
    server = db.session.get(GameServer, server_id)
    if server is None:
        abort(404)
    return render_template('console/index.html', server=server)


@socketio.on('join_console')
def handle_join_console(data):
    try:
        server_id = data.get('server_id')
        sid = flask_request.sid
        room = f'console_{server_id}'
        join_room(room)

        server = db.session.get(GameServer, server_id)
        if not server:
            emit('console_output', {'data': f'\r\n[PGSM] Server {server_id} not found.\r\n'})
            return
        if server.status != 'running':
            emit('console_output', {'data': f'\r\n[PGSM] Server is not running (status: {server.status}).\r\n'})
            return

        # Capture app instance for the background thread
        app = current_app._get_current_object()
        ip = server.ip_address

        with _sessions_lock:
            already_streaming = server_id in _active_sessions and bool(_active_sessions[server_id])
            if server_id not in _active_sessions:
                _active_sessions[server_id] = set()
            _active_sessions[server_id].add(sid)

        if not already_streaming:
            threading.Thread(
                target=_stream_console,
                args=(app, server_id, ip, room),
                daemon=True
            ).start()

    except Exception as e:
        emit('console_output', {'data': f'\r\n[PGSM] join error: {e}\r\n{traceback.format_exc()}\r\n'})


@socketio.on('leave_console')
def handle_leave_console(data):
    server_id = data.get('server_id')
    sid = flask_request.sid
    room = f'console_{server_id}'
    leave_room(room)
    with _sessions_lock:
        if server_id in _active_sessions:
            _active_sessions[server_id].discard(sid)


@socketio.on('disconnect')
def handle_disconnect():
    """Clean up any console sessions when a client disconnects."""
    sid = flask_request.sid
    with _sessions_lock:
        for server_id in list(_active_sessions.keys()):
            _active_sessions[server_id].discard(sid)


@socketio.on('console_input')
def handle_console_input(data):
    server_id = data.get('server_id')
    command = data.get('command', '')
    server = db.session.get(GameServer, server_id)
    if server:
        from app.services.server_lifecycle import send_console_command
        try:
            send_console_command(server, command)
        except Exception as e:
            emit('console_output', {'data': f'\r\n[PGSM] Error sending command: {e}\r\n'})


def _stream_console(app, server_id: str, ip: str, room: str):
    """Background thread: SSH invoke_shell → attach tmux → stream to SocketIO room."""
    client = None
    try:
        with app.app_context():
            socketio.emit('console_output', {'data': f'\r\n[PGSM] Connecting to {ip}...\r\n'}, room=room)
            client = ssh_mgr.get_client(ip)
            socketio.emit('console_output', {'data': '[PGSM] SSH connected. Attaching tmux...\r\n'}, room=room)
            channel = client.invoke_shell(width=220, height=50)
            channel.send('tmux attach -t PGSM\n')
            time.sleep(0.5)
            while True:
                with _sessions_lock:
                    has_viewers = bool(_active_sessions.get(server_id))
                if not has_viewers:
                    break
                if channel.recv_ready():
                    output = channel.recv(4096).decode('utf-8', errors='replace')
                    socketio.emit('console_output', {'data': output}, room=room)
                if channel.closed:
                    socketio.emit('console_output', {'data': '\r\n[PGSM] SSH channel closed.\r\n'}, room=room)
                    break
                time.sleep(0.05)
    except Exception as e:
        log.error('Console stream error for %s: %s', server_id, traceback.format_exc())
        socketio.emit(
            'console_output',
            {'data': f'\r\n[PGSM] Connection error: {e}\r\n'},
            room=room
        )
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        with _sessions_lock:
            _active_sessions.pop(server_id, None)
