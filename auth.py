"""
Module 1  — User Registration & Consent Management
Module 13 — Security: PBKDF2 password hashing, JWT tokens, audit logging

NOTE: Uses Python built-in hashlib (PBKDF2-HMAC-SHA256) instead of bcrypt
      so no extra packages are needed — only flask and PyJWT required.
"""
import hashlib
import hmac
import os
import base64
import jwt
import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, g
from database import get_conn

auth_bp = Blueprint("auth", __name__)

SECRET_KEY = os.environ.get("SECRET_KEY", "finvault_super_secret_2024")

# ---------- PASSWORD HASHING (PBKDF2 — built into Python stdlib) ----------

def _hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 + random salt."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260000)
    return base64.b64encode(salt).decode() + ":" + base64.b64encode(dk).decode()


def _check_password(password: str, stored: str) -> bool:
    """Verify a password against a stored PBKDF2 hash."""
    try:
        salt_b64, hash_b64 = stored.split(":", 1)
        salt = base64.b64decode(salt_b64)
        stored_dk = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260000)
        return hmac.compare_digest(dk, stored_dk)
    except Exception:
        return False


# ---------- HELPERS ----------

def _audit(email, action, detail="", ip=""):
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO audit_log(user_email,action,detail,ip) VALUES(?,?,?,?)",
            (email, action, detail, ip)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _syslog(level, message):
    try:
        conn = get_conn()
        conn.execute("INSERT INTO system_log(level,message) VALUES(?,?)", (level, message))
        conn.commit()
        conn.close()
    except Exception:
        pass


def token_required(f):
    """Decorator — validates JWT and injects g.user_email"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        if not token:
            return jsonify({"error": "Token missing", "success": False}), 401
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            g.user_email = payload["email"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired", "success": False}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token", "success": False}), 401
        return f(*args, **kwargs)
    return decorated


def _make_token(email):
    return jwt.encode(
        {"email": email, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)},
        SECRET_KEY, algorithm="HS256"
    )


# ---------- ROUTES ----------

@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password required", "success": False}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters", "success": False}), 400

    hashed = _hash_password(password)

    try:
        conn = get_conn()
        conn.execute("INSERT INTO users(email,password) VALUES(?,?)", (email, hashed))
        conn.commit()
        conn.close()
    except Exception:
        return jsonify({"error": "Email already registered", "success": False}), 409

    token = _make_token(email)
    _audit(email, "SIGNUP", "New user registered", request.remote_addr)
    _syslog("INFO", f"New user registered: {email}")
    return jsonify({"message": "Account created successfully", "success": True, "token": token})


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    conn = get_conn()
    row = conn.execute("SELECT password FROM users WHERE email=?", (email,)).fetchone()
    conn.close()

    if not row:
        _audit(email, "LOGIN_FAIL", "User not found", request.remote_addr)
        return jsonify({"error": "User not found. Please sign up first.", "success": False}), 404

    if not _check_password(password, row["password"]):
        _audit(email, "LOGIN_FAIL", "Wrong password", request.remote_addr)
        return jsonify({"error": "Incorrect password", "success": False}), 401

    token = _make_token(email)
    _audit(email, "LOGIN", "Login successful", request.remote_addr)
    _syslog("INFO", f"User logged in: {email}")
    return jsonify({"message": "Login successful", "success": True, "token": token})


@auth_bp.route("/me", methods=["GET"])
@token_required
def me():
    return jsonify({"email": g.user_email, "success": True})
