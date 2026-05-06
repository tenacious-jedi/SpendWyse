from flask import Blueprint

transactions_bp = Blueprint("transactions", __name__, url_prefix="/api/transactions")

from . import routes  # noqa: E402, F401
