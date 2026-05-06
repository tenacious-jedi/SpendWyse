from flask import jsonify
from flask_jwt_extended import jwt_required
from . import budgets_bp


@budgets_bp.get("/")
@jwt_required()
def list_budgets():
    # TODO: return all budgets/categories for the current user
    return jsonify({"budgets": [], "message": "not yet implemented"}), 200


@budgets_bp.post("/")
@jwt_required()
def create_budget():
    # TODO: create a budget for a category with a monthly limit
    return jsonify({"message": "not yet implemented"}), 501


@budgets_bp.put("/<int:budget_id>")
@jwt_required()
def update_budget(budget_id: int):
    # TODO: update budget limit or category
    return jsonify({"message": "not yet implemented"}), 501


@budgets_bp.delete("/<int:budget_id>")
@jwt_required()
def delete_budget(budget_id: int):
    # TODO: remove a budget
    return jsonify({"message": "not yet implemented"}), 501
