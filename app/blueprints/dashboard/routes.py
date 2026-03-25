from flask import render_template
from app.auth import require_admin
from app.blueprints.dashboard import bp
from app.models.server import GameServer


@bp.route('/')
@require_admin
def index():
    servers = GameServer.query.all()
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
