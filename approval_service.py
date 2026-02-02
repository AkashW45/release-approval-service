from flask import Flask, request, jsonify
import requests, os, uuid
from datetime import datetime

import psycopg2
import psycopg2.extras

app = Flask(__name__)

# ===============================
# ENV CONFIG
# ===============================
RUNDECK_URL = os.getenv("RUNDECK_URL", "").strip()
RUNDECK_API_TOKEN = os.getenv("RUNDECK_API_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL")

if not RUNDECK_URL or not RUNDECK_API_TOKEN:
    raise RuntimeError("RUNDECK_URL or RUNDECK_API_TOKEN not set")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

# ===============================
# POSTGRES CONNECTION
# ===============================
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

cur.execute("""
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    execution_id TEXT,
    release_id TEXT,
    ai_decision TEXT,
    status TEXT,
    created_at TIMESTAMP DEFAULT NOW()
)
""")

# ===============================
# HEALTH
# ===============================
@app.route("/")
def health():
    return "Approval Service running"

# ===============================
# CREATE APPROVAL
# ===============================
@app.route("/request-approval", methods=["POST"])
def request_approval():
    data = request.json
    approval_id = f"appr_{uuid.uuid4().hex[:12]}"

    cur.execute("""
        INSERT INTO approvals (
            approval_id, execution_id, release_id,
            ai_decision, status, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        approval_id,
        data["execution_id"],
        data["release_id"],
        data["ai_decision"],
        "PENDING",
        datetime.utcnow()
    ))

    approval_url = f"{request.host_url.rstrip('/')}/approval/{approval_id}"

    return jsonify({
        "approval_id": approval_id,
        "approval_url": approval_url
    })

# ===============================
# APPROVAL PAGE
# ===============================
@app.route("/approval/<approval_id>")
def approval_page(approval_id):
    cur.execute(
        "SELECT * FROM approvals WHERE approval_id = %s",
        (approval_id,)
    )
    row = cur.fetchone()

    if not row:
        return "Invalid approval ID", 404

    if row["status"] != "PENDING":
        return f"Already decided: {row['status']}"

    return f"""
    <h2>🚨 Release Approval Required</h2>
    <p><b>Release:</b> {row['release_id']}</p>
    <p><b>AI Recommendation:</b> {row['ai_decision']}</p>

    <a href="/decision/{approval_id}/CONTINUE"><button>CONTINUE</button></a><br><br>
    <a href="/decision/{approval_id}/PAUSE"><button>PAUSE</button></a><br><br>
    <a href="/decision/{approval_id}/ROLLBACK"><button>ROLLBACK</button></a>
    """

# ===============================
# STATUS (POLLED BY RUNDECK)
# ===============================
@app.route("/status/<approval_id>")
def approval_status(approval_id):
    cur.execute(
        "SELECT status FROM approvals WHERE approval_id = %s",
        (approval_id,)
    )
    row = cur.fetchone()

    if not row:
        return jsonify({"status": "UNKNOWN"}), 404

    return jsonify({"status": row["status"]})

# ===============================
# DECISION HANDLER
# ===============================
@app.route("/decision/<approval_id>/<decision>")
def decision(approval_id, decision):
    cur.execute(
        "SELECT * FROM approvals WHERE approval_id = %s",
        (approval_id,)
    )
    row = cur.fetchone()

    if not row:
        return "Invalid approval ID", 404

    if row["status"] != "PENDING":
        return f"Already decided: {row['status']}"

    decision = decision.upper()
    exec_id = row["execution_id"]

    headers = {
        "X-Rundeck-Auth-Token": RUNDECK_API_TOKEN,
        "Content-Type": "application/json"
    }

    if decision == "CONTINUE":
        requests.post(
            f"{RUNDECK_URL}/api/41/execution/{exec_id}/resume",
            headers=headers,
            timeout=10
        ).raise_for_status()

    elif decision == "ROLLBACK":
        requests.post(
            f"{RUNDECK_URL}/api/41/execution/{exec_id}/abort",
            headers=headers,
            timeout=10
        ).raise_for_status()

    elif decision == "PAUSE":
        pass

    else:
        return "Invalid decision", 400

    cur.execute(
        "UPDATE approvals SET status = %s WHERE approval_id = %s",
        (decision, approval_id)
    )

    return f"Decision applied: {decision}"

# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
