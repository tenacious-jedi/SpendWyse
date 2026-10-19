from datetime import datetime, timezone

from app.extensions import db


class IdempotencyKey(db.Model):
    """Ledger for client-supplied Idempotency-Key headers on mutating requests.

    A row is reserved (pending) before the handler runs, so a concurrent or
    retried request with the same (user, key) is detected by the UNIQUE
    constraint. Once the handler succeeds, the response status and body are
    stored here and replayed verbatim on any later retry of the same key.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_idempotency_user_key"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key = db.Column(db.String(255), nullable=False)

    # Method + path + a SHA-256 of the body, so the same key sent with a
    # different request can be rejected rather than silently replayed.
    method = db.Column(db.String(10), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)

    # NULL while the request is in flight (pending); set once it completes.
    status_code = db.Column(db.Integer, nullable=True)
    response_body = db.Column(db.JSON, nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
