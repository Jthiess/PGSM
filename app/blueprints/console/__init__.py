from flask import Blueprint

bp = Blueprint('console', __name__)

from app.blueprints.console import routes  # noqa: E402, F401
