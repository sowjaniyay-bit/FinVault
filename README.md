# FinVault — Privacy-Preserving Smart Finance Advisory App

## Quick Start

### 1. Install backend dependencies
```bash
cd backend
pip install flask bcrypt PyJWT
```

### 2. Set up environment
Edit `backend/.env` and add your API keys:
```
SECRET_KEY=your_secret_here
ANTHROPIC_API_KEY=sk-ant-...   # From console.anthropic.com (for AI chat)
PLAID_CLIENT_ID=...            # From dashboard.plaid.com (for bank sync)
PLAID_SECRET=...
PLAID_ENV=sandbox
```

### 3. Start the backend
```bash
cd backend
python app.py
```

### 4. Open the frontend
Open `frontend/login.html` in your browser (or use VS Code Live Server).

---

## Bug Fixes Applied

| File | Bug | Fix |
|------|-----|-----|
| `signup.html` | Called `/register` (doesn't exist) | Fixed to `/signup` |
| `insights.html` | Called `/forecast` (doesn't exist) | Fixed to `/balance_forecast` |
| `goals.html` | Called `/create_goal`, `/get_goals` (don't exist) | Fixed to `POST /goals`, `GET /goals` |
| `goals.html` | Called `/deposit_goal/{id}`, `/delete_goal/{id}` | Fixed to `/goals/{id}/deposit`, `DELETE /goals/{id}` |
| `reports.html` | Called `/monthly_report`, `/yearly_report` | Fixed to `/report/monthly`, `/report/yearly` |
| `reports.html` | Used `d.net` and `d.alert` (wrong field names) | Fixed to `d.net_savings` and `d.alerts` array |
| `app.py` `/ai_chat` | Expected `{messages:[...]}` but frontend sends `{message, history}` | Backend now accepts both formats |

## Modules Implemented
1. User Registration & Consent Management (`auth.py`)
2. Secure Financial Data Acquisition (`plaid_client.py`)
3. Transaction Preprocessing & Categorization (`transactions.py`)
4. Subscription Auditor (`transactions.py` → `_detect_subs()`)
5. Cash Flow & Spending Pattern Analysis (`transactions.py` → `/cashflow`)
6. Predictive Balance Forecasting (`forecast.py`)
7. Smart Recommendation Engine (`nudge.py`)
8. Financial Health Scoring System (`health_score.py`)
9. Interactive Financial Dashboard (`dashboard.html`)
10. AI Financial Assistant (`assistant.html` + `/ai_chat`)
11. Automated Reports & Alerts (`reports.py`)
12. Goal-Based Savings Planner (`goals.py`)
13. Security & Privacy Layer (`auth.py` — bcrypt + JWT)
14. System Administration & Monitoring (`admin.py`)
