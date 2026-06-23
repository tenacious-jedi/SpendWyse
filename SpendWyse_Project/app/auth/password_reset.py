import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.extensions import db
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User


# Tokens are valid for one hour; the user has to re-request after that.
TOKEN_TTL = timedelta(hours=1)
TOKEN_BYTES = 32


def issue_token(user: User) -> str:
    """Mint a single-use reset token. Returns the raw secret to email.

    Only the hash of the secret is persisted, so a DB leak does not
    let an attacker reset anyone's password.
    """
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    record = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash(raw),
        expires_at=datetime.now(timezone.utc) + TOKEN_TTL,
    )
    db.session.add(record)
    db.session.commit()
    return raw


def consume_token(raw_token: str, new_password: str) -> Optional[User]:
    """Validate and use a reset token. Returns the User on success, None otherwise.

    Constant-time hash comparison via hmac.compare_digest.
    Marks the token used_at so it cannot be replayed.
    """
    token_hash = _hash(raw_token)

    record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
    if not record:
        return None
    if not hmac.compare_digest(record.token_hash, token_hash):
        return None
    if not record.is_consumable():
        return None

    user = db.session.get(User, record.user_id)
    if not user or not user.is_active:
        return None

    user.set_password(new_password)
    record.used_at = datetime.now(timezone.utc)
    db.session.commit()
    return user


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
