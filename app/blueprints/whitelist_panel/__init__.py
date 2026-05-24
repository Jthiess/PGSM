from flask import Blueprint

bp = Blueprint('whitelist_panel', __name__)

from app.blueprints.whitelist_panel import routes  # noqa: E402, F401
