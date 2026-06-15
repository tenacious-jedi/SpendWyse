from flask import Blueprint

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")

from . import routes  # noqa: E402, F401
