"""
Module — Upcoming Dues & Bill Alerts
Detects recurring bills from transaction history and lets users
manually add dues (loan EMIs, fees, subscriptions, etc.)
Categories: Electricity, Water, Gas, Internet, Mobile, Rent,
            Loan EMI, Education Fee, Insurance, Credit Card,
            Subscription, Other
"""

from flask import Blueprint, g, jsonify, request
from auth import token_required
from database import get_conn
from collections import defaultdict
from datetime import datetime, timedelta, date

dues_bp = Blueprint("dues", __name__)

# ── Keywords for auto-detection from transactions ─────────────────────

DUE_PATTERNS = {
    "Electricity": ["electricity","electric","power","current bill","bescom","msedcl","tnebl","kseb","torrent power"],
    "Water":       ["water bill","water board","bwssb","cmwssb","jal board"],
    "Gas":         ["gas bill","piped gas","indane","hp gas","bharat gas","mahanagar gas","igl"],
    "Internet":    ["broadband","internet","fiber","act fibernet","hathway","airtel fiber","jio fiber"],
    "Mobile":      ["airtel","jio","bsnl","vi ","vodafone","mobile bill","recharge","postpaid"],
    "Loan EMI":    ["loan emi","emi","home loan","car loan","personal loan","hdfc loan","sbi loan","icici loan","bajaj finance","lic loan"],
    "Insurance":   ["insurance","lic","max life","hdfc life","term plan","health insurance","mediclaim","star health","policy premium"],
    "Rent":        ["rent","landlord","lease","pg payment","house rent"],
    "Education":   ["school fee","college fee","tuition","coaching","education fee","hostel fee","admission fee","semester fee"],
    "Credit Card": ["credit card","cc bill","card bill","amex","citibank card","axis card","hdfc card","sbi card"],
    "Subscription":["netflix","spotify","prime","hotstar","youtube premium","apple music","zee5","adobe","notion","github"],
}

def _ensure_dues_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS dues (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email   TEXT NOT NULL,
        name         TEXT NOT NULL,
        category     TEXT NOT NULL DEFAULT 'Other',
        amount       REAL NOT NULL,
        due_day      INTEGER NOT NULL,
        frequency    TEXT NOT NULL DEFAULT 'monthly',
        is_paid      INTEGER NOT NULL DEFAULT 0,
        paid_month   TEXT,
        notes        TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    conn.close()


def _auto_detect_dues(user_email):
    """
    Scan last 90 days of transactions and detect recurring bills.
    Returns list of detected due objects (not saved — just for suggestion).
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT merchant, amount, date, category FROM transactions WHERE user_email=?",
        (user_email,)
    ).fetchall()
    conn.close()

    txns = [dict(r) for r in rows]
    today = date.today()
    cutoff = (today - timedelta(days=90)).strftime("%Y-%m-%d")

    # Group transactions by merchant in last 90 days
    merchant_by_month = defaultdict(lambda: defaultdict(float))
    for t in txns:
        if t["date"] < cutoff or t["category"] == "Income":
            continue
        month = t["date"][:7]
        merchant_by_month[t["merchant"]][month] += abs(t["amount"])

    detected = []
    seen_categories = set()

    for merchant, monthly in merchant_by_month.items():
        if len(monthly) < 2:          # need at least 2 months to call it recurring
            continue
        amounts = list(monthly.values())
        avg_amount = sum(amounts) / len(amounts)
        variance = max(amounts) - min(amounts)
        if variance > avg_amount * 0.3:  # too inconsistent
            continue

        # Match to a category
        m_lower = merchant.lower()
        matched_cat = None
        for cat, keywords in DUE_PATTERNS.items():
            if any(k in m_lower for k in keywords):
                matched_cat = cat
                break
        if not matched_cat:
            continue
        if matched_cat in seen_categories:
            continue
        seen_categories.add(matched_cat)

        # Find typical due day from most recent payment
        recent = sorted([t for t in txns if t["merchant"] == merchant], key=lambda x: x["date"], reverse=True)
        due_day = 1
        if recent:
            try:
                due_day = datetime.strptime(recent[0]["date"], "%Y-%m-%d").day
            except Exception:
                due_day = 1

        detected.append({
            "name": merchant,
            "category": matched_cat,
            "amount": round(avg_amount, 0),
            "due_day": due_day,
            "frequency": "monthly",
            "auto_detected": True,
        })

    return detected


def _get_dues_with_status(user_email):
    _ensure_dues_table()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM dues WHERE user_email=? ORDER BY due_day ASC",
        (user_email,)
    ).fetchall()
    conn.close()

    today = date.today()
    this_month = today.strftime("%Y-%m")
    dues = []

    for r in rows:
        d = dict(r)
        due_day = d["due_day"]

        # Build due date for this month
        try:
            due_date = date(today.year, today.month, min(due_day, 28))
        except Exception:
            due_date = date(today.year, today.month, 1)

        days_until = (due_date - today).days

        # Determine status
        is_paid_this_month = (d["is_paid"] == 1 and d.get("paid_month") == this_month)

        if is_paid_this_month:
            status = "paid"
            status_label = "Paid ✓"
        elif days_until < 0:
            status = "overdue"
            status_label = f"Overdue by {abs(days_until)}d"
        elif days_until == 0:
            status = "due_today"
            status_label = "Due Today!"
        elif days_until <= 3:
            status = "urgent"
            status_label = f"Due in {days_until}d"
        elif days_until <= 7:
            status = "upcoming"
            status_label = f"Due in {days_until}d"
        else:
            status = "later"
            status_label = f"Due {due_date.strftime('%d %b')}"

        d["due_date"] = due_date.strftime("%Y-%m-%d")
        d["days_until"] = days_until
        d["status"] = status
        d["status_label"] = status_label
        d["is_paid_this_month"] = is_paid_this_month
        dues.append(d)

    # Sort: overdue → due_today → urgent → upcoming → later → paid
    ORDER = {"overdue": 0, "due_today": 1, "urgent": 2, "upcoming": 3, "later": 4, "paid": 5}
    dues.sort(key=lambda d: ORDER.get(d["status"], 4))
    return dues


# ── Endpoints ─────────────────────────────────────────────────────────

@dues_bp.route("/dues", methods=["GET"])
@token_required
def get_dues():
    dues = _get_dues_with_status(g.user_email)
    # Summary stats
    today = date.today()
    this_month = today.strftime("%Y-%m")
    total_monthly = sum(d["amount"] for d in dues)
    overdue = [d for d in dues if d["status"] == "overdue"]
    urgent  = [d for d in dues if d["status"] in ("due_today", "urgent")]
    paid    = [d for d in dues if d["is_paid_this_month"]]
    unpaid_amount = sum(d["amount"] for d in dues if not d["is_paid_this_month"])

    return jsonify({
        "dues": dues,
        "summary": {
            "total_monthly": round(total_monthly, 0),
            "unpaid_amount": round(unpaid_amount, 0),
            "overdue_count": len(overdue),
            "urgent_count": len(urgent),
            "paid_count": len(paid),
            "total_count": len(dues),
        },
        "auto_detected": _auto_detect_dues(g.user_email),
    })


@dues_bp.route("/dues", methods=["POST"])
@token_required
def add_due():
    _ensure_dues_table()
    data = request.json or {}
    name     = data.get("name", "").strip()
    category = data.get("category", "Other")
    amount   = float(data.get("amount", 0))
    due_day  = int(data.get("due_day", 1))
    freq     = data.get("frequency", "monthly")
    notes    = data.get("notes", "")

    if not name or amount <= 0:
        return jsonify({"error": "Name and amount required", "success": False}), 400
    if not 1 <= due_day <= 31:
        return jsonify({"error": "due_day must be 1–31", "success": False}), 400

    conn = get_conn()
    conn.execute(
        "INSERT INTO dues(user_email,name,category,amount,due_day,frequency,notes) VALUES(?,?,?,?,?,?,?)",
        (g.user_email, name, category, amount, due_day, freq, notes)
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "Due added", "success": True})


@dues_bp.route("/dues/<int:due_id>", methods=["PUT"])
@token_required
def update_due(due_id):
    _ensure_dues_table()
    data = request.json or {}
    conn = get_conn()
    row = conn.execute("SELECT id FROM dues WHERE id=? AND user_email=?", (due_id, g.user_email)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found", "success": False}), 404

    fields = []
    vals   = []
    for col in ["name", "category", "notes", "frequency"]:
        if col in data:
            fields.append(f"{col}=?")
            vals.append(data[col])
    for col in ["amount", "due_day"]:
        if col in data:
            fields.append(f"{col}=?")
            vals.append(float(data[col]) if col == "amount" else int(data[col]))

    if fields:
        vals.append(due_id)
        conn.execute(f"UPDATE dues SET {','.join(fields)} WHERE id=?", vals)
        conn.commit()
    conn.close()
    return jsonify({"success": True})


@dues_bp.route("/dues/<int:due_id>/mark_paid", methods=["POST"])
@token_required
def mark_paid(due_id):
    _ensure_dues_table()
    this_month = date.today().strftime("%Y-%m")
    conn = get_conn()
    row = conn.execute("SELECT * FROM dues WHERE id=? AND user_email=?", (due_id, g.user_email)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found", "success": False}), 404

    conn.execute(
        "UPDATE dues SET is_paid=1, paid_month=? WHERE id=?",
        (this_month, due_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Marked as paid"})


@dues_bp.route("/dues/<int:due_id>/mark_unpaid", methods=["POST"])
@token_required
def mark_unpaid(due_id):
    _ensure_dues_table()
    conn = get_conn()
    conn.execute("UPDATE dues SET is_paid=0, paid_month=NULL WHERE id=? AND user_email=?", (due_id, g.user_email))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@dues_bp.route("/dues/<int:due_id>", methods=["DELETE"])
@token_required
def delete_due(due_id):
    _ensure_dues_table()
    conn = get_conn()
    conn.execute("DELETE FROM dues WHERE id=? AND user_email=?", (due_id, g.user_email))
    conn.commit()
    conn.close()
    return jsonify({"success": True})
