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
        return _error("this bank is already linked", 409)

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
