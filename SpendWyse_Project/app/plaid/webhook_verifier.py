"""Verify webhooks that Plaid POSTs to /api/plaid/webhook.

Plaid signs each request with an ES256 JWS placed in the
Plaid-Verification header. The JWS payload includes a
request_body_sha256 claim, which we recompute over the raw
request bytes and compare in constant time. The signing key is
fetched from Plaid via /webhook_verification_key/get keyed by
the `kid` in the JWS header, then cached in-process until Plaid
declares it expired.

Reference: https://plaid.com/docs/api/webhooks/webhook-verification
"""

import hashlib
import hmac
import logging
import threading
import time
from typing import Optional

import jwt
from jwt import PyJWK, PyJWTError

import plaid
from plaid.model.webhook_verification_key_get_request import (
    WebhookVerificationKeyGetRequest,
)

from .plaid_client import get_plaid_client


logger = logging.getLogger(__name__)


class WebhookVerificationError(Exception):
    """Raised for any verification failure. Callers should return 401
    without echoing the reason back to the caller."""


# Plaid's docs cap acceptable clock skew at 5 minutes.
MAX_IAT_AGE_SECONDS = 5 * 60

# kid -> (jwk_dict, expiry_unix_or_None). None expiry means "no expiry
# advertised" -- we still hold it, but a WebhookVerificationError on
# signature verify will evict + re-fetch (handled by the caller loop).
_KEY_CACHE: dict[str, tuple[dict, Optional[float]]] = {}
_CACHE_LOCK = threading.Lock()


def verify(header_value: Optional[str], raw_body: bytes) -> None:
    """Raise WebhookVerificationError if the request is not authentic.

    Returns None on success so callers can rely on control flow.
    """
    if not header_value:
        raise WebhookVerificationError("missing Plaid-Verification header")
    if raw_body is None:
        raise WebhookVerificationError("missing request body")

    try:
        unverified_header = jwt.get_unverified_header(header_value)
    except PyJWTError as exc:
        raise WebhookVerificationError(f"malformed JWS header: {exc}") from exc

    if unverified_header.get("alg") != "ES256":
        raise WebhookVerificationError("unexpected JWS alg (must be ES256)")
    kid = unverified_header.get("kid")
    if not kid:
        raise WebhookVerificationError("JWS header missing kid")

    jwk_dict = _get_key(kid)
    try:
        public_key = PyJWK.from_dict(jwk_dict).key
    except PyJWTError as exc:
        raise WebhookVerificationError(f"could not parse JWK: {exc}") from exc

    try:
        payload = jwt.decode(
            header_value,
            key=public_key,
            algorithms=["ES256"],
            # We only rely on iat freshness; iss/aud aren't set by Plaid.
            options={"require": ["iat"]},
        )
    except PyJWTError as exc:
        # Force a refresh on the next request in case Plaid rotated the
        # key without advertising an expired_at we saw.
        _evict(kid)
        raise WebhookVerificationError(f"signature verification failed: {exc}") from exc

    iat = payload.get("iat")
    if not isinstance(iat, (int, float)):
        raise WebhookVerificationError("iat missing or not numeric")
    if (time.time() - float(iat)) > MAX_IAT_AGE_SECONDS:
        raise WebhookVerificationError("JWS iat is older than 5 minutes")

    claimed_hash = payload.get("request_body_sha256")
    if not isinstance(claimed_hash, str):
        raise WebhookVerificationError("request_body_sha256 claim missing")

    actual_hash = hashlib.sha256(raw_body).hexdigest()
    if not hmac.compare_digest(actual_hash, claimed_hash):
        raise WebhookVerificationError("body hash mismatch")


def _get_key(kid: str) -> dict:
    with _CACHE_LOCK:
        cached = _KEY_CACHE.get(kid)
        if cached:
            jwk_dict, expiry = cached
            if expiry is None or expiry > time.time():
                return jwk_dict
            _KEY_CACHE.pop(kid, None)

    jwk_dict, expiry = _fetch_key(kid)

    with _CACHE_LOCK:
        _KEY_CACHE[kid] = (jwk_dict, expiry)
    return jwk_dict


def _fetch_key(kid: str) -> tuple[dict, Optional[float]]:
    client = get_plaid_client()
    try:
        resp = client.webhook_verification_key_get(
            WebhookVerificationKeyGetRequest(key_id=kid)
        )
    except plaid.ApiException as exc:
        raise WebhookVerificationError(
            f"could not fetch verification key {kid}"
        ) from exc

    key = resp.key
    jwk_dict = {
        "kty": key.kty,
        "kid": key.kid,
        "use": key.use,
        "alg": key.alg,
        "crv": key.crv,
        "x": key.x,
        "y": key.y,
    }

    expiry: Optional[float] = None
    expired_at = getattr(key, "expired_at", None)
    if expired_at:
        try:
            expiry = float(expired_at)
        except (TypeError, ValueError):
            expiry = None

    return jwk_dict, expiry


def _evict(kid: str) -> None:
    with _CACHE_LOCK:
        _KEY_CACHE.pop(kid, None)
