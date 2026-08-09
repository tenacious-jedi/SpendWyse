from flask import Blueprint

teams_bp = Blueprint("teams", __name__, url_prefix="/api/teams")

from . import routes  # noqa: E402, F401
