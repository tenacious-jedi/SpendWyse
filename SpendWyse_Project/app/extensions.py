from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

# In-memory JWT blocklist for logged-out tokens.
# Replace with Redis for production multi-instance deployments.
jwt_blocklist: set[str] = set()
