"""
Module 3 — Transaction Preprocessing & Categorization
Module 4 — Subscription Auditor (detects by pattern AND by name)
Module 5 — Cash Flow & Spending Pattern Analysis
"""
from flask import Blueprint, request, jsonify, g
from database import get_conn
from auth import token_required
from collections import defaultdict
from datetime import datetime, timedelta

txn_bp = Blueprint("transactions", __name__)

# ---------- CATEGORIZATION ----------

CATEGORY_RULES = {
    "Income":        ["salary", "freelance", "bonus", "gusto", "payroll", "dividend", "refund", "cashback", "credit"],
    "Subscription":  ["netflix", "spotify", "prime", "hotstar", "youtube premium", "apple music",
                      "zee5", "jiocinema", "crunchyroll", "adobe", "notion", "slack", "github",
                      "disney", "hulu", "dropbox", "zoom", "microsoft 365", "google one", "icloud",
                      "playstation", "xbox", "nintendo", "audible"],
    "Food":          ["swiggy", "zomato", "restaurant", "starbucks", "kfc", "mcdonald", "domino",
                      "pizza", "burger", "cafe", "biryani", "eat", "food", "kitchen", "hotel",
                      "barbeque", "subway", "dunkin"],
    "Transport":     ["uber", "ola", "taxi", "metro", "rapido", "bus", "auto", "cab", "lyft", "petrol", "fuel"],
    "Travel":        ["airlines", "delta", "indigo", "spicejet", "air india", "makemytrip",
                      "cleartrip", "goibibo", "booking.com", "airbnb"],
    "Shopping":      ["amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa", "snapdeal",
                      "reliance", "big bazaar", "dmart", "ikea"],
    "Utilities":     ["electricity", "water", "gas", "internet", "jio", "airtel", "bsnl",
                      "vi ", "vodafone", "phone", "mobile", "broadband", "current bill", "power"],
    "Health":        ["pharmacy", "hospital", "clinic", "doctor", "medicine", "medplus",
                      "apollo", "1mg", "health", "gym", "fitness"],
    "Education":     ["udemy", "coursera", "college", "school", "fees", "book", "course", "coaching"],
    "Entertainment": ["bookmyshow", "pvr", "inox", "cinema", "movie", "concert", "game"],
    "Rent":          ["rent", "landlord", "lease", "pg payment", "hostel fee"],
    "Savings":       ["savings transfer", "goal deposit", "goal —", "savings", "piggybank", "rd installment", "sip", "mutual fund"],
}

# Subscriptions detected by name even with single transaction
KNOWN_SUBSCRIPTIONS = {
    "netflix": ("Netflix", 649),
    "spotify": ("Spotify", 119),
    "amazon prime": ("Amazon Prime", 179),
    "hotstar": ("Disney+ Hotstar", 299),
    "youtube premium": ("YouTube Premium", 189),
    "zee5": ("ZEE5", 99),
    "jiocinema": ("JioCinema", 29),
    "apple music": ("Apple Music", 99),
    "adobe": ("Adobe Creative", 1675),
    "github": ("GitHub Pro", 100),
    "notion": ("Notion Pro", 330),
    "dropbox": ("Dropbox", 800),
    "zoom": ("Zoom", 1300),
    "crunchyroll": ("Crunchyroll", 178),
    "disney": ("Disney+", 299),
}


def categorize(merchant: str) -> str:
    m = merchant.lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(k in m for k in keywords):
            return category
    return "Other"


# ---------- DB HELPERS ----------

def insert_txn(user_email, merchant, amount, date, category=None, plaid_id=None):
    # FIX: use INSERT OR IGNORE only when plaid_id present; plain INSERT for manual entries
    cat = category or categorize(merchant)
    conn = get_conn()
    if plaid_id:
        conn.execute(
            "INSERT OR IGNORE INTO transactions(user_email,plaid_id,merchant,amount,date,category) VALUES(?,?,?,?,?,?)",
            (user_email, plaid_id, merchant, float(amount), date, cat)
        )
    else:
        conn.execute(
            "INSERT INTO transactions(user_email,merchant,amount,date,category) VALUES(?,?,?,?,?)",
            (user_email, merchant, float(amount), date, cat)
        )
    conn.commit()
    conn.close()
    return cat


def load_txns(user_email):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id,merchant,amount,date,category FROM transactions WHERE user_email=? ORDER BY date DESC",
        (user_email,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- ENDPOINTS ----------

@txn_bp.route("/add_transaction", methods=["POST"])
@token_required
def add_transaction():
    data     = request.json or {}
    merchant = data.get("merchant", "Unknown").strip()
    amount   = float(data.get("amount", 0))
    date     = data.get("date") or datetime.now().strftime("%Y-%m-%d")
    category = categorize(merchant)
    insert_txn(g.user_email, merchant, amount, date, category)
    return jsonify({"message": "Transaction added", "success": True, "category": category})


@txn_bp.route("/get_transactions", methods=["GET"])
@txn_bp.route("/transactions", methods=["GET"])
@token_required
def get_transactions():
    return jsonify(load_txns(g.user_email))


@txn_bp.route("/delete_transaction/<int:txn_id>", methods=["DELETE"])
@token_required
def delete_transaction(txn_id):
    conn = get_conn()
    conn.execute("DELETE FROM transactions WHERE id=? AND user_email=?", (txn_id, g.user_email))
    conn.commit()
    conn.close()
    return jsonify({"message": "Deleted", "success": True})


# ---------- MODULE 5: CASH FLOW ----------

@txn_bp.route("/cashflow", methods=["GET"])
@token_required
def cashflow():
    txns          = load_txns(g.user_email)
    total_income  = sum(t["amount"] for t in txns if t["category"] == "Income")
    total_expense = sum(abs(t["amount"]) for t in txns if t["category"] != "Income")
    net           = total_income - total_expense
    breakdown     = defaultdict(float)
    for t in txns:
        if t["category"] != "Income":
            breakdown[t["category"]] += abs(t["amount"])
    return jsonify({
        "total_income":       round(total_income, 2),
        "total_expense":      round(total_expense, 2),
        "net_cashflow":       round(net, 2),
        "category_breakdown": {k: round(v, 2) for k, v in sorted(breakdown.items(), key=lambda x: -x[1])}
    })


@txn_bp.route("/monthly_summary", methods=["GET"])
@token_required
def monthly_summary():
    txns    = load_txns(g.user_email)
    summary = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for t in txns:
        try:
            month = t["date"][:7]
        except Exception:
            continue
        if t["category"] == "Income":
            summary[month]["income"] += t["amount"]
        else:
            summary[month]["expense"] += abs(t["amount"])
    return jsonify({
        m: {"income": round(v["income"], 2), "expense": round(v["expense"], 2)}
        for m, v in sorted(summary.items())
    })


# ---------- MODULE 4: SUBSCRIPTION AUDITOR ----------

def _detect_subs(txns):
    """
    Detects subscriptions two ways:
    1. Pattern-based: same merchant, same amount, 25-40 days apart (2+ times)
    2. Name-based: known subscription service found even once
    """
    today    = datetime.now().date()
    detected = {}   # key = merchant name → sub dict

    # ── Method 1: Pattern detection (recurring transactions) ──────────
    merchant_data = defaultdict(list)
    for t in txns:
        try:
            dt = datetime.strptime(t["date"], "%Y-%m-%d")
        except Exception:
            continue
        merchant_data[t["merchant"]].append((t["amount"], dt))

    for merchant, records in merchant_data.items():
        unique  = {}
        for amt, dt in records:
            unique[dt] = amt
        records = sorted([(amt, dt) for dt, amt in unique.items()], key=lambda x: x[1])
        if len(records) < 2:
            continue
        amounts = [r[0] for r in records]
        if len(set(amounts)) != 1:
            continue
        gaps = [(records[i][1] - records[i-1][1]).days for i in range(1, len(records))]
        if all(25 <= gap <= 40 for gap in gaps):
            avg_gap  = sum(gaps) / len(gaps)
            last_dt  = records[-1][1].date()
            next_dt  = last_dt + timedelta(days=round(avg_gap))
            days_left = (next_dt - today).days
            detected[merchant] = {
                "merchant":              merchant,
                "amount":                abs(amounts[0]),
                "frequency":             "Monthly Recurring",
                "last_payment":          last_dt.strftime("%Y-%m-%d"),
                "next_expected_payment": next_dt.strftime("%Y-%m-%d"),
                "days_until_next":       days_left,
                "times":                 len(records),
                "total_spent":           round(sum(abs(a) for a in amounts), 2),
                "detected_by":           "pattern"
            }

    # ── Method 2: Name-based detection (known services) ──────────────
    for t in txns:
        m_lower = t["merchant"].lower()
        for keyword, (display_name, typical_price) in KNOWN_SUBSCRIPTIONS.items():
            if keyword in m_lower and display_name not in detected:
                # Find most recent transaction for this service
                same = [x for x in txns if keyword in x["merchant"].lower()]
                same_sorted = sorted(same, key=lambda x: x["date"], reverse=True)
                last = same_sorted[0]
                try:
                    last_dt  = datetime.strptime(last["date"], "%Y-%m-%d").date()
                    next_dt  = last_dt + timedelta(days=30)
                    days_left = (next_dt - today).days
                    detected[display_name] = {
                        "merchant":              display_name,
                        "amount":                abs(float(last["amount"])),
                        "frequency":             "Monthly Subscription",
                        "last_payment":          last_dt.strftime("%Y-%m-%d"),
                        "next_expected_payment": next_dt.strftime("%Y-%m-%d"),
                        "days_until_next":       days_left,
                        "times":                 len(same),
                        "total_spent":           round(sum(abs(float(x["amount"])) for x in same), 2),
                        "detected_by":           "name"
                    }
                except Exception:
                    pass
                break

    return list(detected.values())


@txn_bp.route("/detect_subscriptions", methods=["GET"])
@token_required
def detect_subscriptions():
    return jsonify(_detect_subs(load_txns(g.user_email)))


@txn_bp.route("/upcoming_subscription_total", methods=["GET"])
@token_required
def upcoming_subscription_total():
    subs  = _detect_subs(load_txns(g.user_email))
    total = sum(s["amount"] for s in subs)
    return jsonify({"next_month_subscription_total": round(total, 2), "count": len(subs)})


# ─────────────────────────────────────────────
# MODULE 7: BUDGET LIMITS
# ─────────────────────────────────────────────

DEFAULT_BUDGETS = {
    "Food": 3000, "Shopping": 5000, "Subscription": 500, "Transport": 2000,
    "Entertainment": 1000, "Utilities": 2000, "Health": 2000, "Education": 3000,
    "Travel": 5000, "Rent": 15000, "Other": 2000,
}

def _ensure_budgets_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS budgets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL, category TEXT NOT NULL, limit_amount REAL NOT NULL,
        UNIQUE(user_email, category))""")
    conn.commit(); conn.close()

@txn_bp.route("/budgets", methods=["GET"])
@token_required
def get_budgets():
    _ensure_budgets_table()
    conn = get_conn()
    rows = conn.execute("SELECT category, limit_amount FROM budgets WHERE user_email=?", (g.user_email,)).fetchall()
    conn.close()
    saved = {r["category"]: r["limit_amount"] for r in rows}
    return jsonify({cat: saved.get(cat, default) for cat, default in DEFAULT_BUDGETS.items()})

@txn_bp.route("/budgets", methods=["POST"])
@token_required
def save_budgets():
    _ensure_budgets_table()
    data = request.json or {}
    conn = get_conn()
    for category, limit in data.items():
        conn.execute(
            "INSERT INTO budgets(user_email,category,limit_amount) VALUES(?,?,?) "
            "ON CONFLICT(user_email,category) DO UPDATE SET limit_amount=excluded.limit_amount",
            (g.user_email, category, float(limit)))
    conn.commit(); conn.close()
    return jsonify({"success": True})

@txn_bp.route("/budget_status", methods=["GET"])
@token_required
def budget_status():
    _ensure_budgets_table()
    current_month = datetime.now().strftime("%Y-%m")
    txns = load_txns(g.user_email)
    spent = defaultdict(float)
    for t in txns:
        if t["category"] != "Income" and t["date"].startswith(current_month):
            spent[t["category"]] += abs(t["amount"])
    conn = get_conn()
    rows = conn.execute("SELECT category, limit_amount FROM budgets WHERE user_email=?", (g.user_email,)).fetchall()
    conn.close()
    saved = {r["category"]: r["limit_amount"] for r in rows}
    result = {}
    for cat, default in DEFAULT_BUDGETS.items():
        limit = saved.get(cat, default)
        s = round(spent.get(cat, 0), 2)
        result[cat] = {"spent": s, "limit": limit, "pct": round((s/limit*100) if limit > 0 else 0, 1), "exceeded": s > limit}
    return jsonify(result)


# ─────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────
import csv, io
from flask import Response as FlaskResponse

@txn_bp.route("/export/csv", methods=["GET"])
@token_required
def export_csv():
    txns = load_txns(g.user_email)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Date", "Merchant", "Category", "Amount (INR)", "Type"])
    for t in txns:
        writer.writerow([t["id"], t["date"], t["merchant"], t["category"], abs(t["amount"]), "Income" if t["category"]=="Income" else "Expense"])
    output.seek(0)
    return FlaskResponse(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=finvault_transactions.csv"})
