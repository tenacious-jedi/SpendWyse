from flask import jsonify
from flask_jwt_extended import jwt_required
from . import plaid_bp


@plaid_bp.post("/link/token")
@jwt_required()
def create_link_token():
    # TODO: call Plaid /link/token/create and return the link_token to the client
    # The client uses this token to open Plaid Link in the browser
    return jsonify({"message": "not yet implemented"}), 501


@plaid_bp.post("/link/exchange")
@jwt_required()
def exchange_public_token():
    # TODO: exchange the public_token from Plaid Link for a permanent access_token
    # Store the access_token encrypted against the user record
    return jsonify({"message": "not yet implemented"}), 501


@plaid_bp.post("/sync")
@jwt_required()
def sync_transactions():
    # TODO: call Plaid /transactions/sync to pull new/modified/removed transactions
    # Upsert results into the transactions table
    return jsonify({"message": "not yet implemented"}), 501


@plaid_bp.get("/accounts")
@jwt_required()
def list_accounts():
    # TODO: call Plaid /accounts/get and return linked bank accounts
    return jsonify({"accounts": [], "message": "not yet implemented"}), 200
