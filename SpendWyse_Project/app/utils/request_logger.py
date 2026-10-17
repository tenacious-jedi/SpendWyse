import logging
import time

from flask import Flask, g, request

from app.utils.correlation import (
    INBOUND_HEADERS,
    RESPONSE_HEADER,
    CorrelationIdFilter,
    generate_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)


# Health probes are hit every few seconds by uptime monitors and would
# drown the useful signal.
SKIP_PATHS = {"/api/health/", "/api/health/deep"}

# Every line carries the correlation id in brackets, so a single request can be
# grepped across all of its log output.
_LOG_FORMAT = "%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"


def init_app(app: Flask) -> None:
    # Flask's default logger is WARNING; drop it to INFO so request lines
    # actually show up during dev without extra logging config.
    app.logger.setLevel(logging.INFO)
    _configure_logging(app)

    @app.before_request
    def _start_request() -> None:
        g._request_start_time = time.perf_counter()
        # Reuse an upstream id if one arrived; otherwise mint one.
        cid = _incoming_correlation_id() or generate_correlation_id()
        g.correlation_id = cid
        set_correlation_id(cid)

    @app.after_request
    def _log_response(response):
        # Echo on every response (health included) so callers can capture the id.
        cid = getattr(g, "correlation_id", None)
        if cid:
            response.headers[RESPONSE_HEADER] = cid

        if request.path in SKIP_PATHS:
            return response

        start = getattr(g, "_request_start_time", None)
        if start is None:
            duration_ms = -1.0
        else:
            duration_ms = (time.perf_counter() - start) * 1000

        # The correlation id is rendered by the formatter, so it is not
        # repeated in the message itself.
        app.logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response


def _incoming_correlation_id():
    for header in INBOUND_HEADERS:
        cid = sanitize_correlation_id(request.headers.get(header))
        if cid:
            return cid
    return None


def _configure_logging(app: Flask) -> None:
    # Own the app logger's handler so every line emitted through it carries the
    # correlation id. Replacing (not appending) keeps re-init — e.g. tests that
    # build several apps — from stacking duplicate handlers.
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(CorrelationIdFilter())
    app.logger.handlers = [handler]
    # We format and emit here; don't also bubble to the root logger (would
    # double-log, and without the correlation id).
    app.logger.propagate = False
