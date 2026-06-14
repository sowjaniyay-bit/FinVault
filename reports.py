"""
Module 11 — Automated Reports & Alerts
Returns structured monthly/yearly report data
"""
from flask import Blueprint, g, jsonify, request
from auth import token_required
from database import get_conn
from collections import defaultdict
from datetime import datetime, timedelta

reports_bp = Blueprint("reports", __name__)


@reports_bp.route("/report/monthly", methods=["GET"])
@token_required
def monthly_report():
    month = request.args.get("month") or datetime.now().strftime("%Y-%m")

    conn = get_conn()
    rows = conn.execute(
        "SELECT merchant, amount, date, category FROM transactions WHERE user_email=? AND date LIKE ?",
        (g.user_email, f"{month}%")
    ).fetchall()
    conn.close()

    txns = [dict(r) for r in rows]

    income = sum(t["amount"] for t in txns if t["category"] == "Income")
    expense = sum(abs(t["amount"]) for t in txns if t["category"] != "Income")
    savings = income - expense

    cat_breakdown = defaultdict(float)
    for t in txns:
        if t["category"] != "Income":
            cat_breakdown[t["category"]] += abs(t["amount"])

    top_merchants = defaultdict(float)
    for t in txns:
        if t["category"] != "Income":
            top_merchants[t["merchant"]] += abs(t["amount"])

    top5 = sorted(top_merchants.items(), key=lambda x: -x[1])[:5]

    alerts = []
    if income > 0 and expense / income > 0.9:
        alerts.append("⚠️ Expenses exceeded 90% of income this month!")
    if cat_breakdown.get("Subscription", 0) > 2000:
        alerts.append("📺 Subscription spend is very high — review and cancel unused ones.")
    if savings < 0:
        alerts.append("🚨 You spent more than you earned this month!")

    return jsonify({
        "month": month,
        "total_transactions": len(txns),
        "total_income": round(income, 2),
        "total_expense": round(expense, 2),
        "net_savings": round(savings, 2),
        "savings_rate": round((savings / income * 100), 1) if income > 0 else 0,
        "category_breakdown": {k: round(v, 2) for k, v in sorted(cat_breakdown.items(), key=lambda x: -x[1])},
        "top_5_merchants": [{"merchant": m, "total": round(v, 2)} for m, v in top5],
        "alerts": alerts
    })


@reports_bp.route("/report/yearly", methods=["GET"])
@token_required
def yearly_report():
    year = request.args.get("year") or datetime.now().strftime("%Y")

    conn = get_conn()
    rows = conn.execute(
        "SELECT amount, category, date FROM transactions WHERE user_email=? AND date LIKE ?",
        (g.user_email, f"{year}%")
    ).fetchall()
    conn.close()

    monthly = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for r in rows:
        m = r["date"][:7]
        if r["category"] == "Income":
            monthly[m]["income"] += r["amount"]
        else:
            monthly[m]["expense"] += abs(r["amount"])

    total_income = sum(v["income"] for v in monthly.values())
    total_expense = sum(v["expense"] for v in monthly.values())

    return jsonify({
        "year": year,
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "net_savings": round(total_income - total_expense, 2),
        "monthly_breakdown": {
            m: {"income": round(v["income"], 2), "expense": round(v["expense"], 2),
                "savings": round(v["income"] - v["expense"], 2)}
            for m, v in sorted(monthly.items())
        }
    })
