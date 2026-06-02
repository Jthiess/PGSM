import json
import logging
import threading

from flask import current_app, jsonify, request
from sqlalchemy.orm.attributes import flag_modified

from app.auth import require_admin, require_server_access, require_internal_token
from app.blueprints.api import bp
from app.extensions import db, csrf
from app.models.server import GameServer
from app.services.ssh import SSHManager

logger = logging.getLogger(__name__)

_ssh_mgr = SSHManager()


@bp.route('/nodes')
@require_admin
def nodes():
    from app.services.proxmox import ProxmoxService
    try:
        return jsonify(ProxmoxService().get_nodes())
    except Exception as e:
        logger.warning('nodes lookup failed: %s', e)
        return jsonify({'error': 'Could not reach Proxmox'}), 500


@bp.route('/ports/used')
@require_admin
def ports_used():
    """Returns sorted list of all port numbers currently in use by any server."""
    ports = set()
    for s in GameServer.query.all():
        ports.add(s.game_port)
        for entry in (s.extra_ports or []):
            p = entry['port'] if isinstance(entry, dict) else entry
            ports.add(p)
    return jsonify(sorted(ports))


@bp.route('/minecraft/versions')
@require_admin
def minecraft_versions():
    from app.services.minecraft import MinecraftService
    snapshots = request.args.get('snapshots', 'false').lower() == 'true'
    try:
        return jsonify(MinecraftService().get_available_versions(include_snapshots=snapshots))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/forge/versions')
@require_admin
def forge_versions():
    from app.services.minecraft import MinecraftService
    mc_version = request.args.get('mc_version', '').strip()
    if not mc_version:
        return jsonify({'error': 'mc_version query parameter is required'}), 400
    try:
        return jsonify(MinecraftService().get_forge_versions(mc_version))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/fabric/loader-versions')
@require_admin
def fabric_loader_versions():
    from app.services.minecraft import MinecraftService
    try:
        versions = MinecraftService().get_fabric_loader_versions()
        # Return only stable versions with just the version string for simplicity
        stable = [v['version'] for v in versions if not v.get('maven', '').endswith('-SNAPSHOT')]
        return jsonify(stable)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/servers/<server_id>/status')
@require_server_access
def server_status(server_id):
    server = GameServer.query.get_or_404(server_id)
    live_status = server.status  # fallback
    try:
        from app.services.server_lifecycle import get_live_status
        live_status = get_live_status(server)
    except Exception:
        pass  # Server may not be accessible yet
    return jsonify({
        'db_status': server.status,
        'live_status': live_status,
    })


@bp.route('/servers/<server_id>/sync', methods=['POST'])
@require_server_access
def sync_server(server_id):
    """Syncs DB status with actual Proxmox CT + systemd state."""
    server = GameServer.query.get_or_404(server_id)
    if server.status in ('creating', 'updating'):
        return jsonify({'status': server.status, 'changed': False})
    old_status = server.status
    try:
        from app.services.server_lifecycle import sync_server_status
        new_status = sync_server_status(server)
        return jsonify({'status': new_status, 'changed': new_status != old_status})
    except Exception as e:
        logger.warning('sync_server failed for server=%s: %s', server_id, e)
        return jsonify({'error': 'Sync failed', 'status': server.status}), 500


@bp.route('/servers/<server_id>/metrics')
@require_server_access
def server_metrics(server_id):
    server = GameServer.query.get_or_404(server_id)

    result = {
        'cpu_percent': None,
        'memory_used_mb': None,
        'memory_total_mb': None,
        'net_rx_bytes': None,
        'net_tx_bytes': None,
        'players_online': None,
        'players_max': None,
    }

    # Collect system metrics via a single SSH connection
    try:
        combined_cmd = (
            'cat /proc/stat | head -1; '
            'sleep 0.5; '
            'cat /proc/stat | head -1; '
            "free -m | awk 'NR==2{print $3,$2}'; "
            "awk '/eth0|ens/{print $2,$10}' /proc/net/dev | head -1"
        )
        stdout, _ = _ssh_mgr.exec(server.ip_address, combined_cmd, timeout=8)
        lines = stdout.strip().splitlines()

        if len(lines) >= 2:
            # CPU: parse two /proc/stat samples
            def _parse_cpu_line(line):
                parts = line.split()
                vals = [int(x) for x in parts[1:]]
                return vals

            v1 = _parse_cpu_line(lines[0])
            v2 = _parse_cpu_line(lines[1])
            delta = [v2[i] - v1[i] for i in range(min(len(v1), len(v2)))]
            idle = delta[3] if len(delta) > 3 else 0
            total = sum(delta)
            if total > 0:
                result['cpu_percent'] = round(100.0 * (total - idle) / total, 1)

        if len(lines) >= 3:
            mem_parts = lines[2].split()
            if len(mem_parts) == 2:
                result['memory_used_mb'] = int(mem_parts[0])
                result['memory_total_mb'] = int(mem_parts[1])

        if len(lines) >= 4:
            net_parts = lines[3].split()
            if len(net_parts) == 2:
                result['net_rx_bytes'] = int(net_parts[0])
                result['net_tx_bytes'] = int(net_parts[1])

    except Exception:
        pass  # Container unreachable; all fields remain None

    # Query Minecraft player count via server list ping
    if server.status == 'running':
        try:
            from mcstatus import JavaServer
            mc = JavaServer(server.ip_address, server.game_port, timeout=2.5)
            mc_status = mc.status()
            result['players_online'] = mc_status.players.online
            result['players_max'] = mc_status.players.max
        except Exception:
            pass  # Server not yet accepting connections or ping timed out

    return jsonify(result)


@bp.route('/servers/<server_id>/ports', methods=['GET'])
@require_server_access
def get_ports(server_id):
    server = GameServer.query.get_or_404(server_id)
    return jsonify({
        'game_port': server.game_port,
        'extra_ports': server.extra_ports or [],
        'all_ports': server.all_ports,
        'all_ports_with_protocols': server.all_ports_with_protocols,
    })


@bp.route('/servers/<server_id>/ports/add', methods=['POST'])
@require_admin
def add_port(server_id):
    server = GameServer.query.get_or_404(server_id)
    data = request.get_json(silent=True) or {}
    port = data.get('port')
    protocol = data.get('protocol', 'tcp')

    if not port or not isinstance(port, int) or not (1024 <= port <= 65535):
        return jsonify({'error': 'Invalid port number (must be 1024–65535)'}), 400

    if protocol not in ('tcp', 'udp', 'both'):
        return jsonify({'error': 'Invalid protocol (must be tcp, udp, or both)'}), 400

    if port == server.game_port:
        return jsonify({'error': 'Port is already the primary game port'}), 400

    extra = list(server.extra_ports or [])
    existing_ports = [e['port'] if isinstance(e, dict) else e for e in extra]
    if port in existing_ports:
        return jsonify({'error': 'Port already added'}), 400

    conflict = GameServer.port_in_use_by(port, exclude_id=server_id)
    if conflict:
        return jsonify({'error': f'Port {port} is already in use by server "{conflict.name}"'}), 400

    extra.append({'port': port, 'protocol': protocol})
    server.extra_ports = extra
    flag_modified(server, 'extra_ports')
    db.session.commit()

    # Update nginx config
    try:
        from app.services.nginx import NginxService
        NginxService().add_server(server)
    except Exception as e:
        return jsonify({'ok': True, 'nginx_warning': str(e), 'all_ports': server.all_ports})

    return jsonify({'ok': True, 'all_ports': server.all_ports})


@bp.route('/servers/<server_id>/ports/primary', methods=['POST'])
@require_admin
def set_primary_port(server_id):
    server = GameServer.query.get_or_404(server_id)
    data = request.get_json(silent=True) or {}
    port = data.get('port')

    if not port or not isinstance(port, int) or not (1024 <= port <= 65535):
        return jsonify({'error': 'Invalid port number (must be 1024–65535)'}), 400

    if port == server.game_port:
        return jsonify({'error': 'That is already the primary port'}), 400

    # Check it's not already an extra port
    extra = list(server.extra_ports or [])
    extra_port_nums = [e['port'] if isinstance(e, dict) else e for e in extra]
    if port in extra_port_nums:
        return jsonify({'error': f'Port {port} is already an extra port — remove it first'}), 400

    conflict = GameServer.port_in_use_by(port, exclude_id=server_id)
    if conflict:
        return jsonify({'error': f'Port {port} is already in use by server "{conflict.name}"'}), 400

    server.game_port = port
    db.session.commit()

    try:
        from app.services.nginx import NginxService
        NginxService().add_server(server)
    except Exception as e:
        return jsonify({'ok': True, 'game_port': server.game_port, 'nginx_warning': str(e)})

    return jsonify({'ok': True, 'game_port': server.game_port})


@bp.route('/servers', methods=['GET'])
@require_admin
def list_servers():
    """Lists all game servers. Admin-only — exposes server IPs and ports."""
    servers = GameServer.query.all()
    return jsonify([
        {
            'id': s.id,
            'name': s.name,
            'status': s.status,
            'ip_address': s.ip_address,
            'game_port': s.game_port,
            'game_code': s.game_code,
            'server_type': s.server_type,
            'game_version': s.game_version,
        }
        for s in servers
    ])


@bp.route('/servers/<server_id>/whitelist', methods=['POST'])
@csrf.exempt
@require_internal_token
def push_whitelist(server_id):
    """Writes whitelist.json to a server and reloads the whitelist.

    Expects JSON body: [{"uuid": "...", "name": "..."}, ...]

    CSRF-exempt because it is a machine-to-machine endpoint authenticated by
    the internal token header (see require_internal_token).
    """
    server = GameServer.query.get_or_404(server_id)
    data = request.get_json(silent=True)
    # Strict schema validation: a list of {uuid, name} string pairs only, so an
    # attacker cannot write arbitrary structures into the root-owned file.
    if not isinstance(data, list):
        return jsonify({'error': 'Request body must be a JSON array'}), 400
    for entry in data:
        if (not isinstance(entry, dict)
                or not isinstance(entry.get('uuid'), str)
                or not isinstance(entry.get('name'), str)):
            return jsonify({'error': 'Each entry must have string "uuid" and "name"'}), 400

    payload = json.dumps([{'uuid': e['uuid'], 'name': e['name']} for e in data], indent=2)
    try:
        ssh_client, sftp = _ssh_mgr.get_sftp(server.ip_address)
        try:
            with sftp.file('/PGSM/whitelist.json', 'w') as f:
                f.write(payload)
            sftp.close()
        finally:
            ssh_client.close()
        _ssh_mgr.exec(server.ip_address, 'chown PGSM:PGSM /PGSM/whitelist.json')
        _ssh_mgr.exec(
            server.ip_address,
            "su -s /bin/bash PGSM -c \"TMUX_TMPDIR=/tmp tmux send-keys -t PGSM 'whitelist reload' Enter\"",
            timeout=5,
        )
    except Exception as e:
        logger.warning('push_whitelist failed for server=%s: %s', server_id, e)
        return jsonify({'error': 'Failed to push whitelist'}), 500

    return jsonify({'ok': True, 'entries': len(data)})


@bp.route('/servers/<server_id>/log')
@require_server_access
def server_log(server_id):
    """Returns recent game output for the server.

    Priority:
      1. tmux capture-pane — the actual Minecraft stdout/stderr scrollback
      2. journalctl — systemd unit events (used when the tmux session doesn't exist yet)
      3. stored provision_log — last known output when the container is unreachable
    """
    from app.services.server_lifecycle import SYSTEMD_UNIT, TMUX_SESSION
    server = GameServer.query.get_or_404(server_id)
    try:
        # Try the tmux scrollback first — this is the actual game output
        stdout, _ = _ssh_mgr.exec(
            server.ip_address,
            f'su -s /bin/bash PGSM -c "TMUX_TMPDIR=/tmp tmux capture-pane -t {TMUX_SESSION} -p -S -500" 2>/dev/null',
            timeout=10,
        )
        if stdout.strip():
            return jsonify({'log': stdout.rstrip(), 'source': 'live'})

        # tmux session doesn't exist yet — fall back to journalctl for systemd events
        stdout, _ = _ssh_mgr.exec(
            server.ip_address,
            f'journalctl -u {SYSTEMD_UNIT} -n 100 --no-pager',
            timeout=10,
        )
        return jsonify({'log': stdout.strip() or '(no output yet)', 'source': 'live'})
    except Exception:
        stored = server.provision_log or '(no log available — container unreachable)'
        return jsonify({'log': stored, 'source': 'stored'})


@bp.route('/servers/<server_id>/provision-log/dismiss', methods=['POST'])
@require_server_access
def dismiss_provision_log(server_id):
    server = GameServer.query.get_or_404(server_id)
    server.provision_log = None
    db.session.commit()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Backup endpoints
# ---------------------------------------------------------------------------

@bp.route('/servers/<server_id>/backup', methods=['POST'])
@require_admin
def create_backup(server_id):
    """Triggers a background backup of /PGSM to the configured local backup path.

    The tar.gz is created on the container then pulled down over SFTP.
    Because large worlds can take several minutes to compress, the operation
    runs in a daemon thread and this endpoint returns immediately.

    Returns:
        200: ``{"ok": true, "message": "Backup started in background"}``
        400: ``{"error": "BACKUP_PATH is not configured"}`` when the
             config value is missing or empty.
        404: server not found.
    """
    from app.services import backup as backup_service

    server = GameServer.query.get_or_404(server_id)

    backup_dir = current_app.config.get('BACKUP_PATH', '').strip()
    if not backup_dir:
        return jsonify({'error': 'BACKUP_PATH is not configured'}), 400

    # Capture the real app object — the current_app proxy is not safe to use
    # inside a new thread because the request context will be gone by then.
    app = current_app._get_current_object()

    def _run_backup(sid=server_id, bdir=backup_dir):
        with app.app_context():
            # Re-query inside the thread's own session; the request-scoped
            # `server` instance must not be used across threads/sessions.
            s = GameServer.query.get(sid)
            if not s:
                logger.warning('Backup thread: server %s no longer exists', sid)
                return
            try:
                backup_service.backup_server(s, bdir)
            except Exception as e:
                logger.error('Backup failed for server=%s: %s', sid, e)

    threading.Thread(target=_run_backup, daemon=True).start()

    return jsonify({'ok': True, 'message': 'Backup started in background'})


@bp.route('/servers/<server_id>/backups', methods=['GET'])
@require_server_access
def list_backups(server_id):
    """Returns a list of existing backup archives for the given server.

    Scans the NFS share directory (BACKUP_NFS_PATH) for files matching
    the server's safe name.  Returns an empty list when no backups exist
    or the directory has not yet been created.

    Returns:
        200: List of ``{"filename": str, "size_mb": float, "created": str}``,
             sorted newest-first.  Empty list ``[]`` when none exist.
        500: ``{"error": "..."}`` on unexpected failure.
    """
    from app.services import backup as backup_service

    server = GameServer.query.get_or_404(server_id)
    backup_dir = current_app.config.get('BACKUP_PATH', '').strip()

    try:
        return jsonify(backup_service.list_backups(server, backup_dir))
    except Exception as e:
        logger.warning('list_backups failed for server=%s: %s', server_id, e)
        return jsonify({'error': 'Could not list backups'}), 500


@bp.route('/servers/<server_id>/ports/remove', methods=['POST'])
@require_admin
def remove_port(server_id):
    server = GameServer.query.get_or_404(server_id)
    data = request.get_json(silent=True) or {}
    port = data.get('port')

    if not port or not isinstance(port, int):
        return jsonify({'error': 'Invalid port'}), 400

    if port == server.game_port:
        return jsonify({'error': 'Cannot remove the primary game port'}), 400

    extra = list(server.extra_ports or [])
    port_nums = [e['port'] if isinstance(e, dict) else e for e in extra]
    if port not in port_nums:
        return jsonify({'error': 'Port not found'}), 404

    extra = [e for e in extra if (e['port'] if isinstance(e, dict) else e) != port]
    server.extra_ports = extra
    flag_modified(server, 'extra_ports')
    db.session.commit()

    # Update nginx config
    try:
        from app.services.nginx import NginxService
        NginxService().add_server(server)
    except Exception as e:
        return jsonify({'ok': True, 'nginx_warning': str(e), 'all_ports': server.all_ports})

    return jsonify({'ok': True, 'all_ports': server.all_ports})
