import enum
from datetime import datetime, timezone
from app.extensions import db


class RuleMatchType(enum.Enum):
    merchant_exact = "merchant_exact"
    merchant_contains = "merchant_contains"
    keyword = "keyword"
    plaid_pfc = "plaid_pfc"


class TagRule(db.Model):
    __tablename__ = "tag_rules"
    # The same rule (same target tag, match type, and value) for a user is a
    # duplicate; the constraint prevents a double-submit creating two rules
    # that then both match the same transactions.
    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "tag_id", "match_type", "match_value",
            name="uq_tag_rule_dedup",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tag_id = db.Column(
        db.Integer, db.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True
    )

    match_type = db.Column(db.Enum(RuleMatchType), nullable=False)
    match_value = db.Column(db.String(255), nullable=False)
    priority = db.Column(db.Integer, nullable=False, default=100)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref=db.backref("tag_rules", lazy="dynamic"))
    tag = db.relationship("Tag", backref=db.backref("rules", lazy="dynamic"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tag_id": self.tag_id,
            "match_type": self.match_type.value,
            "match_value": self.match_value,
            "priority": self.priority,
            "is_active": self.is_active,
        }
