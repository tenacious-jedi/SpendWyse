from flask import request, jsonify
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt,
    get_jwt_identity,
)
from app.extensions import db, jwt_blocklist
from app.models import User
from . import auth_bp


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
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    access_token = create_access_token(identity=str(user.id))
    refresh_token = create_refresh_token(identity=str(user.id))

    return jsonify({
        "user": user.to_dict(),
        "access_token": access_token,
        "refresh_token": refresh_token,
    }), 201


@auth_bp.post("/login")
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
