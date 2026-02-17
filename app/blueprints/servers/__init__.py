from flask import Blueprint

bp = Blueprint('servers', __name__)

from app.blueprints.servers import routes  # noqa: E402, F401
