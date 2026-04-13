"""
Server lifecycle management.

All operations that control game server state: provisioning, start, stop,
restart, console command sending, and status queries.
"""
import io
import logging
import os
import time

from app.extensions import db
from app.models.server import GameServer
from app.services.ssh import SSHManager
from app.services.minecraft import MinecraftService
from app.services.nginx import NginxService

logger = logging.getLogger(__name__)

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
        logger.error('provision_server called with unknown server_id=%s — aborting', server_id)
        return

    ip = server.ip_address
    logger.info(
        '[server=%s] Starting provisioning pipeline — type=%s, version=%s, ip=%s, ct_id=%s',
        server_id, server.server_type, server.game_version, ip, server.ct_id,
    )

    # Step 1: Wait for SSH
    logger.info('[server=%s] Step 1/6: Waiting for SSH on %s', server_id, ip)
    _wait_for_ssh(ip, server)
    logger.info('[server=%s] SSH is ready on %s', server_id, ip)

    # Step 2: Upload install script
    logger.info('[server=%s] Step 2/6: Uploading install script for type=%s', server_id, server.server_type)
    try:
        local_script = mc_svc.get_script_path(server.server_type)
        logger.info('[server=%s] Uploading %s → /tmp/pgsm_install.sh', server_id, local_script)
        ssh_mgr.upload_script(ip, local_script, '/tmp/pgsm_install.sh')
    except Exception as e:
        logger.error('[server=%s] Script upload failed: %s', server_id, e, exc_info=True)
        _set_status(server, 'error', provision_log=f'Script upload failed: {e}')
        raise RuntimeError(f'Script upload failed: {e}') from e

    # Step 2b: For import servers, upload the zip archive to the container
    if server.server_type == 'import' and server.import_archive_url:
        local_zip = server.import_archive_url  # stored as local host path
        logger.info('[server=%s] Uploading import archive %s → /tmp/server-archive.zip', server_id, local_zip)
        try:
            ssh_mgr.upload_script(ip, local_zip, '/tmp/server-archive.zip')
            logger.info('[server=%s] Import archive uploaded successfully', server_id)
        except Exception as e:
            logger.error('[server=%s] Archive upload failed: %s', server_id, e, exc_info=True)
            _set_status(server, 'error', provision_log=f'Archive upload failed: {e}')
            raise RuntimeError(f'Archive upload failed: {e}') from e
        finally:
            # Clean up local zip regardless of upload success
            try:
                os.remove(local_zip)
                logger.info('[server=%s] Cleaned up local archive %s', server_id, local_zip)
            except OSError:
                pass

    # Step 3: Execute install script
    logger.info('[server=%s] Step 3/6: Executing install script (timeout=600s)', server_id)
    try:
        args = mc_svc.build_install_args(server)
        logger.info('[server=%s] Install args: %s', server_id, args)
        stdout, stderr = ssh_mgr.exec(ip, f'bash /tmp/pgsm_install.sh {args}', timeout=600)
        logger.info('[server=%s] Install script completed', server_id)
        if stderr and stderr.strip():
            logger.warning('[server=%s] Install script stderr: %s', server_id, stderr.strip())
        _set_provision_log(server, _format_script_output(stdout, stderr))
    except Exception as e:
        logger.error('[server=%s] Install script failed: %s', server_id, e, exc_info=True)
        _set_status(server, 'error', provision_log=f'Install script failed: {e}')
        raise RuntimeError(f'Install script failed: {e}') from e

    # Step 4: Write server.properties and fix ownership
    logger.info('[server=%s] Step 4/6: Writing server.properties', server_id)
    try:
        props = mc_svc.generate_server_properties(server)
        _write_remote_file(ip, '/PGSM/server.properties', props)
        # SFTP writes as root; restore PGSM ownership so the server can read/write the file
        ssh_mgr.exec(ip, 'chown PGSM:PGSM /PGSM/server.properties')
        logger.info('[server=%s] server.properties written and ownership fixed', server_id)
    except Exception as e:
        logger.error('[server=%s] Could not write server.properties: %s', server_id, e, exc_info=True)
        _set_status(server, 'error', provision_log=f'Could not write server.properties: {e}')
        raise RuntimeError(f'Could not write server.properties: {e}') from e

    # Step 5: Write nginx conf (non-fatal — server still works without it)
    logger.info('[server=%s] Step 5/6: Writing nginx conf for ct_id=%s', server_id, server.ct_id)
    try:
        nginx_svc.add_server(server)
        logger.info('[server=%s] nginx conf written and nginx reloaded', server_id)
    except Exception as e:
        # nginx errors are non-fatal; the game server is still reachable directly
        logger.warning('[server=%s] nginx conf step failed (non-fatal): %s', server_id, e)

    # Step 6: Start the server and update status
    logger.info('[server=%s] Step 6/6: Starting systemd unit %s', server_id, SYSTEMD_UNIT)
    try:
        _start_and_verify(ip, server)
        logger.info('[server=%s] Provisioning complete — server is running', server_id)
    except Exception as e:
        logger.error('[server=%s] systemd start failed after provisioning: %s', server_id, e, exc_info=True)
        # provision_log already set by _start_and_verify; preserve it by not overwriting


def start_server(server: GameServer) -> None:
    logger.info('[server=%s] Starting server — ct_id=%s, ip=%s', server.id, server.ct_id, server.ip_address)
    from app.services.proxmox import ProxmoxService
    try:
        ProxmoxService().start_ct(server.proxmox_node, server.ct_id)
    except Exception as e:
        # CT may already be running; log at debug level so it doesn't alarm on normal starts
        logger.debug('[server=%s] start_ct raised (CT may already be running): %s', server.id, e)
    _wait_for_ssh(server.ip_address, server)
    _start_and_verify(server.ip_address, server)
    logger.info('[server=%s] Server started successfully', server.id)


def stop_server(server: GameServer) -> None:
    """Stops the Minecraft server process via systemd. The container keeps running."""
    logger.info('[server=%s] Stopping server process (container stays up) — ip=%s', server.id, server.ip_address)
    ssh_mgr.exec(server.ip_address, f'systemctl stop {SYSTEMD_UNIT}')
    _set_status(server, 'stopped')
    logger.info('[server=%s] Server stopped', server.id)


def power_off_server(server: GameServer) -> None:
    """Stops the Minecraft process (best-effort) then powers off the LXC container."""
    logger.info('[server=%s] Powering off — stopping game process then halting CT %s', server.id, server.ct_id)
    from app.services.proxmox import ProxmoxService
    try:
        ssh_mgr.exec(server.ip_address, f'systemctl stop {SYSTEMD_UNIT}')
    except Exception as e:
        logger.debug('[server=%s] Could not stop game process before power-off (CT may be unreachable): %s', server.id, e)
    ProxmoxService().stop_ct(server.proxmox_node, server.ct_id)
    _set_status(server, 'stopped')
    logger.info('[server=%s] Container powered off', server.id)


def restart_server(server: GameServer) -> None:
    logger.info('[server=%s] Restarting server process — ip=%s', server.id, server.ip_address)
    ssh_mgr.exec(server.ip_address, f'systemctl restart {SYSTEMD_UNIT}')
    _start_and_verify(server.ip_address, server)
    logger.info('[server=%s] Server restarted', server.id)


def get_live_status(server: GameServer) -> str:
    """Queries systemd for the live unit state. Returns 'active', 'inactive', or 'failed'."""
    try:
        stdout, _ = ssh_mgr.exec(server.ip_address, f'systemctl is-active {SYSTEMD_UNIT}', timeout=5)
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


def sync_server_status(server: GameServer) -> str:
    """Syncs server status by checking Proxmox CT state, then systemd if CT is running.

    Updates the DB if the status changed. Returns the new status string.
    """
    from app.services.proxmox import ProxmoxService
    try:
        ct_status = ProxmoxService().get_ct_status(server.proxmox_node, server.ct_id)
        proxmox_state = ct_status.get('status', 'unknown')
    except Exception:
        # Proxmox unreachable — leave DB as-is, return current value
        return server.status

    if proxmox_state == 'stopped':
        # Container is off — can't reach systemd
        new_status = 'stopped'
    elif proxmox_state == 'running':
        # Container is up — check if the game server systemd unit is actually running
        new_status = get_live_status(server)
        if new_status == 'unknown':
            # SSH not yet accessible (e.g. still booting) — don't change DB
            return server.status
    else:
        return server.status

    if new_status != server.status and new_status in ('running', 'stopped', 'error'):
        _set_status(server, new_status)

    return new_status


def update_server_version(server_id: str, new_version: str) -> None:
    """Updates the Minecraft server binary to a new version.

    Stops the server, replaces the server JAR/binary, updates the DB game_version,
    and restarts. World data in /PGSM is preserved.

    Supported server types: vanilla, paper, fabric.
    """
    import shlex as _shlex

    server = GameServer.query.get(server_id)
    if not server:
        logger.error('update_server_version called with unknown server_id=%s', server_id)
        return

    ip = server.ip_address
    logger.info(
        '[server=%s] Starting version update %s → %s (type=%s)',
        server_id, server.game_version, new_version, server.server_type,
    )
    _set_status(server, 'updating')

    stdout, stderr = '', ''
    try:
        # Stop the server
        try:
            ssh_mgr.exec(ip, f'systemctl stop {SYSTEMD_UNIT}', timeout=30)
        except Exception:
            pass

        if server.server_type == 'vanilla':
            jar_url = mc_svc.get_vanilla_jar_url(new_version)
            stdout, stderr = ssh_mgr.exec(
                ip,
                f'wget -q -O /PGSM/server.jar {_shlex.quote(jar_url)}',
                timeout=300,
            )

        elif server.server_type == 'paper':
            jar_url = mc_svc.get_paper_jar_url(new_version)
            stdout, stderr = ssh_mgr.exec(
                ip,
                f'wget -q -O /PGSM/server.jar {_shlex.quote(jar_url)}',
                timeout=300,
            )

        elif server.server_type == 'fabric':
            installer_url = mc_svc.get_fabric_installer_url()
            loader_version = mc_svc.get_fabric_loader_version(server.fabric_loader_version)
            java_bin = f'/opt/java/java{server.java_version}/bin/java'
            stdout, stderr = ssh_mgr.exec(
                ip,
                f'cd /PGSM && '
                f'wget -q -O /tmp/pgsm-fabric-installer.jar {_shlex.quote(installer_url)} && '
                f'{java_bin} -jar /tmp/pgsm-fabric-installer.jar server '
                f'-mcversion {_shlex.quote(new_version)} '
                f'-loader {_shlex.quote(loader_version)} '
                f'-downloadMinecraft && '
                f'rm -f /tmp/pgsm-fabric-installer.jar',
                timeout=600,
            )

        else:
            raise ValueError(f'Version update is not supported for server type: {server.server_type}')

        # Fix ownership
        ssh_mgr.exec(ip, 'chown -R PGSM:PGSM /PGSM')

        # Update DB
        server.game_version = new_version
        db.session.commit()

        # Update Java symlink — auto-resolved Java version may change with new MC version
        java_dir = f'java{server.java_version}'
        ssh_mgr.exec(ip, f'ln -sf /opt/java/{java_dir}/bin/java /usr/local/bin/java')

        # Write updated server.properties
        props = mc_svc.generate_server_properties(server)
        _write_remote_file(ip, '/PGSM/server.properties', props)
        ssh_mgr.exec(ip, 'chown PGSM:PGSM /PGSM/server.properties')

        # Restart the server
        ssh_mgr.exec(ip, f'systemctl start {SYSTEMD_UNIT}')
        _set_status(server, 'running', provision_log=_format_script_output(stdout, stderr))
        logger.info('[server=%s] Version update complete — now running %s', server_id, new_version)

    except Exception as e:
        logger.error('[server=%s] Version update to %s failed: %s', server_id, new_version, e, exc_info=True)
        _set_status(server, 'error', provision_log=f'Update to {new_version} failed: {e}')
        raise


def send_console_command(server: GameServer, command: str) -> None:
    """Sends a command string to the running tmux session."""
    escaped = command.replace("'", "'\\''")
    # tmux session is owned by the PGSM user — must run as that user
    ssh_mgr.exec(
        server.ip_address,
        f"su -s /bin/bash PGSM -c \"TMUX_TMPDIR=/tmp tmux send-keys -t {TMUX_SESSION} '{escaped}' Enter\""
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _start_and_verify(ip: str, server: GameServer) -> None:
    """Starts the PGSM systemd unit, waits briefly, then verifies it came up.

    Always captures the last 50 lines of the unit's journal and stores them in
    server.provision_log so the startup output is visible in the UI regardless
    of whether the start succeeded. Raises RuntimeError on failure.
    """
    ssh_mgr.exec(ip, f'systemctl start {SYSTEMD_UNIT}')
    # Give systemd a few seconds to reach a stable state (active or failed)
    time.sleep(4)
    live = get_live_status(server)

    # Always capture journal output — "active" doesn't mean the game is healthy
    try:
        journal_out, _ = ssh_mgr.exec(ip, f'journalctl -u {SYSTEMD_UNIT} -n 50 --no-pager', timeout=10)
        journal_out = journal_out.strip() or '(no journal output)'
    except Exception:
        journal_out = '(unable to retrieve journal output)'

    log_msg = (
        f'systemd state: {live}\n\n'
        f'=== journalctl -u {SYSTEMD_UNIT} ===\n{journal_out}'
    )

    if live == 'running':
        _set_status(server, 'running', provision_log=log_msg)
        return

    logger.error('[server=%s] Server failed to start — %s', server.id, log_msg)
    _set_status(server, 'error', provision_log=log_msg)
    raise RuntimeError(f'Server failed to start — systemd state: {live}')


def _wait_for_ssh(ip: str, server: GameServer) -> None:
    """Blocks until the container responds to SSH, with retries."""
    for attempt in range(_BOOT_MAX_ATTEMPTS):
        try:
            ssh_mgr.exec(ip, 'echo ready')
            return
        except Exception:
            if attempt == 0:
                logger.debug('[server=%s] SSH not yet ready on %s — will retry every %ds (max %d attempts)',
                             server.id, ip, _BOOT_RETRY_INTERVAL, _BOOT_MAX_ATTEMPTS)
            elif attempt % 6 == 0:
                # Log a progress note roughly every 30 seconds to show we're still alive
                logger.info('[server=%s] Still waiting for SSH on %s (attempt %d/%d)',
                            server.id, ip, attempt + 1, _BOOT_MAX_ATTEMPTS)
            time.sleep(_BOOT_RETRY_INTERVAL)
    msg = f'Container at {ip} never became SSH-accessible after {_BOOT_MAX_ATTEMPTS} attempts ({_BOOT_MAX_ATTEMPTS * _BOOT_RETRY_INTERVAL}s).'
    logger.error('[server=%s] %s', server.id, msg)
    _set_status(server, 'error', provision_log=msg)
    raise RuntimeError(msg)


def _write_remote_file(ip: str, remote_path: str, content: str) -> None:
    """Writes a string to a file on the remote host via SFTP."""
    client, sftp = ssh_mgr.get_sftp(ip)
    try:
        with sftp.file(remote_path, 'w') as f:
            f.write(content)
    finally:
        sftp.close()
        client.close()


def _set_status(server: GameServer, status: str, provision_log: str = None) -> None:
    server.status = status
    if provision_log is not None:
        server.provision_log = provision_log
    db.session.commit()


def _set_provision_log(server: GameServer, message: str) -> None:
    server.provision_log = message
    db.session.commit()


def _format_script_output(stdout: str, stderr: str) -> str:
    """Formats install script stdout/stderr into a single log string."""
    parts = []
    if stdout and stdout.strip():
        parts.append(f'=== stdout ===\n{stdout.strip()}')
    if stderr and stderr.strip():
        parts.append(f'=== stderr ===\n{stderr.strip()}')
    return '\n\n'.join(parts) if parts else '(no output)'
