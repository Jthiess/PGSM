from flask import render_template
from app.auth import require_management_access, is_admin, get_permitted_server_ids
from app.blueprints.dashboard import bp
from app.models.server import GameServer


@bp.route('/')
@require_management_access
def index():
    if is_admin():
        servers = GameServer.query.all()
    else:
        server_ids = get_permitted_server_ids()
        servers = GameServer.query.filter(GameServer.id.in_(server_ids)).all() if server_ids else []
    running = sum(1 for s in servers if s.status == 'running')
    stopped = sum(1 for s in servers if s.status == 'stopped')
    creating = sum(1 for s in servers if s.status == 'creating')
    return render_template(
        'dashboard/index.html',
        servers=servers,
        running=running,
        stopped=stopped,
        creating=creating,
    )
