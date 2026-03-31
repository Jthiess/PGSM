from flask import render_template, session
from app.auth import require_admin, require_management_access, is_admin
from app.blueprints.dashboard import bp
from app.models.server import GameServer


def _permitted_server_ids():
    """Return list of server IDs the current server_user may access."""
    from app.models.server_permission import ServerPermission
    from sqlalchemy import or_
    raw = session.get('ldap_raw_username')
    display = session.get('ldap_username')
    conditions = []
    if raw:
        conditions.append(ServerPermission.username == raw)
    if display and display != raw:
        conditions.append(ServerPermission.username == display)
    if not conditions:
        return []
    perms = ServerPermission.query.filter(or_(*conditions)).all()
    return [p.server_id for p in perms]


@bp.route('/')
@require_management_access
def index():
    if is_admin():
        servers = GameServer.query.all()
    else:
        server_ids = _permitted_server_ids()
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
