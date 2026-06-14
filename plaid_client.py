"""
Module 2 — Plaid Bank Connection (Sandbox ready)
================================================
HOW TO CONNECT A REAL BANK (Free Sandbox — no real money):

1. Sign up at https://dashboard.plaid.com (free)
2. Go to Team Settings → Keys
3. Copy your "client_id" and "sandbox" secret
4. Create backend/.env with:
       PLAID_CLIENT_ID=your_client_id_here
       PLAID_SECRET=your_sandbox_secret_here
       PLAID_ENV=sandbox

5. In Sandbox mode, use test credentials in the Plaid Link popup:
       Username: user_good
       Password: pass_good
       (These are Plaid's official test credentials — no real bank needed)

6. Click "Connect Bank" on the Dashboard page

NOTE: Plaid Sandbox only supports US banks.
      For Indian banks, use manual transaction entry or Sample Data.

ENVIRONMENT VARIABLES (set in backend/.env):
    PLAID_CLIENT_ID   — from dashboard.plaid.com
    PLAID_SECRET      — sandbox/development/production secret
    PLAID_ENV         — sandbox | development | production (default: sandbox)
"""

import os

PLAID_CLIENT_ID = os.environ.get("PLAID_CLIENT_ID", "")
PLAID_SECRET    = os.environ.get("PLAID_SECRET", "")
PLAID_ENV       = os.environ.get("PLAID_ENV", "sandbox")
PLAID_BASE_URL  = f"https://{PLAID_ENV}.plaid.com"
PLAID_ENABLED   = bool(PLAID_CLIENT_ID and PLAID_SECRET)
