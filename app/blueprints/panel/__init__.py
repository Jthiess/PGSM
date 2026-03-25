from flask import Blueprint

bp = Blueprint('panel', __name__)

from app.blueprints.panel import routes  # noqa: E402, F401
