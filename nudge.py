"""
Module 7 — Advanced AI Nudge Engine
Features:
  - Gemini AI-powered personalised nudges (primary, replaces hardcoded rules)
  - Hardcoded rules as fallback when Gemini unavailable
  - Anomaly detection (unusual spending spikes vs personal average)
  - Streak tracker (consecutive days under daily budget)
  - Goal progress nudges
  - Weekly digest card (Mondays)
  - Predicted end-of-month balance
  - Snooze / Dismiss nudges (persisted in DB)
"""

import os
import json as _json
import urllib.request
import urllib.error
from flask import Blueprint, g, jsonify, request
from auth import token_required
from database import get_conn
from collections import defaultdict
from datetime import datetime, timedelta, date

nudge_bp = Blueprint("nudge", __name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ── DB helpers ────────────────────────────────────────────────────────

def _ensure_nudge_state_table():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS nudge_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        nudge_key  TEXT NOT NULL,
        state      TEXT NOT NULL DEFAULT 'active',
        snoozed_until TEXT,
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_email, nudge_key)
    )""")
    conn.commit()
    conn.close()


def _get_nudge_states(user_email):
    _ensure_nudge_state_table()
    conn = get_conn()
    rows = conn.execute(
        "SELECT nudge_key, state, snoozed_until FROM nudge_state WHERE user_email=?",
        (user_email,)
    ).fetchall()
    conn.close()
    return {r["nudge_key"]: dict(r) for r in rows}


def _is_suppressed(nudge_key, states):
    s = states.get(nudge_key)
    if not s:
        return False
    if s["state"] == "dismissed":
        return True
    if s["state"] == "snoozed" and s.get("snoozed_until"):
        try:
            until = datetime.strptime(s["snoozed_until"], "%Y-%m-%d").date()
            if date.today() <= until:
                return True
        except Exception:
            pass
    return False


# ── Data loader ───────────────────────────────────────────────────────

def _load_data(user_email):
    conn = get_conn()
    txns = [dict(r) for r in conn.execute(
        "SELECT id, merchant, amount, date, category FROM transactions WHERE user_email=?",
        (user_email,)
    ).fetchall()]
    goals = [dict(r) for r in conn.execute(
        "SELECT id, name, target_amount, saved_amount, deadline FROM goals WHERE user_email=?",
        (user_email,)
    ).fetchall()]
    try:
        budgets = {r["category"]: r["limit_amount"] for r in conn.execute(
            "SELECT category, limit_amount FROM budgets WHERE user_email=?",
            (user_email,)
        ).fetchall()}
    except Exception:
        budgets = {}
    conn.close()
    return txns, goals, budgets


# ── Anomaly detection ─────────────────────────────────────────────────

def _detect_anomalies(txns):
    today      = date.today()
    week_ago   = today - timedelta(days=7)
    month_ago  = today - timedelta(days=37)

    week_spend  = defaultdict(float)
    month_spend = defaultdict(float)

    for t in txns:
        if t["category"] == "Income":
            continue
        try:
            dt = datetime.strptime(t["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        amt = abs(t["amount"])
        if dt >= week_ago:
            week_spend[t["category"]] += amt
        elif dt >= month_ago:
            month_spend[t["category"]] += amt

    anomalies = []
    for cat, w_amt in week_spend.items():
        m_amt = month_spend.get(cat, 0)
        if m_amt < 100:
            continue
        weekly_avg = m_amt / 4.3
        if w_amt > 2.0 * weekly_avg and w_amt > 300:
            anomalies.append({
                "category": cat,
                "this_week": round(w_amt, 0),
                "weekly_avg": round(weekly_avg, 0),
                "ratio": round(w_amt / weekly_avg, 1)
            })
    return anomalies


# ── Streak tracker ────────────────────────────────────────────────────

def _calc_streak(txns, budgets):
    DEFAULT_BUDGETS = {
        "Food": 3000, "Shopping": 5000, "Subscription": 500,
        "Transport": 2000, "Entertainment": 1000, "Utilities": 2000,
        "Health": 2000, "Education": 3000, "Travel": 5000, "Rent": 15000, "Other": 2000,
    }
    total_monthly = sum(budgets.get(c, d) for c, d in DEFAULT_BUDGETS.items())
    daily_limit = total_monthly / 30

    daily_spend = defaultdict(float)
    for t in txns:
        if t["category"] == "Income":
            continue
        try:
            daily_spend[t["date"]] += abs(t["amount"])
        except Exception:
            pass

    streak = 0
    check_date = date.today() - timedelta(days=1)
    for _ in range(60):
        ds = check_date.strftime("%Y-%m-%d")
        if daily_spend.get(ds, 0) <= daily_limit:
            streak += 1
        else:
            break
        check_date -= timedelta(days=1)

    return streak, round(daily_limit, 0)


# ── End-of-month prediction ───────────────────────────────────────────

def _predict_eom_balance(txns):
    today = date.today()
    this_month = today.strftime("%Y-%m")
    days_elapsed = today.day
    days_in_month = 30

    income_this_month  = 0.0
    expense_this_month = 0.0
    for t in txns:
        if not t["date"].startswith(this_month):
            continue
        if t["category"] == "Income":
            income_this_month += t["amount"]
        else:
            expense_this_month += abs(t["amount"])

    if days_elapsed == 0 or income_this_month == 0:
        return None

    daily_rate = expense_this_month / days_elapsed
    remaining_days = days_in_month - days_elapsed
    projected_balance = income_this_month - (expense_this_month + daily_rate * remaining_days)

    return {
        "income": round(income_this_month, 0),
        "expense_so_far": round(expense_this_month, 0),
        "projected_balance": round(projected_balance, 0),
        "days_elapsed": days_elapsed,
        "days_remaining": remaining_days,
        "daily_rate": round(daily_rate, 0),
    }


# ── Weekly digest ─────────────────────────────────────────────────────

def _build_weekly_digest(txns):
    today = date.today()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday = last_monday + timedelta(days=6)

    week_income = 0.0
    week_expense = 0.0
    week_by_cat = defaultdict(float)

    for t in txns:
        try:
            dt = datetime.strptime(t["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if last_monday <= dt <= last_sunday:
            if t["category"] == "Income":
                week_income += t["amount"]
            else:
                week_expense += abs(t["amount"])
                week_by_cat[t["category"]] += abs(t["amount"])

    if week_expense == 0 and week_income == 0:
        return None

    top_cat = max(week_by_cat, key=week_by_cat.get) if week_by_cat else "Other"
    saved = round(week_income - week_expense, 0) if week_income > 0 else None

    return {
        "week_start": last_monday.strftime("%d %b"),
        "week_end":   last_sunday.strftime("%d %b"),
        "income":     round(week_income, 0),
        "expense":    round(week_expense, 0),
        "saved":      saved,
        "top_cat":    top_cat,
        "top_cat_amt": round(week_by_cat.get(top_cat, 0), 0),
    }


# ── Goal progress nudges ──────────────────────────────────────────────

def _goal_nudges(goals):
    nudges = []
    today = date.today()
    for g_obj in goals:
        target = g_obj["target_amount"]
        saved  = g_obj["saved_amount"]
        if target <= 0:
            continue
        pct = (saved / target) * 100
        remaining = target - saved

        for milestone in [100, 90, 75, 50, 25]:
            if pct >= milestone:
                key = f"goal_{g_obj['id']}_m{milestone}"
                if milestone == 100:
                    nudges.append({
                        "key": key, "type": "success", "icon": "🏆",
                        "title": f"Goal Achieved: {g_obj['name']}!",
                        "message": f"You've hit 100% of your goal of ₹{target:,.0f}. Incredible! Time to set a new challenge.",
                        "saving_tip": "Set a new goal to keep building wealth",
                        "action": {"label": "View Goals", "href": "goals.html"}
                    })
                elif milestone == 90:
                    nudges.append({
                        "key": key, "type": "info", "icon": "🎯",
                        "title": f"Almost There: {g_obj['name']}",
                        "message": f"90% done on your ₹{target:,.0f} goal. Just ₹{remaining:,.0f} to go!",
                        "saving_tip": f"One more push of ₹{remaining:,.0f} completes this goal",
                        "action": {"label": "Add to Goal", "href": "goals.html"}
                    })
                break

        if g_obj.get("deadline") and pct < 100:
            try:
                dl = datetime.strptime(g_obj["deadline"], "%Y-%m-%d").date()
                days_left = (dl - today).days
                if 0 < days_left <= 30:
                    per_day = round(remaining / days_left, 0)
                    nudges.append({
                        "key": f"goal_{g_obj['id']}_deadline",
                        "type": "warning", "icon": "⏳",
                        "title": f"Deadline: {g_obj['name']}",
                        "message": f"{days_left} days left to reach ₹{target:,.0f}. You're at {pct:.0f}% — need ₹{per_day:,.0f}/day to make it.",
                        "saving_tip": f"Set aside ₹{per_day:,.0f} daily to hit the deadline",
                        "action": {"label": "Add to Goal", "href": "goals.html"}
                    })
            except Exception:
                pass

    return nudges


# ── Gemini AI nudges ──────────────────────────────────────────────────

def _gemini_nudges(txns, goals, budgets, eom, streak, anomalies):
    if not GEMINI_API_KEY:
        return []

    today = date.today()
    this_month = today.strftime("%Y-%m")

    monthly_cat    = defaultdict(float)
    monthly_income = 0.0
    for t in txns:
        if t["date"][:7] == this_month:
            if t["category"] == "Income":
                monthly_income += t["amount"]
            else:
                monthly_cat[t["category"]] += abs(t["amount"])

    top_spend = sorted(monthly_cat.items(), key=lambda x: -x[1])[:5]
    goal_summary = [
        {"name": g["name"], "pct": round((g["saved_amount"] / g["target_amount"]) * 100, 1) if g["target_amount"] > 0 else 0}
        for g in goals
    ]

    summary = {
        "month": today.strftime("%B %Y"),
        "income_this_month": round(monthly_income, 0),
        "top_spend_categories": {k: round(v, 0) for k, v in top_spend},
        "total_expense": round(sum(v for _, v in top_spend), 0),
        "anomalies_detected": [f"{a['category']} is {a['ratio']}x above normal this week" for a in anomalies],
        "current_streak_days": streak,
        "projected_month_end_balance": eom["projected_balance"] if eom else None,
        "goals": goal_summary,
    }

    prompt = (
        "You are a sharp, friendly Indian personal finance advisor inside FinVault. "
        "Based on this user's financial summary, generate exactly 3 personalised nudges. "
        "Be specific — use the actual numbers from the summary. Be concise and warm. "
        "Each nudge must be a JSON object with these exact keys: "
        "key (unique slug like ai_food_spike), "
        "type (one of: danger, warning, success, info), "
        "icon (1 emoji), "
        "title (max 8 words), "
        "message (2-3 sentences with actual ₹ numbers from the data), "
        "saving_tip (one short actionable tip), "
        "action (object with label string and href string — pick href from: "
        "transactions.html, budget.html, goals.html, reports.html, insights.html). "
        "Return ONLY a valid JSON array, no markdown, no extra text. "
        "Financial summary: " + _json.dumps(summary)
    )

    payload = _json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.6}
    }).encode("utf-8")

    models = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]
    for model in models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
            req = urllib.request.Request(url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=25) as resp:
                result = _json.loads(resp.read())
            raw = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            parsed = _json.loads(raw)
            if isinstance(parsed, list):
                valid = []
                for n in parsed:
                    if all(k in n for k in ["key", "type", "icon", "title", "message", "saving_tip"]):
                        if n.get("type") not in ["danger", "warning", "success", "info"]:
                            n["type"] = "info"
                        if "action" not in n:
                            n["action"] = {"label": "View Transactions", "href": "transactions.html"}
                        valid.append(n)
                if valid:
                    print(f"[AI Nudges] Gemini ({model}) → {len(valid)} nudges")
                    return valid
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            print(f"[AI Nudges] {model} HTTP {e.code}")
            break
        except Exception as ex:
            print(f"[AI Nudges] {model} error: {ex}")
            continue
    return []


# ── Fallback rule-based nudges ────────────────────────────────────────

def _rule_nudges(txns, budgets):
    today = date.today()
    this_month = today.strftime("%Y-%m")
    DEFAULT_BUDGETS = {
        "Food": 3000, "Shopping": 5000, "Subscription": 500,
        "Transport": 2000, "Entertainment": 1000, "Utilities": 2000,
        "Health": 2000, "Education": 3000, "Travel": 5000, "Rent": 15000, "Other": 2000,
    }
    monthly_cat    = defaultdict(float)
    monthly_income = 0.0
    for t in txns:
        if t["date"][:7] == this_month:
            if t["category"] == "Income":
                monthly_income += t["amount"]
            else:
                monthly_cat[t["category"]] += abs(t["amount"])

    total_expense = sum(monthly_cat.values())
    nudges = []

    for cat, spent in monthly_cat.items():
        limit = budgets.get(cat, DEFAULT_BUDGETS.get(cat, 2000))
        pct = (spent / limit * 100) if limit > 0 else 0
        if pct >= 100:
            nudges.append({
                "key": f"budget_exceeded_{cat.lower()}",
                "type": "danger", "icon": "🚨",
                "title": f"{cat} Budget Exceeded",
                "message": f"You've spent ₹{spent:,.0f} on {cat} — that's {pct:.0f}% of your ₹{limit:,.0f} budget.",
                "saving_tip": f"Pause {cat.lower()} spending for the rest of the month",
                "action": {"label": "Edit Budget", "href": "budget.html"}
            })
        elif pct >= 80:
            nudges.append({
                "key": f"budget_80_{cat.lower()}",
                "type": "warning", "icon": "⚠️",
                "title": f"{cat} Budget at {pct:.0f}%",
                "message": f"₹{spent:,.0f} used of your ₹{limit:,.0f} {cat} budget. Only ₹{limit-spent:,.0f} remaining.",
                "saving_tip": f"Spend mindfully on {cat.lower()} this week",
                "action": {"label": "View Budget", "href": "budget.html"}
            })

    if monthly_income > 0 and total_expense > 0.8 * monthly_income:
        pct = round((total_expense / monthly_income) * 100)
        nudges.append({
            "key": "overspending_alert",
            "type": "danger", "icon": "💸",
            "title": "Overspending Alert",
            "message": f"You've spent {pct}% of income this month (₹{total_expense:,.0f} of ₹{monthly_income:,.0f}).",
            "saving_tip": "Set a daily spending limit to stay on track",
            "action": {"label": "View Insights", "href": "insights.html"}
        })
    elif monthly_income > 0:
        saved = monthly_income - total_expense
        rate = round((saved / monthly_income) * 100)
        if rate >= 20:
            nudges.append({
                "key": "great_savings",
                "type": "success", "icon": "✅",
                "title": f"Great Savings Rate — {rate}%!",
                "message": f"Saving ₹{saved:,.0f} ({rate}% of income) this month. Excellent!",
                "saving_tip": "Move surplus into a high-yield FD or mutual fund",
                "action": {"label": "View Goals", "href": "goals.html"}
            })

    if not nudges:
        nudges.append({
            "key": "no_txns_yet",
            "type": "info", "icon": "💡",
            "title": "Add Transactions to Get Nudges",
            "message": "No transactions found for this month yet. Once you log income and expenses, AI will analyse your patterns and generate personalised alerts here.",
            "saving_tip": "Start by logging your salary as income, then add a few expenses",
            "action": {"label": "Add Transaction", "href": "transactions.html"},
            "_never_suppress": True
        })
    return nudges


# ── Master assembler ──────────────────────────────────────────────────

def _get_all_nudges(user_email):
    txns, goals, budgets = _load_data(user_email)
    states    = _get_nudge_states(user_email)
    today     = date.today()
    anomalies = _detect_anomalies(txns)
    streak, daily_limit = _calc_streak(txns, budgets)
    eom       = _predict_eom_balance(txns)

    all_nudges = []

    # 1. Gemini AI nudges (primary)
    ai = _gemini_nudges(txns, goals, budgets, eom, streak, anomalies)
    all_nudges.extend(ai if ai else _rule_nudges(txns, budgets))

    # 2. Anomaly detection
    for a in anomalies:
        all_nudges.append({
            "key": f"anomaly_{a['category'].lower()}",
            "type": "danger", "icon": "📈",
            "title": f"Unusual {a['category']} Spike",
            "message": f"Your {a['category']} spending this week (₹{a['this_week']:,.0f}) is {a['ratio']}× your weekly average of ₹{a['weekly_avg']:,.0f}.",
            "saving_tip": f"Review recent {a['category'].lower()} transactions",
            "action": {"label": "View Transactions", "href": "transactions.html"}
        })

    # 3. Streak
    if streak >= 3:
        emoji = "🔥" if streak >= 7 else "⭐"
        all_nudges.append({
            "key": f"streak_{streak}",
            "type": "success", "icon": emoji,
            "title": f"{streak}-Day Budget Streak!",
            "message": f"You've stayed under your daily budget of ₹{daily_limit:,.0f} for {streak} consecutive days. Real discipline!",
            "saving_tip": "Check your spend tonight to keep the streak alive",
            "action": {"label": "View Dashboard", "href": "dashboard.html"}
        })

    # 4. Goal nudges
    all_nudges.extend(_goal_nudges(goals))

    # 5. End-of-month prediction
    if eom:
        pb = eom["projected_balance"]
        dr = eom["days_remaining"]
        key = "eom_prediction"
        if pb < 0:
            all_nudges.append({
                "key": key, "type": "danger", "icon": "🔮",
                "title": "Projected Overspend",
                "message": f"At ₹{eom['daily_rate']:,.0f}/day you'll overshoot income by ₹{abs(pb):,.0f} by month end. {dr} days left.",
                "saving_tip": f"Cut ₹{round(abs(pb)/max(dr,1),0):,.0f}/day to break even",
                "action": {"label": "View Budget", "href": "budget.html"}
            })
        elif pb < eom["income"] * 0.1:
            all_nudges.append({
                "key": key, "type": "warning", "icon": "🔮",
                "title": "Tight Month Ahead",
                "message": f"On track to save only ₹{pb:,.0f} by month end at ₹{eom['daily_rate']:,.0f}/day with {dr} days left.",
                "saving_tip": "Reduce discretionary spending this week",
                "action": {"label": "View Insights", "href": "insights.html"}
            })
        elif pb > eom["income"] * 0.3:
            all_nudges.append({
                "key": key, "type": "success", "icon": "🔮",
                "title": "Strong Month Projected",
                "message": f"On track to save ₹{pb:,.0f} this month. Daily spend ₹{eom['daily_rate']:,.0f} with {dr} days remaining.",
                "saving_tip": "Move the surplus to a goal or FD",
                "action": {"label": "View Goals", "href": "goals.html"}
            })

    # 6. Weekly digest (Mondays)
    if today.weekday() == 0:
        digest = _build_weekly_digest(txns)
        if digest:
            saved_str = f"Saved ₹{digest['saved']:,.0f}." if digest["saved"] and digest["saved"] > 0 else "No net savings."
            all_nudges.append({
                "key": "weekly_digest",
                "type": "info", "icon": "📊",
                "title": f"Weekly Digest: {digest['week_start']} – {digest['week_end']}",
                "message": (
                    f"Last week: Income ₹{digest['income']:,.0f} · Spent ₹{digest['expense']:,.0f}. "
                    f"{saved_str} Top: {digest['top_cat']} (₹{digest['top_cat_amt']:,.0f})."
                ),
                "saving_tip": f"Focus on trimming {digest['top_cat'].lower()} this week",
                "action": {"label": "View Reports", "href": "reports.html"}
            })

    # Salary credit
    this_month = today.strftime("%Y-%m")
    salary_txn = next(
        (t for t in txns if t["category"] == "Income" and t["date"].startswith(this_month) and t["amount"] > 0),
        None
    )

    # Filter dismissed/snoozed (never suppress informational fallback nudges)
    visible = [n for n in all_nudges if n.get("_never_suppress") or not _is_suppressed(n.get("key", ""), states)]

    # Sort: danger → warning → success → info
    ORDER = {"danger": 0, "warning": 1, "success": 2, "info": 3}
    visible.sort(key=lambda n: ORDER.get(n.get("type", "info"), 3))

    return visible, salary_txn


# ── Endpoints ─────────────────────────────────────────────────────────

@nudge_bp.route("/nudges", methods=["GET"])
@token_required
def get_nudges():
    nudges, _ = _get_all_nudges(g.user_email)
    return jsonify(nudges)


@nudge_bp.route("/nudges/full", methods=["GET"])
@token_required
def get_nudges_full():
    txns, goals, budgets = _load_data(g.user_email)
    nudges, salary_txn   = _get_all_nudges(g.user_email)
    eom                  = _predict_eom_balance(txns)
    streak, daily_limit  = _calc_streak(txns, budgets)
    return jsonify({
        "nudges": nudges,
        "salary": {"amount": salary_txn["amount"], "merchant": salary_txn["merchant"]} if salary_txn else None,
        "eom": eom,
        "streak": {"days": streak, "daily_limit": daily_limit},
    })


@nudge_bp.route("/nudges/<nudge_key>/snooze", methods=["POST"])
@token_required
def snooze_nudge(nudge_key):
    _ensure_nudge_state_table()
    days  = int((request.json or {}).get("days", 3))
    until = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")
    conn  = get_conn()
    conn.execute(
        """INSERT INTO nudge_state(user_email,nudge_key,state,snoozed_until) VALUES(?,?,?,?)
           ON CONFLICT(user_email,nudge_key)
           DO UPDATE SET state='snoozed',snoozed_until=excluded.snoozed_until,updated_at=datetime('now')""",
        (g.user_email, nudge_key, "snoozed", until)
    )
    conn.commit(); conn.close()
    return jsonify({"success": True, "snoozed_until": until})


@nudge_bp.route("/nudges/<nudge_key>/dismiss", methods=["POST"])
@token_required
def dismiss_nudge(nudge_key):
    _ensure_nudge_state_table()
    conn = get_conn()
    conn.execute(
        """INSERT INTO nudge_state(user_email,nudge_key,state) VALUES(?,?,?)
           ON CONFLICT(user_email,nudge_key)
           DO UPDATE SET state='dismissed',snoozed_until=NULL,updated_at=datetime('now')""",
        (g.user_email, nudge_key, "dismissed")
    )
    conn.commit(); conn.close()
    return jsonify({"success": True})


@nudge_bp.route("/nudges/reset", methods=["POST"])
@token_required
def reset_nudges():
    _ensure_nudge_state_table()
    conn = get_conn()
    conn.execute("DELETE FROM nudge_state WHERE user_email=?", (g.user_email,))
    conn.commit(); conn.close()
    return jsonify({"success": True})
