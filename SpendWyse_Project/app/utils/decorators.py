from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity
from app.extensions import db


def require_tier(*allowed_tiers: str):
    """
    Decorator that enforces subscription tier access.
    Subsumes @jwt_required() — do not stack both.

    Usage:
        @require_tier("individual_monthly", "individual_yearly", "team")
        def my_route():
            ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()

            from app.models.user import User
            user_id = int(get_jwt_identity())
            user = db.session.get(User, user_id)

            if not user or not user.is_active:
                return jsonify({"error": "user not found"}), 404

            effective = user.effective_tier
            if effective.value not in allowed_tiers:
                return jsonify({
                    "error": "subscription upgrade required",
                    "current_tier": effective.value,
                    "required_tiers": list(allowed_tiers),
                }), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator
