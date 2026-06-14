"""
Module 6 — Predictive Balance Forecasting (14-day)
"""
from flask import Blueprint, g, jsonify
from database import get_conn
from auth import token_required
from collections import defaultdict
from datetime import datetime, timedelta

forecast_bp = Blueprint("forecast", __name__)


@forecast_bp.route("/balance_forecast", methods=["GET"])
@token_required
def balance_forecast():
    conn = get_conn()
    rows = conn.execute(
        "SELECT amount, category, date FROM transactions WHERE user_email=?",
        (g.user_email,)
    ).fetchall()
    conn.close()

    balance = 0.0
    expense_total = 0.0
    expense_count = 0
    subscription_total = 0.0
    daily_expenses = defaultdict(float)

    for row in rows:
        amount = float(row["amount"])
        category = row["category"]
        date_str = row["date"]

        if category == "Income":
            balance += amount
        else:
            balance -= abs(amount)
            expense_total += abs(amount)
            expense_count += 1
            daily_expenses[date_str] += abs(amount)

        if category == "Subscription":
            subscription_total += abs(amount)

    # Daily average from last 30 days
    today = datetime.now().date()
    last_30 = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
    recent_expenses = [daily_expenses.get(d, 0) for d in last_30 if daily_expenses.get(d, 0) > 0]
    daily_avg = sum(recent_expenses) / len(recent_expenses) if recent_expenses else (
        expense_total / expense_count if expense_count else 0
    )

    daily_sub_drain = subscription_total / 30

    forecast = []
    future_balance = balance
    for i in range(14):
        future_balance -= daily_avg
        future_balance -= daily_sub_drain
        forecast.append({
            "day": i + 1,
            "date": (today + timedelta(days=i + 1)).strftime("%Y-%m-%d"),
            "predicted_balance": round(future_balance, 2)
        })

    # Warnings
    warnings = []
    for f in forecast:
        if f["predicted_balance"] < 0:
            warnings.append(f"⚠️ Negative balance predicted on Day {f['day']} ({f['date']})")
            break
        elif f["predicted_balance"] < 1000:
            warnings.append(f"⚠️ Balance drops below ₹1,000 around Day {f['day']} ({f['date']})")
            break

    return jsonify({
        "current_balance": round(balance, 2),
        "daily_avg_expense": round(daily_avg, 2),
        "forecast": forecast,
        "warnings": warnings
    })
