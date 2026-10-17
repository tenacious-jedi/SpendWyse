import logging
import re
import uuid
from contextvars import ContextVar
from typing import Optional

# Request-scoped correlation id. A ContextVar (not flask.g) so the same value
# is reachable from non-request code too — the event layer stamps it onto the
# envelope, and the logging filter below reads it — without passing it around.
_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)

# Inbound headers an upstream (gateway, client, Plaid/Stripe proxy) may already
# set; the first present and valid one is reused so a trace isn't broken at our
# edge. The response always echoes RESPONSE_HEADER.
INBOUND_HEADERS = ("X-Correlation-ID", "X-Request-ID")
RESPONSE_HEADER = "X-Correlation-ID"

# Accept only id-shaped values and cap the length, so an inbound header cannot
# inject newlines/control chars into log lines or bloat them.
_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_MAX_LEN = 128


def generate_correlation_id() -> str:
    return uuid.uuid4().hex


def sanitize_correlation_id(raw: Optional[str]) -> Optional[str]:
    """Normalize an inbound id to a safe token, or None if nothing usable."""
    if not raw:
        return None
    cleaned = _SAFE.sub("", raw.strip())[:_MAX_LEN]
    return cleaned or None


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def set_correlation_id(value: Optional[str]):
    """Set the current correlation id; returns a token for reset()."""
    return _correlation_id.set(value)


def reset_correlation_id(token) -> None:
    _correlation_id.reset(token)


class CorrelationIdFilter(logging.Filter):
    """Injects the current correlation id onto every record so a formatter can
    render it. Lines emitted outside a correlated context show '-'.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True
