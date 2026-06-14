"""
Module 14 — System Monitoring & Admin Logs
"""
from flask import Blueprint, jsonify, request
from database import get_conn

admin_bp = Blueprint("admin", __name__)

import os
ADMIN_KEY = os.environ.get("ADMIN_KEY", "finvault_admin_2024")


def _admin_check():
    return request.headers.get("X-Admin-Key") == ADMIN_KEY


@admin_bp.route("/admin/users", methods=["GET"])
def admin_users():
    if not _admin_check():
        return jsonify({"error": "Unauthorized"}), 403
    conn = get_conn()
    rows = conn.execute("SELECT id, email, created_at FROM users ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/admin/audit", methods=["GET"])
def admin_audit():
    if not _admin_check():
        return jsonify({"error": "Unauthorized"}), 403
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/admin/syslog", methods=["GET"])
def admin_syslog():
    if not _admin_check():
        return jsonify({"error": "Unauthorized"}), 403
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM system_log ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@admin_bp.route("/admin/stats", methods=["GET"])
def admin_stats():
    if not _admin_check():
        return jsonify({"error": "Unauthorized"}), 403
    conn = get_conn()
    users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    txns = conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"]
    goals = conn.execute("SELECT COUNT(*) as c FROM goals").fetchone()["c"]
    logs = conn.execute("SELECT COUNT(*) as c FROM audit_log").fetchone()["c"]
    conn.close()
    return jsonify({
        "total_users": users,
        "total_transactions": txns,
        "total_goals": goals,
        "total_audit_events": logs
    })
