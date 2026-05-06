from flask import Blueprint

budgets_bp = Blueprint("budgets", __name__, url_prefix="/api/budgets")

from . import routes  # noqa: E402, F401
