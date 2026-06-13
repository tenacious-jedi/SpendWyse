import uuid
from datetime import datetime, timezone
from typing import Any

# Event type names are dot-namespaced so consumers can filter by prefix later
# (e.g. all spendwyse.transactions.*) without coordinating with publishers.
TRANSACTION_TAGGED = "spendwyse.transactions.tagged"

ENVELOPE_VERSION = 1


def build_envelope(event_type: str, payload: dict[str, Any]) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "event_version": ENVELOPE_VERSION,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
