from datetime import datetime, timezone, timedelta
from flask import request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt,
    get_jwt_identity,
)
from app.extensions import db, jwt_blocklist, limiter
from app.models import User
from app.models.user import SubscriptionTier, TRIAL_DAYS
from app.utils.notifier import send_email
from . import auth_bp
from .password_reset import consume_token, issue_token


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _validate_signup_payload(data: dict):
    required = ["email", "password", "first_name", "last_name"]
    for field in required:
        if not data.get(field, "").strip():
            return f"{field} is required"
    if len(data["password"]) < 8:
        return "password must be at least 8 characters"
    return None


@auth_bp.post("/signup")
@limiter.limit("3 per minute")
def signup():
    data = request.get_json(silent=True) or {}

    err = _validate_signup_payload(data)
    if err:
        return _error(err, 400)

    email = data["email"].lower().strip()
    if User.query.filter_by(email=email).first():
        return _error("email already registered", 409)

    user = User(
        email=email,
        first_name=data["first_name"].strip(),
        last_name=data["last_name"].strip(),
        subscription_tier=SubscriptionTier.free_trial,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS),
    )
    user.set_password(data["password"])
    db.session.add(user)
    # Get user.id before the Stripe call.
    db.session.flush()

    try:
        from app.subscriptions.stripe_client import create_customer
        stripe_customer_id = create_customer(
            email=user.email,
            name=f"{user.first_name} {user.last_name}",
        )
        user.stripe_customer_id = stripe_customer_id
    except Exception:
        # Stripe failure must not block account creation.
        pass

    db.session.commit()

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))

    return jsonify({
        "user": user.to_dict(),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }), 201


@auth_bp.post("/login")
@limiter.limit("5 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").lower().strip()
    password = data.get("password", "")

    if not email or not password:
        return _error("email and password are required", 400)

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return _error("invalid email or password", 401)

    if not user.is_active:
        return _error("account is deactivated", 403)

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))

    return jsonify({
        "user": user.to_dict(),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }), 200


@auth_bp.post("/logout")
@jwt_required(verify_type=False)
def logout():
    jti = get_jwt()["jti"]
    jwt_blocklist.add(jti)
    return jsonify({"message": "logged out"}), 200


@auth_bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    user_id = get_jwt_identity()
    access_token = create_access_token(identity=user_id)
    return jsonify({"access_token": access_token}), 200


@auth_bp.get("/me")
@jwt_required()
def me():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return _error("user not found", 404)
    return jsonify({"user": user.to_dict()}), 200


@auth_bp.patch("/me")
@jwt_required()
def update_me():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return _error("user not found", 404)

    data = request.get_json(silent=True) or {}

    if "first_name" in data:
        first_name = (data["first_name"] or "").strip()
        if not first_name:
            return _error("first_name cannot be empty", 400)
        user.first_name = first_name

    if "last_name" in data:
        last_name = (data["last_name"] or "").strip()
        if not last_name:
            return _error("last_name cannot be empty", 400)
        user.last_name = last_name

    if "email" in data:
        new_email = (data["email"] or "").lower().strip()
        if not new_email:
            return _error("email cannot be empty", 400)
        if new_email != user.email:
            collision = User.query.filter_by(email=new_email).first()
            if collision:
                return _error("email already in use", 409)
            user.email = new_email

    db.session.commit()
    return jsonify({"user": user.to_dict()}), 200


@auth_bp.post("/change-password")
@jwt_required()
def change_password():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return _error("user not found", 404)

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not current_password or not new_password:
        return _error("current_password and new_password are required", 400)
    if not user.check_password(current_password):
        return _error("current password is incorrect", 401)
    if len(new_password) < 8:
        return _error("new password must be at least 8 characters", 400)
    if new_password == current_password:
        return _error("new password must differ from the current one", 400)

    user.set_password(new_password)
    db.session.commit()

    # Revoke the active JWT so the caller must re-login on this device.
    jti = get_jwt()["jti"]
    jwt_blocklist.add(jti)

    return jsonify({"message": "password changed"}), 200


@auth_bp.post("/forgot-password")
@limiter.limit("3 per minute")
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").lower().strip()

    # Always return 200 to avoid leaking which emails are registered.
    response = jsonify({"message": "if an account exists, a reset link has been sent"})

    if not email:
        return response, 200

    user = User.query.filter_by(email=email).first()
    if not user or not user.is_active:
        return response, 200

    raw_token = issue_token(user)
    reset_url = current_app.config.get("PASSWORD_RESET_URL", "")
    link = f"{reset_url}?token={raw_token}" if reset_url else raw_token

    body = (
        f"Hi {user.first_name},\n\n"
        f"We received a request to reset your SpendWyse password. "
        f"Use the link below within the next hour:\n\n"
        f"{link}\n\n"
        f"If you did not request this, you can ignore this email.\n\n"
        f"— SpendWyse"
    )
    error = send_email(user.email, "[SpendWyse] Reset your password", body)
    if error:
        current_app.logger.warning("password reset email failed: %s", error)

    return response, 200


@auth_bp.post("/reset-password")
@limiter.limit("5 per minute")
def reset_password():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("new_password", "")

    if not token or not new_password:
        return _error("token and new_password are required", 400)
    if len(new_password) < 8:
        return _error("new password must be at least 8 characters", 400)

    user = consume_token(token, new_password)
    if not user:
        return _error("token is invalid or has expired", 400)

    return jsonify({"message": "password reset; please log in"}), 200
