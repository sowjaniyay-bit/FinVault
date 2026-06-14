import os

# ── Load .env FIRST — before any module imports so SECRET_KEY etc are available ──
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from flask import Flask, request, jsonify, Response
from database import init_db
from auth import auth_bp
from transactions import txn_bp
from forecast import forecast_bp
from nudge import nudge_bp
from health_score import health_bp
from goals import goals_bp
from reports import reports_bp
from admin import admin_bp
from dues import dues_bp

app = Flask(__name__)

# ── CORS ──────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500", "http://localhost:5500",
    "http://127.0.0.1:5000", "http://localhost:5000",
    "http://127.0.0.1:3000", "http://localhost:3000",
    "null",
]

def _cors_origin():
    origin = request.headers.get("Origin", "")
    return origin if origin in ALLOWED_ORIGINS else "*"

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"]      = _cors_origin()
    response.headers["Access-Control-Allow-Headers"]     = "Content-Type, Authorization, X-Admin-Key"
    response.headers["Access-Control-Allow-Methods"]     = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        res = Response()
        res.headers["Access-Control-Allow-Origin"]      = _cors_origin()
        res.headers["Access-Control-Allow-Headers"]     = "Content-Type, Authorization, X-Admin-Key"
        res.headers["Access-Control-Allow-Methods"]     = "GET, POST, PUT, DELETE, OPTIONS"
        res.headers["Access-Control-Allow-Credentials"] = "true"
        return res, 200

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found", "success": False}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": f"Server error: {str(e)}", "success": False}), 500

init_db()

app.register_blueprint(auth_bp)
app.register_blueprint(txn_bp)
app.register_blueprint(forecast_bp)
app.register_blueprint(nudge_bp)
app.register_blueprint(health_bp)
app.register_blueprint(goals_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(dues_bp)

# ── Config ────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
PLAID_CLIENT_ID   = os.environ.get("PLAID_CLIENT_ID", "")
PLAID_SECRET      = os.environ.get("PLAID_SECRET", "")
PLAID_ENV         = os.environ.get("PLAID_ENV", "sandbox")
PLAID_BASE        = f"https://{PLAID_ENV}.plaid.com"


# ── Plaid: Create Link Token ──────────────────────────────────────────
@app.route("/plaid/create_link_token", methods=["POST"])
def plaid_create_link_token():
    try:
        import urllib.request, json as _json, urllib.error
        if not PLAID_CLIENT_ID or not PLAID_SECRET:
            return jsonify({"error": "Plaid credentials not configured.", "success": False}), 503
        payload = _json.dumps({
            "client_id": PLAID_CLIENT_ID, "secret": PLAID_SECRET,
            "client_name": "FinVault", "country_codes": ["US"],
            "language": "en", "user": {"client_user_id": "finvault-user"},
            "products": ["transactions"]
        }).encode("utf-8")
        req = urllib.request.Request(f"{PLAID_BASE}/link/token/create", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return jsonify(_json.loads(resp.read()))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err_data = _json.loads(body)
                return jsonify({"error": f"Plaid error: {err_data.get('error_message','Invalid credentials')}", "success": False}), 400
            except Exception:
                return jsonify({"error": f"Plaid HTTP {e.code}", "success": False}), 400
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── Plaid: Exchange Token ─────────────────────────────────────────────
@app.route("/plaid/exchange_token", methods=["POST"])
def plaid_exchange_token():
    try:
        import urllib.request, json as _json, urllib.error, jwt as _jwt
        from transactions import categorize
        from database import get_conn
        from auth import SECRET_KEY
        from datetime import date, timedelta

        if not PLAID_CLIENT_ID or not PLAID_SECRET:
            return jsonify({"error": "Plaid credentials not configured", "success": False}), 503

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Authorization token missing", "success": False}), 401
        token = auth_header.split(" ")[1]
        try:
            payload = _jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user_email = payload["email"]
        except Exception:
            return jsonify({"error": "Invalid or expired token", "success": False}), 401

        data = request.json or {}
        public_token = data.get("public_token")
        if not public_token:
            return jsonify({"error": "Missing public_token", "success": False}), 400

        payload = _json.dumps({"client_id": PLAID_CLIENT_ID, "secret": PLAID_SECRET, "public_token": public_token}).encode("utf-8")
        req = urllib.request.Request(f"{PLAID_BASE}/item/public_token/exchange", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            access_token = _json.loads(resp.read())["access_token"]

        start = (date.today() - timedelta(days=30)).isoformat()
        end = date.today().isoformat()
        payload2 = _json.dumps({"client_id": PLAID_CLIENT_ID, "secret": PLAID_SECRET, "access_token": access_token, "start_date": start, "end_date": end}).encode("utf-8")
        req2 = urllib.request.Request(f"{PLAID_BASE}/transactions/get", data=payload2, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req2, timeout=15) as resp:
            txn_data = _json.loads(resp.read())

        conn = get_conn()
        imported = 0
        for t in txn_data.get("transactions", []):
            merchant = t.get("name", "Unknown")
            plaid_amount = float(t.get("amount", 0))
            amount = abs(plaid_amount)
            date_str = t.get("date", end)
            plaid_id = t.get("transaction_id")
            category = "Income" if plaid_amount < 0 else categorize(merchant)
            try:
                cur = conn.execute("INSERT OR IGNORE INTO transactions(user_email,plaid_id,merchant,amount,date,category) VALUES(?,?,?,?,?,?)", (user_email, plaid_id, merchant, amount, date_str, category))
                if cur.rowcount > 0:
                    imported += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        return jsonify({"success": True, "imported": imported, "message": f"{imported} transactions imported!"})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── Forgot Password ───────────────────────────────────────────────────
@app.route("/forgot_password", methods=["POST"])
def forgot_password():
    try:
        from auth import _hash_password
        from database import get_conn
        data = request.json or {}
        email = data.get("email", "").strip().lower()
        new_pass = data.get("new_password", "")
        if not email or not new_pass:
            return jsonify({"error": "Email and new password required", "success": False}), 400
        conn = get_conn()
        row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "No account found with that email", "success": False}), 404
        conn.execute("UPDATE users SET password=? WHERE email=?", (_hash_password(new_pass), email))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Password updated!"})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── Sample Data Import ────────────────────────────────────────────────
@app.route("/import_sample_data", methods=["POST"])
def import_sample_data():
    try:
        from database import get_conn
        from datetime import date, timedelta
        import jwt

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token missing", "success": False}), 401
        token = auth_header.split(" ")[1]
        from auth import SECRET_KEY
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except Exception:
            return jsonify({"error": "Invalid session", "success": False, "expired": True}), 401
        user_email = payload["email"]
        bank = request.json.get("bank", "generic") if request.json else "generic"
        today = date.today()
        def ago(n): return (today - timedelta(days=n)).isoformat()

        # Each bank has a distinct salary level, lifestyle, and spending pattern
        BANK_DATA = {
            "sbi": [
                # Income — government employee profile, ₹52,000/month
                ("SBI Salary Credit - Govt", 52000, "Income", ago(2)),
                ("SBI Salary Credit - Govt", 52000, "Income", ago(32)),
                ("SBI Salary Credit - Govt", 52000, "Income", ago(62)),
                ("SBI DA Arrears Credit", 8400, "Income", ago(20)),
                # Loans & EMIs
                ("SBI Car Loan EMI", 11500, "Other", ago(3)),
                ("SBI RD Installment", 3000, "Other", ago(3)),
                ("SBI Mutual Fund SIP", 5000, "Other", ago(4)),
                ("LIC Premium", 4200, "Health", ago(18)),
                # UPI & daily
                ("UPI-PhonePe-Kirana", 960, "Food", ago(1)),
                ("UPI-GPay-Sabzi Mandi", 340, "Food", ago(5)),
                ("UPI-BHIM-Milk Dairy", 180, "Food", ago(8)),
                ("SBI YONO Cash Withdrawal", 5000, "Other", ago(10)),
                ("Swiggy", 320, "Food", ago(12)),
                ("Zomato", 280, "Food", ago(22)),
                ("MTR Foods Online", 490, "Food", ago(28)),
                # Transport
                ("HPCL Petrol Pump", 2800, "Transport", ago(7)),
                ("SBI FASTag Recharge", 1000, "Transport", ago(15)),
                ("KSRTC Bus Pass", 850, "Transport", ago(20)),
                # Utilities
                ("BESCOM Electricity Bill", 1620, "Utilities", ago(12)),
                ("BWSSB Water Bill", 310, "Utilities", ago(14)),
                ("BSNL Broadband", 699, "Utilities", ago(16)),
                ("Airtel Prepaid Recharge", 299, "Utilities", ago(6)),
                # Entertainment & Shopping
                ("Hotstar Premium", 299, "Subscription", ago(5)),
                ("Amazon Shopping", 890, "Shopping", ago(9)),
                ("D-Mart Groceries", 2200, "Food", ago(3)),
                ("Reliance Smart Bazaar", 1650, "Shopping", ago(18)),
                # Rent
                ("House Rent - Rajajinagar", 10000, "Rent", ago(1)),
                ("House Rent - Rajajinagar", 10000, "Rent", ago(31)),
                # Health
                ("Apollo Pharmacy", 380, "Health", ago(11)),
                ("Govt Hospital Fees", 150, "Health", ago(25)),
            ],
            "hdfc": [
                # Income — private IT employee, ₹85,000/month
                ("HDFC Salary - Infosys", 85000, "Income", ago(1)),
                ("HDFC Salary - Infosys", 85000, "Income", ago(31)),
                ("HDFC Salary - Infosys", 85000, "Income", ago(61)),
                ("Freelance - Upwork", 18000, "Income", ago(14)),
                ("HDFC FD Interest Credit", 2100, "Income", ago(20)),
                # Loans & investments
                ("HDFC Home Loan EMI", 24500, "Rent", ago(2)),
                ("HDFC Home Loan EMI", 24500, "Rent", ago(32)),
                ("HDFC Life Smart Protect", 3200, "Health", ago(5)),
                ("HDFC Mutual Fund SIP", 10000, "Other", ago(4)),
                ("HDFC Credit Card Bill", 22000, "Other", ago(8)),
                ("Zerodha Stocks", 15000, "Other", ago(12)),
                # Premium lifestyle
                ("Swiggy Genie", 680, "Food", ago(1)),
                ("Zomato Gold Order", 1200, "Food", ago(3)),
                ("Starbucks Coffee", 520, "Food", ago(5)),
                ("Barbeque Nation", 3200, "Food", ago(11)),
                ("Social Restaurant", 2400, "Food", ago(18)),
                ("Swiggy Instamart", 1100, "Food", ago(7)),
                # Transport
                ("Uber Premium", 480, "Transport", ago(2)),
                ("Ola Intercity", 1200, "Transport", ago(9)),
                ("BPCL Petrol", 3500, "Transport", ago(15)),
                ("Fastag Wallet", 800, "Transport", ago(22)),
                # Subscriptions
                ("Netflix Premium", 649, "Subscription", ago(6)),
                ("Spotify Family", 179, "Subscription", ago(8)),
                ("Amazon Prime", 179, "Subscription", ago(10)),
                ("Adobe Creative Cloud", 1675, "Subscription", ago(12)),
                ("YouTube Premium", 189, "Subscription", ago(14)),
                # Shopping
                ("Flipkart Big Sale", 6800, "Shopping", ago(5)),
                ("Myntra Fashion", 3200, "Shopping", ago(10)),
                ("Apple Store", 8999, "Shopping", ago(20)),
                ("Nykaa", 1200, "Shopping", ago(16)),
                # Utilities
                ("Tata Power Electricity", 2800, "Utilities", ago(13)),
                ("Airtel Fiber", 999, "Utilities", ago(15)),
                ("Jio Postpaid", 499, "Utilities", ago(18)),
                # Health
                ("Cult.fit Membership", 2499, "Health", ago(3)),
                ("Max Healthcare", 1500, "Health", ago(22)),
                ("1mg Medicines", 620, "Health", ago(27)),
                # Entertainment
                ("BookMyShow", 900, "Entertainment", ago(8)),
                ("PVR IMAX Gold", 760, "Entertainment", ago(16)),
            ],
            "icici": [
                # Income — senior professional, ₹1,20,000/month
                ("ICICI Corp Salary", 120000, "Income", ago(1)),
                ("ICICI Corp Salary", 120000, "Income", ago(31)),
                ("ICICI Corp Salary", 120000, "Income", ago(61)),
                ("ICICI FD Interest", 4500, "Income", ago(15)),
                ("Rental Income Transfer", 25000, "Income", ago(5)),
                # Large EMIs & investments
                ("ICICI Home Loan EMI", 38000, "Rent", ago(2)),
                ("ICICI Home Loan EMI", 38000, "Rent", ago(32)),
                ("ICICI Vehicle Loan EMI", 12000, "Other", ago(2)),
                ("ICICI Prudential SIP", 20000, "Other", ago(3)),
                ("NPS Tier-1 Contribution", 5000, "Other", ago(5)),
                ("ICICI Lombard Premium", 7500, "Health", ago(10)),
                ("US Stocks - INDmoney", 25000, "Other", ago(8)),
                # Premium food
                ("Taj Hotel Dining", 8500, "Food", ago(4)),
                ("Zomato Pro Order", 1800, "Food", ago(7)),
                ("ITC Grand Buffet", 4200, "Food", ago(14)),
                ("Swiggy Corporate", 950, "Food", ago(9)),
                ("Starbucks Reserve", 720, "Food", ago(12)),
                ("Nature's Basket Grocery", 4500, "Food", ago(6)),
                # Transport
                ("Uber Black", 1200, "Transport", ago(3)),
                ("IndiGo Airlines", 8500, "Travel", ago(18)),
                ("Ola Prime", 650, "Transport", ago(6)),
                ("IOCL Petrol", 5000, "Transport", ago(12)),
                ("ParkSmart Parking", 300, "Transport", ago(8)),
                # Premium subscriptions
                ("Netflix Ultra HD", 649, "Subscription", ago(5)),
                ("Spotify Premium", 119, "Subscription", ago(7)),
                ("Audible", 399, "Subscription", ago(9)),
                ("LinkedIn Premium", 2600, "Subscription", ago(11)),
                ("GitHub Copilot", 830, "Subscription", ago(13)),
                # Luxury shopping
                ("Tanishq Jewellery", 45000, "Shopping", ago(20)),
                ("Croma Electronics", 12000, "Shopping", ago(8)),
                ("Lifestyle Stores", 8000, "Shopping", ago(15)),
                ("Nykaa Luxe", 3500, "Shopping", ago(18)),
                # Utilities (luxury apartment)
                ("APEPDCL Electricity", 5200, "Utilities", ago(11)),
                ("Airtel Black", 1499, "Utilities", ago(14)),
                ("Society Maintenance", 6000, "Utilities", ago(2)),
                # Health
                ("Manipal Hospital", 4500, "Health", ago(22)),
                ("Gold's Gym Membership", 3500, "Health", ago(4)),
                ("PharmEasy Premium", 1800, "Health", ago(16)),
                # Entertainment
                ("BookMyShow Premium", 2400, "Entertainment", ago(9)),
                ("Sunburn Festival Ticket", 5000, "Entertainment", ago(25)),
            ],
            "axis": [
                # Income — startup employee + freelancer, ₹72,000/month
                ("Axis Bank Salary Credit", 72000, "Income", ago(3)),
                ("Axis Bank Salary Credit", 72000, "Income", ago(33)),
                ("Axis Bank Salary Credit", 72000, "Income", ago(63)),
                ("Freelance Design - Fiverr", 9500, "Income", ago(11)),
                ("Cashback Credit Axis", 1200, "Income", ago(18)),
                # EMIs
                ("Axis Home Loan EMI", 19500, "Rent", ago(4)),
                ("Axis Neo Credit Bill", 14000, "Other", ago(7)),
                ("Bajaj Finserv EMI", 3200, "Shopping", ago(4)),
                ("Axis Mutual Fund SIP", 5000, "Other", ago(5)),
                # Food - mix of delivery & eating out
                ("Swiggy One Order", 590, "Food", ago(2)),
                ("Zomato", 450, "Food", ago(6)),
                ("Chaayos Coffee", 180, "Food", ago(8)),
                ("Rebel Foods", 720, "Food", ago(13)),
                ("BigBasket", 1800, "Food", ago(4)),
                ("Zepto Groceries", 650, "Food", ago(9)),
                ("Haldiram's", 320, "Food", ago(19)),
                # Transport
                ("Rapido Bike Taxi", 95, "Transport", ago(1)),
                ("Uber Auto", 140, "Transport", ago(4)),
                ("Ola Mini", 200, "Transport", ago(7)),
                ("BMTC Bus Card", 300, "Transport", ago(15)),
                ("HP Petrol Pump", 2100, "Transport", ago(20)),
                # Subscriptions
                ("Netflix Standard", 649, "Subscription", ago(6)),
                ("Hotstar Mobile", 149, "Subscription", ago(8)),
                ("Spotify", 119, "Subscription", ago(10)),
                ("Notion Pro", 330, "Subscription", ago(12)),
                ("Figma Professional", 1200, "Subscription", ago(14)),
                # Shopping
                ("Amazon Sale Purchase", 3400, "Shopping", ago(5)),
                ("Flipkart SuperCoins", 1800, "Shopping", ago(11)),
                ("Ajio Fashion", 1400, "Shopping", ago(17)),
                ("Boat Accessories", 2200, "Shopping", ago(24)),
                # Utilities
                ("MSEDCL Electricity", 1900, "Utilities", ago(12)),
                ("Airtel DTH", 450, "Utilities", ago(16)),
                ("Vi Postpaid", 399, "Utilities", ago(19)),
                # Health
                ("Medplus Pharmacy", 460, "Health", ago(10)),
                ("CureFit Session", 899, "Health", ago(5)),
                # Entertainment
                ("Inox Movies", 480, "Entertainment", ago(7)),
                ("Steam Games", 1200, "Entertainment", ago(22)),
                # Rent
                ("PG Accommodation - HSR", 12000, "Rent", ago(1)),
                ("PG Accommodation - HSR", 12000, "Rent", ago(31)),
            ],
            "kotak": [
                # Income — small business owner, variable income
                ("Kotak Current A/C Credit", 95000, "Income", ago(4)),
                ("Kotak Current A/C Credit", 78000, "Income", ago(28)),
                ("Kotak Current A/C Credit", 110000, "Income", ago(58)),
                ("GST Refund Credit", 12000, "Income", ago(22)),
                ("Kotak FD Interest", 3200, "Income", ago(15)),
                # Business & personal EMIs
                ("Kotak Business Loan EMI", 18000, "Other", ago(5)),
                ("Kotak Car Loan EMI", 14500, "Other", ago(5)),
                ("Kotak Mahindra SIP", 8000, "Other", ago(6)),
                ("LIC Endowment Policy", 5500, "Health", ago(8)),
                # Business expenses (food with clients)
                ("Taj Vivanta Lunch", 6200, "Food", ago(3)),
                ("The Capital Grill", 4800, "Food", ago(9)),
                ("Swiggy Corporate", 1100, "Food", ago(13)),
                ("Zomato Business", 870, "Food", ago(17)),
                ("Barbeque Nation Team", 7500, "Food", ago(22)),
                ("Wholesale Kirana Vendor", 3200, "Food", ago(6)),
                # Transport - car owner
                ("IOC Petrol Fill-up", 4500, "Transport", ago(5)),
                ("Fastag Highway", 1200, "Transport", ago(10)),
                ("Ola Prime Outstation", 2400, "Transport", ago(15)),
                ("Car Service - Maruti", 4800, "Other", ago(25)),
                # Utilities
                ("TPDDL Electricity Delhi", 3800, "Utilities", ago(13)),
                ("ACT Fibernet", 1299, "Utilities", ago(16)),
                ("Airtel Postpaid Family", 899, "Utilities", ago(19)),
                ("Society Maintenance", 4500, "Utilities", ago(1)),
                # Subscriptions
                ("Netflix", 649, "Subscription", ago(7)),
                ("Amazon Prime", 179, "Subscription", ago(9)),
                ("Tally ERP License", 1800, "Other", ago(14)),
                ("Zoho CRM", 2400, "Other", ago(14)),
                # Shopping
                ("Office Supplies - Amazon", 4200, "Shopping", ago(4)),
                ("IKEA Home Office", 12000, "Shopping", ago(18)),
                ("Croma Laptop", 55000, "Shopping", ago(30)),
                ("Flipkart Business", 3600, "Shopping", ago(11)),
                # Health
                ("Star Health Insurance", 8000, "Health", ago(20)),
                ("Fortis Hospital", 3200, "Health", ago(24)),
                ("Gym Membership Premium", 2500, "Health", ago(3)),
                # Rent (office + home)
                ("Office Rent - Nehru Place", 25000, "Rent", ago(1)),
                ("Apartment Rent - Noida", 22000, "Rent", ago(1)),
                ("Office Rent - Nehru Place", 25000, "Rent", ago(31)),
                ("Apartment Rent - Noida", 22000, "Rent", ago(31)),
            ],
            "pnb": [
                # Income — teacher/lecturer, ₹45,000/month
                ("PNB Salary - Education Dept", 45000, "Income", ago(3)),
                ("PNB Salary - Education Dept", 45000, "Income", ago(33)),
                ("PNB Salary - Education Dept", 45000, "Income", ago(63)),
                ("Tuition Income Cash", 8000, "Income", ago(12)),
                ("PNB FD Maturity", 15000, "Income", ago(22)),
                # Loans
                ("PNB Housing Loan EMI", 12000, "Rent", ago(4)),
                ("PNB Housing Loan EMI", 12000, "Rent", ago(34)),
                ("PNB RD Monthly Deposit", 3000, "Other", ago(4)),
                ("PLI (Postal Life Insurance)", 2800, "Health", ago(10)),
                ("PPF Contribution", 5000, "Other", ago(5)),
                # Conservative spending - food
                ("Saravana Bhavan", 480, "Food", ago(2)),
                ("Haldiram Restaurant", 350, "Food", ago(7)),
                ("UPI-PhonePe-Vegetables", 220, "Food", ago(1)),
                ("Swiggy (occasional)", 290, "Food", ago(14)),
                ("Local Grocery Store", 1800, "Food", ago(5)),
                ("Ration Shop", 450, "Food", ago(20)),
                ("Milk Booth UPI", 150, "Food", ago(3)),
                # Transport - conservative
                ("City Bus Monthly Pass", 500, "Transport", ago(2)),
                ("BPCL Petrol - Scooter", 900, "Transport", ago(10)),
                ("Auto Rickshaw UPI", 80, "Transport", ago(5)),
                ("Auto Rickshaw UPI", 60, "Transport", ago(12)),
                # Utilities
                ("TNEB Electricity Bill", 820, "Utilities", ago(14)),
                ("BSNL Monthly Bill", 299, "Utilities", ago(16)),
                ("Water Board Bill", 180, "Utilities", ago(18)),
                # Subscriptions (minimal)
                ("Jio Prepaid Recharge", 239, "Utilities", ago(8)),
                ("Hotstar Basic", 299, "Subscription", ago(9)),
                # Shopping - necessity
                ("D-Mart Monthly", 2800, "Shopping", ago(6)),
                ("Pothys Textiles", 3500, "Shopping", ago(25)),
                ("Amazon (books)", 560, "Shopping", ago(19)),
                # Health
                ("Govt Hospital Consultation", 100, "Health", ago(20)),
                ("Medical Store", 480, "Health", ago(22)),
                # Education
                ("Books & Stationery", 650, "Education", ago(18)),
                ("Coaching Material", 450, "Education", ago(30)),
                # Rent paid separately
                ("House Rent - Tambaram", 8000, "Rent", ago(1)),
                ("House Rent - Tambaram", 8000, "Rent", ago(31)),
                # Entertainment
                ("SunTV DTH Recharge", 250, "Entertainment", ago(11)),
                ("Temple Donation UPI", 500, "Other", ago(7)),
            ],
            "bob": [
                # Income — mid-level banker/finance professional, ₹68,000/month
                ("BOB Salary Credit", 68000, "Income", ago(2)),
                ("BOB Salary Credit", 68000, "Income", ago(32)),
                ("BOB Salary Credit", 68000, "Income", ago(62)),
                ("Performance Bonus Credit", 20000, "Income", ago(20)),
                ("BOB FD Interest", 2800, "Income", ago(18)),
                # EMIs & investments
                ("BOB Home Loan EMI", 17500, "Rent", ago(3)),
                ("BOB Home Loan EMI", 17500, "Rent", ago(33)),
                ("BOB Credit Card Bill", 18000, "Other", ago(7)),
                ("BOB Baroda SIP", 6000, "Other", ago(5)),
                ("NPS Contribution", 3000, "Other", ago(5)),
                ("Bajaj Allianz Insurance", 5200, "Health", ago(12)),
                # Food habits - moderate
                ("Zomato", 680, "Food", ago(2)),
                ("Swiggy", 520, "Food", ago(5)),
                ("KFC Family Meal", 1200, "Food", ago(9)),
                ("McDonald's", 440, "Food", ago(14)),
                ("Cafe Coffee Day", 280, "Food", ago(7)),
                ("Bigbasket Weekly", 2400, "Food", ago(4)),
                ("Paradise Biryani", 780, "Food", ago(18)),
                ("Domino's Pizza", 560, "Food", ago(23)),
                # Transport
                ("Uber", 360, "Transport", ago(3)),
                ("Ola", 240, "Transport", ago(8)),
                ("IOC Petrol", 3200, "Transport", ago(11)),
                ("Metro Smart Card", 500, "Transport", ago(17)),
                # Subscriptions
                ("Netflix", 649, "Subscription", ago(6)),
                ("Amazon Prime", 179, "Subscription", ago(8)),
                ("Spotify", 119, "Subscription", ago(10)),
                ("Zee5 Premium", 999, "Subscription", ago(12)),
                # Shopping
                ("Flipkart Fashion", 2800, "Shopping", ago(7)),
                ("Amazon Purchase", 4200, "Shopping", ago(13)),
                ("Westside Clothing", 2100, "Shopping", ago(20)),
                ("Decathlon Sports", 3500, "Shopping", ago(27)),
                # Utilities
                ("Adani Electricity", 2200, "Utilities", ago(14)),
                ("Airtel Broadband", 999, "Utilities", ago(16)),
                ("Vodafone Postpaid", 449, "Utilities", ago(19)),
                # Health
                ("Apollo 24|7", 800, "Health", ago(10)),
                ("HealthifyMe Pro", 900, "Health", ago(6)),
                ("Medplus", 340, "Health", ago(22)),
                # Entertainment
                ("BookMyShow", 700, "Entertainment", ago(8)),
                ("Carnival Cinemas", 420, "Entertainment", ago(20)),
                # Rent
                ("Flat Rent - Banjara Hills", 14000, "Rent", ago(1)),
                ("Flat Rent - Banjara Hills", 14000, "Rent", ago(31)),
                # Misc
                ("Gym Membership", 1500, "Health", ago(4)),
            ],
        }

        # Generic fallback — average Indian urban profile
        generic_data = [
            ("Salary Credit", 60000, "Income", ago(2)),
            ("Salary Credit", 60000, "Income", ago(32)),
            ("Salary Credit", 60000, "Income", ago(62)),
            ("Freelance Payment", 10000, "Income", ago(15)),
            ("Netflix", 649, "Subscription", ago(5)),
            ("Spotify", 119, "Subscription", ago(8)),
            ("Amazon Prime", 179, "Subscription", ago(12)),
            ("House Rent", 13000, "Rent", ago(1)),
            ("House Rent", 13000, "Rent", ago(31)),
            ("Electricity Bill", 1200, "Utilities", ago(18)),
            ("Airtel Broadband", 799, "Utilities", ago(20)),
            ("Jio Recharge", 239, "Utilities", ago(10)),
            ("Swiggy", 480, "Food", ago(1)),
            ("Zomato", 390, "Food", ago(4)),
            ("Dominos", 520, "Food", ago(7)),
            ("Bigbasket", 1400, "Food", ago(6)),
            ("Uber", 250, "Transport", ago(2)),
            ("Ola", 175, "Transport", ago(5)),
            ("Amazon Shopping", 1299, "Shopping", ago(6)),
            ("Flipkart", 2499, "Shopping", ago(11)),
            ("Apollo Pharmacy", 420, "Health", ago(8)),
            ("BookMyShow", 600, "Entertainment", ago(7)),
        ]

        transactions = BANK_DATA.get(bank, generic_data)
        conn = get_conn()
        imported = 0
        for row in transactions:
            merchant, amount, category, txn_date = row
            try:
                conn.execute("INSERT INTO transactions(user_email,merchant,amount,date,category) VALUES(?,?,?,?,?)", (user_email, merchant, float(amount), txn_date, category))
                imported += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        bank_label = bank.upper() if bank != "generic" else "Sample"
        return jsonify({"success": True, "imported": imported, "message": f"{imported} {bank_label} transactions loaded!"})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


# ── Clear Data ────────────────────────────────────────────────────────
@app.route("/clear_data", methods=["POST"])
def clear_data():
    try:
        import jwt as _jwt
        from database import get_conn
        from auth import SECRET_KEY
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token missing", "success": False}), 401
        token = auth_header.split(" ")[1]
        try:
            payload = _jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user_email = payload["email"]
        except Exception:
            return jsonify({"error": "Invalid or expired token", "success": False}), 401
        data = request.json or {}
        clear_goals = data.get("clear_goals", False)
        conn = get_conn()
        txn_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE user_email=?", (user_email,)).fetchone()[0]
        conn.execute("DELETE FROM transactions WHERE user_email=?", (user_email,))
        if clear_goals:
            conn.execute("DELETE FROM goals WHERE user_email=?", (user_email,))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": f"Cleared {txn_count} transactions", "deleted": txn_count})
    except Exception as e:
        return jsonify({"error": str(e), "success": False}), 500


@app.route("/")
def home():
    return jsonify({"status": "FinVault server running", "success": True})


if __name__ == "__main__":
    app.run(debug=False, port=5000)
