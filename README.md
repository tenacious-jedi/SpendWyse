# SpendWyse
A personal finance app to manage personal finances and budgeting with filters for checking category spending with category tags [eg. tuition, food, travel etc.] Built as a Flask REST API application, it pulls user's bank transactions via Plaid, auto-categorizes them, tracks spending against per category spend rules, raises alerts when spend caps are approached or breached. Billing and plan tiers are run through Stripe. The application has also has deterministic agents set up as below.

Agents are set as:

Subscription Optimizer Agent - Finds hidden user subscriptions which are compounding over time (for eg. annual renewals, free trials that converted, services billed under weird merchant names, duplicate streaming through bundles which need investigation). It essentially investigates, problems like where is a user leaking money on his/her subscriptions?

Savings Spend Agent - Agent that investigates why the spend went up in a particular category tag that month. For eg. The spend on Uber Eats in the "Food" category tag went up by say $1000 dollars for last month. this agent investigates and prescribes a solution like say, At your historical dining frequency, dropping 4 of these Uber eats spends would bring you back to your baseline of $300/month.

## Status

Backend API is feature-complete: auth (incl. password reset), Plaid bank linking and transaction sync, user-defined tags and auto-tagging rules, spend caps with warn/alert thresholds, alert delivery via a Kafka event bus, Stripe-billed subscriptions, and reports. Frontend is ongoing. 

## Running locally

Requires Docker Desktop and Python 3.12.

```bash
# Bring up Postgres and Kafka
docker compose -f docker-compose.yml up -d

# Create the venv and install deps
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Generate a Fernet key for Plaid token encryption and add it to .env:
./venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Apply the DB schema
FLASK_APP=run.py ./venv/bin/flask db upgrade

# Run the API
./venv/bin/python run.py

# In a separate terminal, run the alert worker
./venv/bin/python worker.py
```
