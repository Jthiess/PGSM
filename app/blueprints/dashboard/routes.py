from flask import render_template
from app.auth import require_admin, require_management_access, is_admin, get_current_username
from app.blueprints.dashboard import bp
from app.models.server import GameServer


@bp.route('/')
@require_management_access
def index():
    if is_admin():
        servers = GameServer.query.all()
    else:
        from app.models.server_permission import ServerPermission
        username = get_current_username()
        if username:
            perms = ServerPermission.query.filter_by(username=username).all()
            server_ids = [p.server_id for p in perms]
            servers = GameServer.query.filter(GameServer.id.in_(server_ids)).all()
        else:
            servers = []
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
