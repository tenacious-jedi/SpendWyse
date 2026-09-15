from datetime import date
from decimal import Decimal, InvalidOperation

from flask import request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import and_

from app.events.outbox import enqueue
from app.events.schema import TRANSACTION_TAGGED
from app.extensions import db
from app.models.transaction import Transaction, TransactionSource, TransactionType
from app.tags.rule_engine import apply_rules
from app.utils.decorators import require_tier
from . import transactions_bp

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

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _error(message: str, status: int):
    return jsonify({"error": message}), status


def _get_current_user_id() -> int:
    return int(get_jwt_identity())


def _parse_date(value: str):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


@transactions_bp.get("/")
@require_tier(*ALL_TIERS)
def list_transactions():
    user_id = _get_current_user_id()

    page = max(1, request.args.get("page", 1, type=int))
    page_size = max(
        1,
        min(
            request.args.get("page_size", DEFAULT_PAGE_SIZE, type=int),
            MAX_PAGE_SIZE,
        ),
    )

    # Optional filters
    category = request.args.get("category")
    start_date = _parse_date(request.args.get("start_date"))
    end_date = _parse_date(request.args.get("end_date"))
    transaction_type = request.args.get("type")

    # Reject an inverted range up front; otherwise the filters below silently
    # return an empty list instead of signalling the bad input.
    if start_date and end_date and start_date > end_date:
        return _error("start_date must not be after end_date", 400)

    query = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.is_deleted == False,
    )

    if category:
        query = query.filter(Transaction.category.ilike(f"%{category}%"))
    if start_date:
        query = query.filter(Transaction.transaction_date >= start_date)
    if end_date:
        query = query.filter(Transaction.transaction_date <= end_date)
    if transaction_type in ("debit", "credit"):
        query = query.filter(Transaction.transaction_type == TransactionType[transaction_type])

    query = query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    pagination = query.paginate(page=page, per_page=page_size, error_out=False)

    return jsonify({
        "transactions": [t.to_dict() for t in pagination.items],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": pagination.total,
            "pages": pagination.pages,
            "has_next": pagination.has_next,
            "has_prev": pagination.has_prev,
        },
    }), 200


@transactions_bp.post("/")
@require_tier(*WRITE_TIERS)
def create_transaction():
    user_id = _get_current_user_id()
    data = request.get_json(silent=True) or {}

    amount = data.get("amount")
    transaction_date_raw = data.get("transaction_date")

    if amount is None:
        return _error("amount is required", 400)
    try:
        # Money is stored as Numeric; parse as Decimal like the rest of the
        # codebase. is_finite() rejects NaN/Inf, which slip past a plain > 0
        # check (nan <= 0 and inf <= 0 are both False).
        amount = Decimal(str(amount))
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        return _error("amount must be a positive number", 400)

    if not transaction_date_raw:
        return _error("transaction_date is required (YYYY-MM-DD)", 400)
    transaction_date = _parse_date(transaction_date_raw)
    if not transaction_date:
        return _error("transaction_date must be in YYYY-MM-DD format", 400)

    txn_type_raw = data.get("transaction_type", "debit")
    if txn_type_raw not in ("debit", "credit"):
        return _error("transaction_type must be 'debit' or 'credit'", 400)

    txn = Transaction(
        user_id=user_id,
        amount=amount,
        currency=(data.get("currency") or "USD").upper()[:3],
        transaction_type=TransactionType[txn_type_raw],
        merchant=(data.get("merchant") or "").strip() or None,
        category=(data.get("category") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
        transaction_date=transaction_date,
        source=TransactionSource.manual,
    )

    explicit_tag = data.get("tag_id")
    txn.tag_id = explicit_tag if explicit_tag is not None else apply_rules(user_id, txn)

    db.session.add(txn)
    # Flush to assign txn.id so the event can reference it, then stage the event
    # in the same transaction as the row it describes.
    db.session.flush()

    if txn.tag_id is not None:
        enqueue(
            TRANSACTION_TAGGED,
            {
                "user_id": user_id,
                "transaction_id": txn.id,
                "tag_id": txn.tag_id,
            },
            key=str(user_id),
        )

    db.session.commit()

    return jsonify({"transaction": txn.to_dict()}), 201


@transactions_bp.get("/<int:transaction_id>")
@require_tier(*ALL_TIERS)
def get_transaction(transaction_id: int):
    user_id = _get_current_user_id()
    txn = Transaction.query.filter_by(
        id=transaction_id, user_id=user_id, is_deleted=False
    ).first()

    if not txn:
        return _error("transaction not found", 404)

    return jsonify({"transaction": txn.to_dict()}), 200


@transactions_bp.put("/<int:transaction_id>")
@require_tier(*WRITE_TIERS)
def update_transaction(transaction_id: int):
    user_id = _get_current_user_id()
    txn = Transaction.query.filter_by(
        id=transaction_id, user_id=user_id, is_deleted=False
    ).first()

    if not txn:
        return _error("transaction not found", 404)

    if txn.source == TransactionSource.plaid:
        return _error("plaid-imported transactions cannot be manually edited", 422)

    data = request.get_json(silent=True) or {}

    for field in ("merchant", "category", "notes"):
        if field in data:
            value = (data[field] or "").strip()
            setattr(txn, field, value or None)

    if "currency" in data:
        currency = (data["currency"] or "").strip().upper()[:3]
        if not currency:
            return _error("currency cannot be empty", 400)
        txn.currency = currency

    if "amount" in data:
        try:
            # Parse as Decimal and reject non-finite values, matching
            # create_transaction; is_finite() screens out NaN/Inf, which pass
            # a plain > 0 check (nan <= 0 and inf <= 0 are both False).
            amount = Decimal(str(data["amount"]))
            if not amount.is_finite() or amount <= 0:
                raise InvalidOperation
            txn.amount = amount
        except (InvalidOperation, TypeError, ValueError):
            return _error("amount must be a positive number", 400)

    if "transaction_date" in data:
        parsed = _parse_date(data["transaction_date"])
        if not parsed:
            return _error("transaction_date must be in YYYY-MM-DD format", 400)
        txn.transaction_date = parsed

    if "transaction_type" in data:
        if data["transaction_type"] not in ("debit", "credit"):
            return _error("transaction_type must be 'debit' or 'credit'", 400)
        txn.transaction_type = TransactionType[data["transaction_type"]]

    db.session.commit()
    return jsonify({"transaction": txn.to_dict()}), 200


@transactions_bp.delete("/<int:transaction_id>")
@require_tier(*WRITE_TIERS)
def delete_transaction(transaction_id: int):
    user_id = _get_current_user_id()
    txn = Transaction.query.filter_by(
        id=transaction_id, user_id=user_id, is_deleted=False
    ).first()

    if not txn:
        return _error("transaction not found", 404)

    if txn.source == TransactionSource.plaid:
        return _error("plaid-imported transactions cannot be deleted", 422)

    txn.is_deleted = True
    db.session.commit()

    return jsonify({"message": "transaction deleted"}), 200
