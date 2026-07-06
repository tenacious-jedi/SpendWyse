import logging
import time

from flask import Flask, g, request


# Health probes are hit every few seconds by uptime monitors and would
# drown the useful signal.
SKIP_PATHS = {"/api/health/", "/api/health/deep"}


def init_app(app: Flask) -> None:
    # Flask's default logger is WARNING; drop it to INFO so request lines
    # actually show up during dev without extra logging config.
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def _start_timer() -> None:
        g._request_start_time = time.perf_counter()

    @app.after_request
    def _log_response(response):
        if request.path in SKIP_PATHS:
            return response

        start = getattr(g, "_request_start_time", None)
        if start is None:
            duration_ms = -1.0
        else:
            duration_ms = (time.perf_counter() - start) * 1000

        app.logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response
