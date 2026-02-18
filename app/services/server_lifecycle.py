"""
Server lifecycle management.

All operations that control game server state: provisioning, start, stop,
restart, console command sending, and status queries.
"""
import io
import time

from app.extensions import db
from app.models.server import GameServer
from app.services.ssh import SSHManager
from app.services.minecraft import MinecraftService
from app.services.nginx import NginxService

ssh_mgr = SSHManager()
mc_svc = MinecraftService()
nginx_svc = NginxService()

# The systemd unit name created by install-mcjava.sh
SYSTEMD_UNIT = 'PGSM'

# tmux session name created by install-mcjava.sh
TMUX_SESSION = 'PGSM'

# Seconds between SSH retry attempts during container boot wait
_BOOT_RETRY_INTERVAL = 5
_BOOT_MAX_ATTEMPTS = 60  # 5 minutes total


def provision_server(server_id: str) -> None:
    """Full provisioning pipeline after LXC container creation.

    1. Wait for container to become SSH-accessible
    2. Upload install script
    3. Execute install script with args
    4. Write server.properties
    5. Write nginx conf
    6. Update server status in DB
    """
    server = GameServer.query.get(server_id)
    if not server:
        return

    ip = server.ip_address

    # Step 1: Wait for SSH
    _wait_for_ssh(ip, server)

    # Step 2: Upload install script
    try:
        local_script = mc_svc.get_script_path(server.server_type)
        ssh_mgr.upload_script(ip, local_script, '/tmp/pgsm_install.sh')
    except Exception as e:
        _set_status(server, 'error')
        raise RuntimeError(f'Script upload failed: {e}') from e

    # Step 3: Execute install script
    try:
        args = mc_svc.build_install_args(server)
        stdout, stderr = ssh_mgr.exec(ip, f'bash /tmp/pgsm_install.sh {args}', timeout=600)
    except Exception as e:
        _set_status(server, 'error')
        raise RuntimeError(f'Install script failed: {e}') from e

    # Step 4: Write server.properties
    try:
        props = mc_svc.generate_server_properties(server)
        _write_remote_file(ip, '/PGSM/server.properties', props)
    except Exception as e:
        _set_status(server, 'error')
        raise RuntimeError(f'Could not write server.properties: {e}') from e

    # Step 5: Write nginx conf
    try:
        nginx_svc.add_server(server)
    except Exception:
        pass  # nginx errors are non-fatal; log in production

    # Step 6: Start the server and update status
    try:
        ssh_mgr.exec(ip, f'systemctl start {SYSTEMD_UNIT}')
        _set_status(server, 'running')
    except Exception as e:
        _set_status(server, 'stopped')  # Provisioned but not started


def start_server(server: GameServer) -> None:
    ssh_mgr.exec(server.ip_address, f'systemctl start {SYSTEMD_UNIT}')
    _set_status(server, 'running')


def stop_server(server: GameServer) -> None:
    ssh_mgr.exec(server.ip_address, f'systemctl stop {SYSTEMD_UNIT}')
    _set_status(server, 'stopped')


def restart_server(server: GameServer) -> None:
    ssh_mgr.exec(server.ip_address, f'systemctl restart {SYSTEMD_UNIT}')
    _set_status(server, 'running')


def get_live_status(server: GameServer) -> str:
    """Queries systemd for the live unit state. Returns 'active', 'inactive', or 'failed'."""
    try:
        stdout, _ = ssh_mgr.exec(server.ip_address, f'systemctl is-active {SYSTEMD_UNIT}')
        raw = stdout.strip()
        # Map systemd states to PGSM status vocabulary
        if raw == 'active':
            return 'running'
        elif raw in ('inactive', 'deactivating'):
            return 'stopped'
        elif raw == 'failed':
            return 'error'
        return raw
    except Exception:
        return 'unknown'


def send_console_command(server: GameServer, command: str) -> None:
    """Sends a command string to the running tmux session."""
    escaped = command.replace("'", "'\\''")
    # tmux session is owned by the PGSM user — must run as that user
    ssh_mgr.exec(
        server.ip_address,
        f"su -s /bin/bash PGSM -c \"TMUX_TMPDIR=/tmp tmux send-keys -t {TMUX_SESSION} '{escaped}' Enter\""
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _wait_for_ssh(ip: str, server: GameServer) -> None:
    """Blocks until the container responds to SSH, with retries."""
    for attempt in range(_BOOT_MAX_ATTEMPTS):
        try:
            ssh_mgr.exec(ip, 'echo ready')
            return
        except Exception:
            if attempt == 0:
                pass  # Expected on first try
            time.sleep(_BOOT_RETRY_INTERVAL)
    _set_status(server, 'error')
    raise RuntimeError(f'Container at {ip} never became SSH-accessible after {_BOOT_MAX_ATTEMPTS} attempts.')


def _write_remote_file(ip: str, remote_path: str, content: str) -> None:
    """Writes a string to a file on the remote host via SFTP."""
    client, sftp = ssh_mgr.get_sftp(ip)
    try:
        with sftp.file(remote_path, 'w') as f:
            f.write(content)
    finally:
        sftp.close()
        client.close()


def _set_status(server: GameServer, status: str) -> None:
    server.status = status
    db.session.commit()
