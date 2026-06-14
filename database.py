import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "finance.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # Module 1 — Users (persistent, not in-memory)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Module 3 — Transactions
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            plaid_id TEXT UNIQUE,
            merchant TEXT,
            amount REAL,
            date TEXT,
            category TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Module 12 — Goals
    c.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            name TEXT NOT NULL,
            target_amount REAL NOT NULL,
            saved_amount REAL DEFAULT 0,
            deadline TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Module 13 — Audit log
    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT,
            action TEXT,
            detail TEXT,
            ip TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    """)

    # Module 14 — Admin / system log
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Database initialised")
