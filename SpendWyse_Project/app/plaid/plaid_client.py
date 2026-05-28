from functools import lru_cache

import plaid
from flask import current_app
from plaid.api import plaid_api


_ENV_HOSTS = {
    "sandbox": plaid.Environment.Sandbox,
    "development": plaid.Environment.Development,
    "production": plaid.Environment.Production,
}


@lru_cache(maxsize=1)
def get_plaid_client() -> plaid_api.PlaidApi:
    env = (current_app.config.get("PLAID_ENV") or "sandbox").lower()
    host = _ENV_HOSTS.get(env, plaid.Environment.Sandbox)

    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": current_app.config["PLAID_CLIENT_ID"],
            "secret": current_app.config["PLAID_SECRET"],
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))
