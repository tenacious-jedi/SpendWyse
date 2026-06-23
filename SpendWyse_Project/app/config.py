import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.environ["JWT_SECRET_KEY"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 15))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 30))
    )
    JWT_TOKEN_LOCATION = ["headers"]
    JWT_HEADER_TYPE = "Bearer"

    PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
    PLAID_SECRET = os.getenv("PLAID_SECRET", "")
    PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")
    PLAID_TOKEN_ENCRYPTION_KEY = os.getenv("PLAID_TOKEN_ENCRYPTION_KEY", "")

    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    STRIPE_PRICE_INDIVIDUAL_MONTHLY = os.getenv("STRIPE_PRICE_INDIVIDUAL_MONTHLY", "")
    STRIPE_PRICE_INDIVIDUAL_YEARLY = os.getenv("STRIPE_PRICE_INDIVIDUAL_YEARLY", "")
    STRIPE_PRICE_TEAM = os.getenv("STRIPE_PRICE_TEAM", "")
    STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:3000/subscription/success")
    STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "http://localhost:3000/subscription/cancel")

    ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "false").lower() in ("true", "1", "yes")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")

    KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    KAFKA_CONSUMER_GROUP = os.getenv("KAFKA_CONSUMER_GROUP", "spendwyse-alerts")

    PASSWORD_RESET_URL = os.getenv(
        "PASSWORD_RESET_URL", "http://localhost:3000/reset-password"
    )


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}


def get_config():
    env = os.getenv("FLASK_ENV", "development")
    return config_map.get(env, DevelopmentConfig)
