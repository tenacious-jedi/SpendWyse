from flask import request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity

import plaid
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products

from app.extensions import db
from app.models.plaid_item import PlaidItem
from app.utils.decorators import require_tier
from . import plaid_bp
from .plaid_client import get_plaid_client
from .sync_service import sync_item
from .webhook_verifier import WebhookVerificationError, verify as verify_webhook


ALL_TIERS = (
    "free_trial",
    "free_readonly",
    "individual_monthly",
    "individual_yearly",
    "team",
)
WRITE_TIERS = (
    "free_trial",
    "individual_monthly",
    "individual_yearly",
    "team",
)


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _uid() -> int:
    return int(get_jwt_identity())


def _plaid_error(exc: plaid.ApiException):
    # Plaid returns a JSON body in `exc.body`; surface its error_code to the client.
    return jsonify({
        "error": "plaid api error",
        "details": getattr(exc, "body", None),
    }), 502


@plaid_bp.post("/link/token")
@require_tier(*WRITE_TIERS)
def create_link_token():
    user_id = _uid()
    try:
        req = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id=str(user_id)),
            client_name="SpendWyse",
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
        )
        resp = get_plaid_client().link_token_create(req)
    except plaid.ApiException as exc:
        return _plaid_error(exc)

    return jsonify({"link_token": resp.link_token, "expiration": resp.expiration.isoformat()}), 200


@plaid_bp.post("/link/exchange")
@require_tier(*WRITE_TIERS)
def exchange_public_token():
    data = request.get_json(silent=True) or {}
    public_token = data.get("public_token")
    if not public_token:
        return _error("public_token is required", 400)

    try:
        resp = get_plaid_client().item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
    except plaid.ApiException as exc:
        return _plaid_error(exc)

    existing = PlaidItem.query.filter_by(plaid_item_id=resp.item_id).first()
    if existing:
        # Never touch an item owned by another user.
        if existing.user_id != _uid():
            return _error("this bank is already linked", 409)

        # An active item is already usable; re-linking it is a no-op conflict.
        if existing.is_active:
            return _error("this bank is already linked", 409)

        # Reactivate a previously deactivated link (e.g. the user repaired it
        # through Link after an ITEM_LOGIN_REQUIRED). Exchange issues a fresh
        # access token, so store it in case the old one was invalidated.
        existing.access_token = resp.access_token
        if data.get("institution_id"):
            existing.institution_id = data.get("institution_id")
        if data.get("institution_name"):
            existing.institution_name = data.get("institution_name")
        existing.is_active = True
        db.session.commit()
        return jsonify({"plaid_item": existing.to_dict()}), 200

    pit = PlaidItem(
        user_id=_uid(),
        plaid_item_id=resp.item_id,
        institution_id=data.get("institution_id"),
        institution_name=data.get("institution_name"),
    )
    # Setter encrypts before storing.
    pit.access_token = resp.access_token
    db.session.add(pit)
    db.session.commit()

    return jsonify({"plaid_item": pit.to_dict()}), 201


@plaid_bp.post("/sync")
@require_tier(*WRITE_TIERS)
def sync_transactions():
    items = PlaidItem.query.filter_by(user_id=_uid(), is_active=True).all()
    if not items:
        return jsonify({"synced": [], "message": "no linked banks"}), 200

    results = []
    for item in items:
        try:
            results.append(sync_item(item))
        except plaid.ApiException as exc:
            db.session.rollback()
            results.append({
                "plaid_item_id": item.id,
                "error": "plaid api error",
                "details": getattr(exc, "body", None),
            })

    return jsonify({"synced": results}), 200


@plaid_bp.get("/accounts")
@require_tier(*ALL_TIERS)
def list_accounts():
    items = PlaidItem.query.filter_by(user_id=_uid(), is_active=True).all()

    accounts = []
    for item in items:
        try:
            resp = get_plaid_client().accounts_get(
                AccountsGetRequest(access_token=item.access_token)
            )
        except plaid.ApiException as exc:
            return _plaid_error(exc)

        for acct in resp.accounts:
            accounts.append({
                "account_id": acct.account_id,
                "name": acct.name,
                "mask": acct.mask,
                "type": str(acct.type),
                "subtype": str(acct.subtype) if acct.subtype else None,
                "institution_name": item.institution_name,
                "plaid_item_id": item.id,
            })

    return jsonify({"accounts": accounts}), 200


@plaid_bp.get("/items")
@require_tier(*ALL_TIERS)
def list_items():
    items = (
        PlaidItem.query
        .filter_by(user_id=_uid())
        .order_by(PlaidItem.created_at.desc())
        .all()
    )
    return jsonify({"items": [item.to_dict() for item in items]}), 200


@plaid_bp.delete("/items/<int:item_id>")
@require_tier(*WRITE_TIERS)
def delete_item(item_id: int):
    item = PlaidItem.query.filter_by(id=item_id, user_id=_uid()).first()
    if not item:
        return _error("plaid item not found", 404)

    try:
        get_plaid_client().item_remove(
            ItemRemoveRequest(access_token=item.access_token)
        )
    except plaid.ApiException as exc:
        body = getattr(exc, "body", "") or ""
        # If Plaid says the item is already gone, treat the local delete
        # as the user-visible success path.
        if "ITEM_NOT_FOUND" not in str(body):
            return _plaid_error(exc)

    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "plaid item removed"}), 200


@plaid_bp.post("/items/<int:item_id>/sync")
@require_tier(*WRITE_TIERS)
def sync_one_item(item_id: int):
    item = PlaidItem.query.filter_by(
        id=item_id, user_id=_uid(), is_active=True
    ).first()
    if not item:
        return _error("plaid item not found", 404)

    try:
        result = sync_item(item)
    except plaid.ApiException as exc:
        db.session.rollback()
        return _plaid_error(exc)

    return jsonify({"synced": result}), 200


@plaid_bp.post("/webhook")
def receive_webhook():
    """Plaid-facing endpoint. No JWT / tier decorator: Plaid calls this
    directly, and authenticity is enforced by the ES256 JWS in the
    Plaid-Verification header (see webhook_verifier).

    We always reply 200 for anything we consider handled or safely
    ignorable so Plaid does not retry unnecessarily; genuinely bad
    signatures get 401, and only unexpected server errors get 500.
    """
    raw_body = request.get_data(cache=True)
    header_value = request.headers.get("Plaid-Verification")

    if current_app.config.get("PLAID_WEBHOOK_VERIFY", True):
        try:
            verify_webhook(header_value, raw_body)
        except WebhookVerificationError as exc:
            current_app.logger.warning("plaid webhook rejected: %s", exc)
            return jsonify({"error": "invalid signature"}), 401
    else:
        current_app.logger.warning(
            "PLAID_WEBHOOK_VERIFY is false; accepting webhook without signature check"
        )

    payload = request.get_json(silent=True) or {}
    webhook_type = payload.get("webhook_type")
    webhook_code = payload.get("webhook_code")
    plaid_item_id = payload.get("item_id")

    if webhook_type == "TRANSACTIONS" and webhook_code == "SYNC_UPDATES_AVAILABLE":
        return _dispatch_transactions_sync(plaid_item_id)

    if webhook_type == "ITEM":
        return _handle_item_webhook(webhook_code, plaid_item_id, payload)

    current_app.logger.info(
        "plaid webhook ignored type=%s code=%s item=%s",
        webhook_type, webhook_code, plaid_item_id,
    )
    return jsonify({"received": True, "handled": False}), 200


def _dispatch_transactions_sync(plaid_item_id):
    if not plaid_item_id:
        current_app.logger.warning("plaid SYNC_UPDATES_AVAILABLE missing item_id")
        return jsonify({"received": True, "handled": False}), 200

    item = PlaidItem.query.filter_by(
        plaid_item_id=plaid_item_id, is_active=True
    ).first()
    if not item:
        # The item may have been removed since Plaid queued the webhook.
        # Ack so Plaid stops retrying.
        current_app.logger.info(
            "plaid webhook for unknown/inactive item %s; acking", plaid_item_id
        )
        return jsonify({"received": True, "handled": False}), 200

    try:
        result = sync_item(item)
    except plaid.ApiException as exc:
        db.session.rollback()
        current_app.logger.exception(
            "plaid sync failed for item %s during webhook", plaid_item_id
        )
        # Return 500 so Plaid retries; we want the next attempt to try again.
        return jsonify({
            "error": "sync failed",
            "details": getattr(exc, "body", None),
        }), 500

    return jsonify({"received": True, "handled": True, "synced": result}), 200


# ITEM webhook codes that unambiguously mean the link is broken and can only be
# fixed by the user re-authenticating through Link. These carry no nested error.
_ITEM_DEACTIVATE_CODES = frozenset({
    "PENDING_EXPIRATION",
    "USER_PERMISSION_REVOKED",
})
# The ITEM/ERROR webhook also fires for transient problems (institution down,
# rate limits, internal errors) that recover on their own. Only this nested
# error_code actually requires the user to re-authenticate, so it is the only
# ERROR case we deactivate on.
_ITEM_REAUTH_ERROR_CODE = "ITEM_LOGIN_REQUIRED"


def _handle_item_webhook(webhook_code, plaid_item_id, payload):
    if not plaid_item_id:
        current_app.logger.warning("plaid ITEM webhook missing item_id")
        return jsonify({"received": True, "handled": False}), 200

    # Plaid nests the underlying cause under an `error` object for ERROR codes.
    error_detail = payload.get("error") or {}
    plaid_error_code = error_detail.get("error_code")

    if webhook_code == "ERROR":
        should_deactivate = plaid_error_code == _ITEM_REAUTH_ERROR_CODE
    else:
        should_deactivate = webhook_code in _ITEM_DEACTIVATE_CODES

    if not should_deactivate:
        current_app.logger.info(
            "plaid ITEM webhook ignored code=%s error_code=%s item=%s",
            webhook_code, plaid_error_code, plaid_item_id,
        )
        return jsonify({"received": True, "handled": False}), 200

    item = PlaidItem.query.filter_by(plaid_item_id=plaid_item_id).first()
    if not item:
        current_app.logger.info(
            "plaid ITEM webhook for unknown item %s; acking", plaid_item_id
        )
        return jsonify({"received": True, "handled": False}), 200

    if not item.is_active:
        current_app.logger.info(
            "plaid item %s already inactive; code=%s error_code=%s",
            plaid_item_id, webhook_code, plaid_error_code,
        )
        return jsonify({"received": True, "handled": True}), 200

    item.is_active = False
    db.session.commit()
    current_app.logger.warning(
        "deactivated plaid item %s after ITEM webhook code=%s error_code=%s",
        plaid_item_id, webhook_code, plaid_error_code,
    )
    return jsonify({"received": True, "handled": True}), 200
