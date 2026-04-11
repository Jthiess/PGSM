from flask import render_template, session, current_app
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


# ---------------------------------------------------------------------------
# NFS Mount Management
# Admin-only view that lists current NFS mounts and exposes controls to
# mount or unmount NFS exports. Delegates filesystem work to nfs_svc so
# the route stays thin and testable.
# ---------------------------------------------------------------------------

@bp.route('/nfs')
@require_admin
def nfs_mounts():
    """Render the NFS mount management page.

    Fetches the current NFS mount list from the service layer. On any
    unexpected error the page renders with an empty mount list rather than
    returning a 500, so the UI is still usable for adding new mounts.

    Returns:
        Rendered ``dashboard/nfs.html`` template with:
            - ``mounts`` (list[dict]): Active NFS mounts from /proc/mounts.
            - ``backup_nfs_path`` (str): Default path from config, used to
              pre-populate the mount form if set.
    """
    from app.services import nfs as nfs_svc
    try:
        mounts = nfs_svc.list_nfs_mounts()
    except Exception:
        mounts = []
    # BACKUP_NFS_PATH is optional config — used to pre-fill the mount form
    backup_nfs_path = current_app.config.get('BACKUP_NFS_PATH', '')
    return render_template('dashboard/nfs.html', mounts=mounts, backup_nfs_path=backup_nfs_path)
