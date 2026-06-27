from flask import Blueprint

recurring_bp = Blueprint("recurring", __name__, url_prefix="/api/recurring")

from . import routes  # noqa: E402, F401
