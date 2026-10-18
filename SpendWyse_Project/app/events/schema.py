import uuid
from datetime import datetime, timezone
from typing import Any

from app.utils.correlation import get_correlation_id

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
        # Correlation id of the request that produced this event, so the trace
        # continues across the relay and consumers. None if enqueued outside a
        # request context.
        "correlation_id": get_correlation_id(),
        "payload": payload,
    }
