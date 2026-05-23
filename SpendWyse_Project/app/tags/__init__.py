from flask import Blueprint

tags_bp = Blueprint("tags", __name__, url_prefix="/api/tags")
tag_rules_bp = Blueprint("tag_rules", __name__, url_prefix="/api/tag-rules")
spend_caps_bp = Blueprint("spend_caps", __name__, url_prefix="/api/spend-caps")

from . import routes  # noqa: E402, F401
