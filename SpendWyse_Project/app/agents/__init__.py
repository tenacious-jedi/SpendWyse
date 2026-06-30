from flask import Blueprint

agents_bp = Blueprint("agents", __name__, url_prefix="/api/agents")

from . import routes  # noqa: E402, F401
