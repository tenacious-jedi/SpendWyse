from flask import Blueprint

health_bp = Blueprint("health", __name__, url_prefix="/api/health")

from . import routes  # noqa: E402, F401
