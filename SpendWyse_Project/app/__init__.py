from flask import Flask
from flask_cors import CORS
from app.config import get_config
from app.extensions import db, migrate, jwt, jwt_blocklist


def create_app():
    app = Flask(__name__)
    app.config.from_object(get_config())

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # Restrict to known frontend origins; never use "*" with JWT or credentials.
    CORS(
        app,
        origins=app.config["CORS_ALLOWED_ORIGINS"],
        allow_headers=["Authorization", "Content-Type"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        return jwt_payload["jti"] in jwt_blocklist

    @jwt.revoked_token_loader
    def revoked_token_response(jwt_header, jwt_payload):
        from flask import jsonify
        return jsonify({"error": "token has been revoked"}), 401

    @jwt.expired_token_loader
    def expired_token_response(jwt_header, jwt_payload):
        from flask import jsonify
        return jsonify({"error": "token has expired"}), 401

    @jwt.invalid_token_loader
    def invalid_token_response(error):
        from flask import jsonify
        return jsonify({"error": "invalid token"}), 422

    @jwt.unauthorized_loader
    def missing_token_response(error):
        from flask import jsonify
        return jsonify({"error": "authorization token required"}), 401

    from app.auth import auth_bp
    from app.transactions import transactions_bp
    from app.plaid import plaid_bp
    from app.subscriptions import subscriptions_bp
    from app.tags import tags_bp, tag_rules_bp, spend_caps_bp
    from app.alerts import alerts_bp
    from app.reports import reports_bp
    from app.recurring import recurring_bp
    from app.agents import agents_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(plaid_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(tags_bp)
    app.register_blueprint(tag_rules_bp)
    app.register_blueprint(spend_caps_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(recurring_bp)
    app.register_blueprint(agents_bp)

    from app.models import (  # noqa: F401
        User,
        Subscription,
        Team,
        TeamMember,
        Transaction,
        PlaidItem,
        Tag,
        TagRule,
        SpendCap,
        Alert,
        PasswordResetToken,
    )

    return app
