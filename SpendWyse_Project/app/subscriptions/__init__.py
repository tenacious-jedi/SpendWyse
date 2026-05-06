from flask import Blueprint

subscriptions_bp = Blueprint("subscriptions", __name__, url_prefix="/api/subscriptions")

from . import routes  # noqa: E402, F401
