from flask import Blueprint

bp = Blueprint('admin_panel', __name__, url_prefix='/admin')

from app.blueprints.admin_panel import routes  # noqa: E402, F401
