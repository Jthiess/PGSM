from flask import jsonify, request

from app.blueprints.api import bp
from app.models.server import GameServer
from app.services.ssh import SSHManager

_ssh_mgr = SSHManager()


@bp.route('/nodes')
def nodes():
    from app.services.proxmox import ProxmoxService
    try:
        return jsonify(ProxmoxService().get_nodes())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/minecraft/versions')
def minecraft_versions():
    from app.services.minecraft import MinecraftService
    snapshots = request.args.get('snapshots', 'false').lower() == 'true'
    try:
        return jsonify(MinecraftService().get_available_versions(include_snapshots=snapshots))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/servers/<server_id>/status')
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


@bp.route('/servers/<server_id>/metrics')
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
