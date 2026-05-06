from flask import jsonify
from flask_jwt_extended import jwt_required
from . import transactions_bp


@transactions_bp.get("/")
@jwt_required()
def list_transactions():
    # TODO: return paginated transactions for the current user
    return jsonify({"transactions": [], "message": "not yet implemented"}), 200


@transactions_bp.post("/")
@jwt_required()
def create_transaction():
    # TODO: create a manual transaction entry
    return jsonify({"message": "not yet implemented"}), 501


@transactions_bp.get("/<int:transaction_id>")
@jwt_required()
def get_transaction(transaction_id: int):
    # TODO: return a single transaction by id
    return jsonify({"message": "not yet implemented"}), 501


@transactions_bp.put("/<int:transaction_id>")
@jwt_required()
def update_transaction(transaction_id: int):
    # TODO: update transaction fields (category, notes, etc.)
    return jsonify({"message": "not yet implemented"}), 501


@transactions_bp.delete("/<int:transaction_id>")
@jwt_required()
def delete_transaction(transaction_id: int):
    # TODO: soft-delete a transaction
    return jsonify({"message": "not yet implemented"}), 501
