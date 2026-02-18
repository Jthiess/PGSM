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

# Active console sessions: server_id -> {'sids': set, 'channel': paramiko channel or None}
_active_sessions: dict[str, dict] = {}


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
        cols = int(data.get('cols', 220))
        rows = int(data.get('rows', 50))
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

        ip = server.ip_address
        app = current_app._get_current_object()

        already_streaming = server_id in _active_sessions and bool(_active_sessions[server_id]['sids'])
        if server_id not in _active_sessions:
            _active_sessions[server_id] = {'sids': set(), 'channel': None}
        _active_sessions[server_id]['sids'].add(sid)

        if not already_streaming:
            socketio.start_background_task(_stream_console, app, server_id, ip, room, cols, rows)

    except Exception as e:
        emit('console_output', {'data': f'\r\n[PGSM] join error: {e}\r\n{traceback.format_exc()}\r\n'})


@socketio.on('console_resize')
def handle_console_resize(data):
    """Client window was resized — update the pty dimensions."""
    server_id = data.get('server_id')
    cols = int(data.get('cols', 220))
    rows = int(data.get('rows', 50))
    session = _active_sessions.get(server_id)
    if session and session['channel']:
        try:
            session['channel'].resize_pty(width=cols, height=rows)
        except Exception:
            pass


@socketio.on('leave_console')
def handle_leave_console(data):
    server_id = data.get('server_id')
    sid = flask_request.sid
    leave_room(f'console_{server_id}')
    session = _active_sessions.get(server_id)
    if session:
        session['sids'].discard(sid)


@socketio.on('disconnect')
def handle_disconnect():
    sid = flask_request.sid
    for session in _active_sessions.values():
        session['sids'].discard(sid)


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


def _stream_console(app, server_id: str, ip: str, room: str, cols: int, rows: int):
    """Eventlet greenlet: SSH invoke_shell → attach tmux → stream to SocketIO room."""
    client = None
    try:
        with app.app_context():
            socketio.emit('console_output', {'data': f'\r\n[PGSM] Connecting to {ip}...\r\n'}, room=room)
            client = ssh_mgr.get_client(ip)
            socketio.emit('console_output', {'data': '[PGSM] SSH connected. Attaching tmux...\r\n'}, room=room)

            # Open a pty-backed shell sized to match xterm.js exactly
            channel = client.invoke_shell(term='xterm-256color', width=cols, height=rows)
            # Store channel so resize events can update it
            if server_id in _active_sessions:
                _active_sessions[server_id]['channel'] = channel

            # Attach to the tmux session as the PGSM user
            # TMUX_TMPDIR=/tmp matches what the systemd service sets
            channel.send('su -s /bin/bash PGSM -c "TMUX_TMPDIR=/tmp tmux attach -t PGSM"\n')
            socketio.sleep(0.5)

            while True:
                session = _active_sessions.get(server_id)
                if not session or not session['sids']:
                    break
                if channel.recv_ready():
                    output = channel.recv(4096).decode('utf-8', errors='replace')
                    socketio.emit('console_output', {'data': output}, room=room)
                if channel.closed:
                    socketio.emit('console_output', {'data': '\r\n[PGSM] SSH channel closed.\r\n'}, room=room)
                    break
                socketio.sleep(0.05)

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
        _active_sessions.pop(server_id, None)
