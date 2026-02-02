from flask import Flask, request, jsonify
import requests, os, uuid
from datetime import datetime
import sqlite3

app = Flask(__name__)

# ===============================
# ENV CONFIG (RENDER)
# ===============================
RUNDECK_URL = os.getenv("RUNDECK_URL", "").strip()
RUNDECK_API_TOKEN = os.getenv("RUNDECK_API_TOKEN", "").strip()

if not RUNDECK_URL or not RUNDECK_API_TOKEN:
    raise RuntimeError("RUNDECK_URL or RUNDECK_API_TOKEN not set")

# ===============================
# SQLITE STORE (REPLACES MEMORY)
# ===============================
conn = sqlite3.connect("approvals.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    execution_id TEXT,
    release_id TEXT,
    ai_decision TEXT,
    status TEXT,
    created_at TEXT
)
""")
conn.commit()

# -------------------------------
# HEALTH
# -------------------------------
@app.route("/")
def health():
    return "Approval Service running"

# -------------------------------
# CREATE APPROVAL (CALLED BY RUNDECK)
# -------------------------------
@app.route("/request-approval", methods=["POST"])
def request_approval():
    data = request.json

    approval_id = f"appr_{uuid.uuid4().hex[:12]}"

    cur.execute(
        "INSERT INTO approvals VALUES (?,?,?,?,?,?)",
        (
            approval_id,
            data["execution_id"],
            data["release_id"],
            data["ai_decision"],
            "PENDING",
            datetime.utcnow().isoformat()
        )
    )
    conn.commit()

    approval_url = f"{request.host_url.rstrip('/')}/approval/{approval_id}"

    return jsonify({
        "approval_id": approval_id,
        "approval_url": approval_url
    })

# -------------------------------
# APPROVAL PAGE (UI)
# -------------------------------
@app.route("/approval/<approval_id>")
def approval_page(approval_id):
    cur.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,))
    row = cur.fetchone()

    if not row:
        return "Invalid approval ID", 404

    if row[4] != "PENDING":
        return f"Already decided: {row[4]}"

    return f"""
    <h2>🚨 Release Approval Required</h2>
    <p><b>Release:</b> {row[2]}</p>
    <p><b>AI Recommendation:</b> {row[3]}</p>

    <a href="/decision/{approval_id}/CONTINUE"><button>CONTINUE</button></a><br><br>
    <a href="/decision/{approval_id}/PAUSE"><button>PAUSE</button></a><br><br>
    <a href="/decision/{approval_id}/ROLLBACK"><button>ROLLBACK</button></a>
    """

# -------------------------------
# DECISION HANDLER
# -------------------------------
@app.route("/decision/<approval_id>/<decision>")
def decision(approval_id, decision):
    cur.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,))
    row = cur.fetchone()

    if not row:
        return "Invalid approval ID", 404

    if row[4] != "PENDING":
        return f"Already decided: {row[4]}"

    decision = decision.upper()
    exec_id = row[1]

    headers = {
    "X-Rundeck-Auth-Token": RUNDECK_API_TOKEN,
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true"
    }


    if decision == "CONTINUE":
        r = requests.post(
            f"{RUNDECK_URL}/api/41/execution/{exec_id}/resume",
            headers=headers,
            timeout=10
        )
        r.raise_for_status()

    elif decision == "ROLLBACK":
        r = requests.post(
            f"{RUNDECK_URL}/api/41/execution/{exec_id}/abort",
            headers=headers,
            timeout=10
        )
        r.raise_for_status()

    elif decision == "PAUSE":
        pass

    else:
        return "Invalid decision", 400

    cur.execute(
        "UPDATE approvals SET status=? WHERE approval_id=?",
        (decision, approval_id)
    )
    conn.commit()

    return f"Decision applied: {decision}"

# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
