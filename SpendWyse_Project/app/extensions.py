from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

# In-memory JWT blocklist for logged-out tokens.
# Replace with Redis for production multi-instance deployments.
jwt_blocklist: set[str] = set()

# Storage URI is read from app config at init_app time; memory:// by default.
limiter = Limiter(key_func=get_remote_address)
