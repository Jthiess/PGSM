from flask import jsonify, request

from app.blueprints.api import bp
from app.models.server import GameServer


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
