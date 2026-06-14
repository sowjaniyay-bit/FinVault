"""
Module 12 — Goal-Based Savings Tracker
"""
from flask import Blueprint, request, g, jsonify
from auth import token_required
from database import get_conn
from datetime import datetime

goals_bp = Blueprint("goals", __name__)


@goals_bp.route("/goals", methods=["GET"])
@token_required
def get_goals():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,name,target_amount,saved_amount,deadline,created_at FROM goals WHERE user_email=? ORDER BY created_at DESC",
        (g.user_email,)
    ).fetchall()
    conn.close()

    goals = []
    for r in rows:
        d = dict(r)
        d["progress_pct"] = round((d["saved_amount"] / d["target_amount"]) * 100, 1) if d["target_amount"] > 0 else 0
        d["remaining"] = round(d["target_amount"] - d["saved_amount"], 2)

        # Days remaining
        if d["deadline"]:
            try:
                dl = datetime.strptime(d["deadline"], "%Y-%m-%d").date()
                days_left = (dl - datetime.now().date()).days
                d["days_left"] = days_left
                d["monthly_needed"] = round(d["remaining"] / max((days_left / 30), 1), 2) if days_left > 0 else 0
            except Exception:
                d["days_left"] = None
                d["monthly_needed"] = None
        else:
            d["days_left"] = None
            d["monthly_needed"] = None

        goals.append(d)
    return jsonify(goals)


@goals_bp.route("/goals", methods=["POST"])
@token_required
def create_goal():
    data = request.json or {}
    name = data.get("name", "").strip()
    target = float(data.get("target_amount", 0))
    deadline = data.get("deadline")

    if not name or target <= 0:
        return jsonify({"error": "Name and target amount required", "success": False}), 400

    conn = get_conn()
    conn.execute(
        "INSERT INTO goals(user_email,name,target_amount,deadline) VALUES(?,?,?,?)",
        (g.user_email, name, target, deadline)
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Goal created", "success": True})


@goals_bp.route("/goals/<int:goal_id>/deposit", methods=["POST"])
@token_required
def deposit_to_goal(goal_id):
    data = request.json or {}
    amount = float(data.get("amount", 0))
    if amount <= 0:
        return jsonify({"error": "Amount must be positive", "success": False}), 400

    conn = get_conn()
    row = conn.execute(
        "SELECT saved_amount, target_amount, name FROM goals WHERE id=? AND user_email=?",
        (goal_id, g.user_email)
    ).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Goal not found", "success": False}), 404

    new_saved = row["saved_amount"] + amount
    if new_saved > row["target_amount"]:
        new_saved = row["target_amount"]

    # Update goal progress
    conn.execute("UPDATE goals SET saved_amount=? WHERE id=?", (new_saved, goal_id))

    # Also log as a negative transaction (debit from balance) so it shows in Transactions
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO transactions(user_email, merchant, amount, date, category) VALUES(?,?,?,?,?)",
        (g.user_email, f"Goal Deposit — {row['name']}", -amount, today, "Savings")
    )

    conn.commit()
    conn.close()

    achieved = new_saved >= row["target_amount"]
    return jsonify({
        "message": "🎉 Goal achieved!" if achieved else "Deposit recorded",
        "success": True,
        "saved_amount": round(new_saved, 2),
        "achieved": achieved
    })


@goals_bp.route("/goals/<int:goal_id>", methods=["DELETE"])
@token_required
def delete_goal(goal_id):
    conn = get_conn()
    conn.execute("DELETE FROM goals WHERE id=? AND user_email=?", (goal_id, g.user_email))
    conn.commit()
    conn.close()
    return jsonify({"message": "Goal deleted", "success": True})
