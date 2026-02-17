import threading
import time

from flask import render_template
from flask_socketio import emit, join_room, leave_room

from app.blueprints.console import bp
from app.extensions import socketio
from app.models.server import GameServer
from app.services.ssh import SSHManager

ssh_mgr = SSHManager()

# Track active console sessions: server_id -> set of sid
_active_sessions: dict[str, set] = {}


@bp.route('/<server_id>')
def console(server_id):
    server = GameServer.query.get_or_404(server_id)
    return render_template('console/index.html', server=server)


@socketio.on('join_console')
def handle_join_console(data):
    server_id = data.get('server_id')
    room = f'console_{server_id}'
    join_room(room)

    server = GameServer.query.get(server_id)
    if not server or server.status != 'running':
        emit('console_output', {'data': '\r\n[PGSM] Server is not running.\r\n'})
        return

    if server_id not in _active_sessions:
        _active_sessions[server_id] = set()

    # Only start one streaming thread per server
    if not _active_sessions[server_id]:
        threading.Thread(
            target=_stream_console,
            args=(server_id, server.ip_address, room),
            daemon=True
        ).start()

    from flask import request as flask_request
    _active_sessions[server_id].add(flask_request.sid)


@socketio.on('leave_console')
def handle_leave_console(data):
    server_id = data.get('server_id')
    room = f'console_{server_id}'
    leave_room(room)
    from flask import request as flask_request
    if server_id in _active_sessions:
        _active_sessions[server_id].discard(flask_request.sid)


@socketio.on('console_input')
def handle_console_input(data):
    server_id = data.get('server_id')
    command = data.get('command', '')
    server = GameServer.query.get(server_id)
    if server:
        from app.services.server_lifecycle import send_console_command
        try:
            send_console_command(server, command)
        except Exception as e:
            emit('console_output', {'data': f'\r\n[PGSM] Error sending command: {e}\r\n'})


def _stream_console(server_id: str, ip: str, room: str):
    """Background thread: SSH invoke_shell → attach tmux → stream to SocketIO room."""
    try:
        client = ssh_mgr.get_client(ip)
        channel = client.invoke_shell(width=220, height=50)
        channel.send('tmux attach -t PGSM\n')
        time.sleep(0.5)
        while True:
            if not _active_sessions.get(server_id):
                break  # All viewers left
            if channel.recv_ready():
                output = channel.recv(4096).decode('utf-8', errors='replace')
                socketio.emit('console_output', {'data': output}, room=room)
            if channel.closed:
                break
            time.sleep(0.05)
    except Exception as e:
        socketio.emit('console_output', {'data': f'\r\n[PGSM] Connection lost: {e}\r\n'}, room=room)
    finally:
        try:
            client.close()
        except Exception:
            pass
        _active_sessions.pop(server_id, None)
