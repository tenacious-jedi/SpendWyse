from flask import current_app, jsonify
from sqlalchemy import text

from app.extensions import db
from . import health_bp


# Bounded so a stalled dependency cannot make the deep probe hang.
DEEP_TIMEOUT_MS = 1500


@health_bp.get("/")
def liveness():
    return jsonify({"status": "ok"}), 200


@health_bp.get("/deep")
def readiness():
    checks = {
        "db": _check_db(),
        "kafka": _check_kafka(),
    }
    all_ok = all(c["ok"] for c in checks.values())
    payload = {"status": "ok" if all_ok else "degraded"}
    payload.update(checks)
    return jsonify(payload), 200 if all_ok else 503


def _check_db() -> dict:
    try:
        db.session.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def _check_kafka() -> dict:
    bootstrap = current_app.config.get("KAFKA_BOOTSTRAP_SERVERS", "")
    if not bootstrap:
        return {"ok": True, "note": "not configured"}

    # Import inside the function so a missing kafka install still lets
    # the shallow / endpoint answer.
    try:
        from kafka import KafkaProducer
        from kafka.errors import KafkaError
    except Exception as exc:
        return {"ok": False, "error": f"kafka client unavailable: {exc}"}

    producer = None
    try:
        producer = KafkaProducer(
            bootstrap_servers=[s.strip() for s in bootstrap.split(",") if s.strip()],
            request_timeout_ms=DEEP_TIMEOUT_MS,
            api_version_auto_timeout_ms=DEEP_TIMEOUT_MS,
            reconnect_backoff_ms=100,
            retries=0,
        )
        return {"ok": producer.bootstrap_connected()}
    except KafkaError as exc:
        return {"ok": False, "error": str(exc)[:200]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
    finally:
        if producer is not None:
            try:
                producer.close(timeout=1)
            except Exception:
                pass
