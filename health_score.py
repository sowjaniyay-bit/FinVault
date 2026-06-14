"""
Module 8 — Financial Health Scoring System
Produces a 0-100 score with letter grade and breakdown.
"""
from flask import Blueprint, g, jsonify
from auth import token_required
from database import get_conn
from collections import defaultdict
from datetime import datetime

health_bp = Blueprint("health", __name__)


@health_bp.route("/health_score", methods=["GET"])
@token_required
def health_score():
    conn = get_conn()
    rows = conn.execute(
        "SELECT amount, category, date FROM transactions WHERE user_email=?",
        (g.user_email,)
    ).fetchall()
    conn.close()

    txns = [dict(r) for r in rows]
    if not txns:
        return jsonify({
            "score": 0,
            "grade": "N/A",
            "message": "Add transactions to calculate your financial health score.",
            "breakdown": {}
        })

    this_month = datetime.now().strftime("%Y-%m")

    monthly_income = defaultdict(float)
    monthly_expense = defaultdict(float)
    sub_spend = 0.0

    for t in txns:
        m = t["date"][:7]
        if t["category"] == "Income":
            monthly_income[m] += t["amount"]
        else:
            monthly_expense[m] += abs(t["amount"])
            if t["category"] == "Subscription":
                sub_spend += abs(t["amount"])

    months_with_income = [m for m in monthly_income if monthly_income[m] > 0]
    if not months_with_income:
        return jsonify({
            "score": 20,
            "grade": "F",
            "message": "No income recorded. Please add income transactions.",
            "breakdown": {}
        })

    # --- SCORING COMPONENTS (each out of allocated points) ---
    scores = {}

    # 1. Savings Rate (30 pts): income - expense / income
    total_income = sum(monthly_income.values())
    total_expense = sum(monthly_expense.values())
    savings = total_income - total_expense
    savings_rate = savings / total_income if total_income > 0 else 0

    if savings_rate >= 0.30:
        s1 = 30
    elif savings_rate >= 0.20:
        s1 = 24
    elif savings_rate >= 0.10:
        s1 = 16
    elif savings_rate >= 0:
        s1 = 8
    else:
        s1 = 0
    scores["Savings Rate"] = {"score": s1, "max": 30,
                              "detail": f"{round(savings_rate * 100, 1)}% savings rate"}

    # 2. Expense Consistency (20 pts): std dev of monthly expenses
    exp_vals = [monthly_expense[m] for m in monthly_expense]
    if len(exp_vals) >= 2:
        avg_exp = sum(exp_vals) / len(exp_vals)
        variance = sum((v - avg_exp) ** 2 for v in exp_vals) / len(exp_vals)
        std_dev = variance ** 0.5
        cv = std_dev / avg_exp if avg_exp > 0 else 1
        if cv < 0.15:
            s2 = 20
        elif cv < 0.30:
            s2 = 14
        elif cv < 0.50:
            s2 = 8
        else:
            s2 = 3
        scores["Expense Consistency"] = {"score": s2, "max": 20,
                                          "detail": f"Spending volatility: {round(cv * 100)}%"}
    else:
        s2 = 10  # partial credit for single month
        scores["Expense Consistency"] = {"score": s2, "max": 20, "detail": "Need more months of data"}

    # 3. Subscription Control (15 pts)
    sub_pct = sub_spend / total_income if total_income > 0 else 1
    if sub_pct < 0.05:
        s3 = 15
    elif sub_pct < 0.10:
        s3 = 10
    elif sub_pct < 0.20:
        s3 = 5
    else:
        s3 = 0
    scores["Subscription Control"] = {"score": s3, "max": 15,
                                       "detail": f"{round(sub_pct * 100, 1)}% of income on subscriptions"}

    # 4. Income Regularity (20 pts)
    inc_months = len([m for m in monthly_income if monthly_income[m] > 0])
    all_months_tracked = len(set(t["date"][:7] for t in txns))
    regularity = inc_months / all_months_tracked if all_months_tracked > 0 else 0
    if regularity >= 0.90:
        s4 = 20
    elif regularity >= 0.70:
        s4 = 14
    elif regularity >= 0.50:
        s4 = 8
    else:
        s4 = 3
    scores["Income Regularity"] = {"score": s4, "max": 20,
                                    "detail": f"Income in {inc_months}/{all_months_tracked} months"}

    # 5. Diversity of Spending (15 pts): more categories = better control
    categories_used = len(set(t["category"] for t in txns if t["category"] != "Income"))
    if categories_used >= 5:
        s5 = 15
    elif categories_used >= 3:
        s5 = 10
    else:
        s5 = 5
    scores["Spending Diversity"] = {"score": s5, "max": 15,
                                     "detail": f"{categories_used} spending categories tracked"}

    total_score = sum(v["score"] for v in scores.values())

    if total_score >= 85:
        grade, message = "A+", "Excellent financial health! You're a money master."
    elif total_score >= 75:
        grade, message = "A", "Great financial health. Keep up the good work!"
    elif total_score >= 65:
        grade, message = "B", "Good financial habits. A few tweaks can make you excellent."
    elif total_score >= 50:
        grade, message = "C", "Average financial health. Focus on savings and consistency."
    elif total_score >= 35:
        grade, message = "D", "Below average. Cut subscriptions and track spending closely."
    else:
        grade, message = "F", "Financial health needs urgent attention. Start budgeting today."

    return jsonify({
        "score": total_score,
        "grade": grade,
        "message": message,
        "breakdown": scores,
        "summary": {
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "total_savings": round(savings, 2),
            "savings_rate_pct": round(savings_rate * 100, 1)
        }
    })
