from flask import Blueprint

bp = Blueprint('whitelist_panel', __name__, url_prefix='/whitelist')

from app.blueprints.whitelist_panel import routes  # noqa: E402, F401
