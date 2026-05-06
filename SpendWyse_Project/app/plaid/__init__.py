from flask import Blueprint

plaid_bp = Blueprint("plaid", __name__, url_prefix="/api/plaid")

from . import routes  # noqa: E402, F401
