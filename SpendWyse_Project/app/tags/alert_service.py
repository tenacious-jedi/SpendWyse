from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.alert import Alert, AlertLevel
from app.models.spend_cap import SpendCap
from app.models.tag import Tag
from app.models.user import User
from app.utils.notifier import send_email
from .cap_evaluator import evaluate_cap


def check_caps_and_notify(user_id: int, only_tag_id: Optional[int] = None) -> list[dict]:
    """Evaluate the user's active caps; for any at warn/alert level, write
    a deduped Alert row and try to deliver it via email.

    Pass only_tag_id to scope the check to one cap (e.g. after a single
    transaction create touches one tag).
    """
    user = db.session.get(User, user_id)
    if not user:
        return []

    caps_q = SpendCap.query.filter_by(user_id=user_id, is_active=True)
    if only_tag_id is not None:
        caps_q = caps_q.filter_by(tag_id=only_tag_id)

    actions: list[dict] = []
    for cap in caps_q.all():
        result = evaluate_cap(cap)
        status = result["status"]
        if status == "ok":
            continue

        level = AlertLevel.alert if status == "alert" else AlertLevel.warn
        period_start = date.fromisoformat(result["period_start"])

        if _already_alerted(user_id, cap.id, period_start, level):
            continue

        alert = Alert(
            user_id=user_id,
            spend_cap_id=cap.id,
            level=level,
            period_start=period_start,
            spent=Decimal(result["spent"]),
            limit_amount=Decimal(result["limit_amount"]),
            pct=result["pct"],
        )
        db.session.add(alert)
        try:
            db.session.commit()
        except IntegrityError:
            # Lost a race with a concurrent insert; treat as already alerted.
            db.session.rollback()
            continue

        tag = db.session.get(Tag, cap.tag_id)
        subject, body = _compose(user, tag, result, level)
        error = send_email(user.email, subject, body)

        if error:
            alert.delivery_error = error
        else:
            alert.delivered_at = datetime.now(timezone.utc)
        db.session.commit()

        actions.append({
            "cap_id": cap.id,
            "alert_id": alert.id,
            "level": level.value,
            "delivered": error is None,
        })

    return actions


def _already_alerted(user_id: int, cap_id: int, period_start: date, level: AlertLevel) -> bool:
    return db.session.query(
        Alert.query.filter_by(
            user_id=user_id,
            spend_cap_id=cap_id,
            period_start=period_start,
            level=level,
        ).exists()
    ).scalar()


def _compose(user: User, tag: Optional[Tag], result: dict, level: AlertLevel) -> tuple[str, str]:
    tag_name = tag.name if tag else f"tag #{result['tag_id']}"
    pct = result["pct"]
    currency = result["currency"]

    if level == AlertLevel.alert:
        subject = f"[SpendWyse] You've reached {pct}% of your {tag_name} budget"
    else:
        subject = f"[SpendWyse] Heads up: {pct}% of your {tag_name} budget"

    body = (
        f"Hi {user.first_name},\n\n"
        f"You've spent {currency} {result['spent']} of your "
        f"{currency} {result['limit_amount']} {result['period']} {tag_name} budget "
        f"({pct}%).\n\n"
        f"This period ends on {result['period_end']}.\n\n"
        f"— SpendWyse"
    )
    return subject, body
