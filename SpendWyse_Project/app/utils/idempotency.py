import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import jsonify, make_response, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.idempotency_key import IdempotencyKey

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
MAX_KEY_LEN = 255

# A reservation older than this with no stored response is treated as abandoned
# (the producing request crashed), so a key can't wedge forever. Kept short so
# the window in which a crash-then-retry could re-run the handler is small.
PENDING_TTL = timedelta(seconds=60)


def _request_hash() -> str:
    body = request.get_data(cache=True) or b""
    basis = f"{request.method}\n{request.path}\n".encode("utf-8")
    return hashlib.sha256(basis + body).hexdigest()


def _age(created: datetime) -> timedelta:
    # Stored timestamps are tz-aware on Postgres; be defensive for other backends.
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - created


def _replay(row: IdempotencyKey):
    resp = make_response(jsonify(row.response_body), row.status_code or 200)
    resp.headers[REPLAYED_HEADER] = "true"
    return resp


def _release(row: IdempotencyKey) -> None:
    # Drop a reservation so a client can retry after a failed/non-cached attempt.
    try:
        db.session.delete(row)
        db.session.commit()
    except Exception:
        db.session.rollback()


def idempotent(fn):
    """Make a mutating endpoint idempotent per client-supplied Idempotency-Key.

    Opt-in: with no header, behavior is unchanged. With a key, the first
    successful (2xx) request is recorded and any retry of the same key replays
    the stored response without re-running the handler. A concurrent duplicate
    gets 409; the same key with a different request body gets 422.

    Guarantee: no duplicate side effect under normal concurrent/retried
    requests. A process crash in the narrow window between the handler's commit
    and recording the response can, once PENDING_TTL lapses, allow a retry to
    re-run — an accepted, bounded edge.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = (request.headers.get(HEADER) or "").strip()
        if not key:
            return fn(*args, **kwargs)
        if len(key) > MAX_KEY_LEN:
            return jsonify({"error": f"{HEADER} exceeds {MAX_KEY_LEN} characters"}), 400

        try:
            user_id = int(get_jwt_identity())
        except (TypeError, ValueError):
            # No authenticated identity to scope the key to; skip idempotency.
            return fn(*args, **kwargs)

        req_hash = _request_hash()

        existing = IdempotencyKey.query.filter_by(
            user_id=user_id, idempotency_key=key
        ).first()
        if existing is not None:
            conflict = _resolve_existing(existing, req_hash)
            if conflict is not None:
                return conflict
            # Stale pending reservation was cleared; fall through to re-reserve.

        reservation = IdempotencyKey(
            user_id=user_id,
            idempotency_key=key,
            method=request.method,
            path=request.path,
            request_hash=req_hash,
        )
        db.session.add(reservation)
        try:
            db.session.commit()
        except IntegrityError:
            # Lost the reservation race with a concurrent request carrying the
            # same key; defer to whatever that request recorded.
            db.session.rollback()
            existing = IdempotencyKey.query.filter_by(
                user_id=user_id, idempotency_key=key
            ).first()
            if existing is not None:
                conflict = _resolve_existing(existing, req_hash)
                if conflict is not None:
                    return conflict
            return fn(*args, **kwargs)

        try:
            rv = fn(*args, **kwargs)
        except Exception:
            _release(reservation)
            raise

        resp = make_response(rv)
        if 200 <= resp.status_code < 300:
            reservation.status_code = resp.status_code
            reservation.response_body = resp.get_json(silent=True)
            reservation.completed_at = datetime.now(timezone.utc)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        else:
            # Only successful responses are cached; release so a retry can run.
            _release(reservation)
        return resp

    return wrapper


def _resolve_existing(row: IdempotencyKey, req_hash: str):
    """Decide what to do when a row already exists for this (user, key).

    Returns a Response to short-circuit with, or None if the row was a stale
    pending reservation that has now been cleared so the caller can re-reserve.
    """
    if row.request_hash != req_hash:
        return jsonify({
            "error": f"{HEADER} was already used with a different request"
        }), 422

    if row.completed_at is None:
        # Still pending: either genuinely in flight, or abandoned by a crash.
        if _age(row.created_at) > PENDING_TTL:
            _release(row)
            return None
        return jsonify({
            "error": f"a request with this {HEADER} is already in progress"
        }), 409

    return _replay(row)
