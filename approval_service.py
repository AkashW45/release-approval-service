from flask import Flask, request, jsonify
import requests, os, uuid
from datetime import datetime

import psycopg2
import psycopg2.extras

app = Flask(__name__)

# ===============================
# ENV CONFIG
# ===============================
DATABASE_URL = os.getenv("DATABASE_URL")
DIFY_CALLBACK_URL = os.getenv("DIFY_CALLBACK_URL")  # Workflow 2 webhook

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
# HEALTH CHECK
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
        data.get("execution_id"),
        data.get("release_id"),
        data.get("ai_decision"),
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
    <p><b>AI Recommendation:</b></p>
    <pre>{row['ai_decision']}</pre>

    <a href="/decision/{approval_id}/CONTINUE">
        <button style="background:green;color:white;padding:10px;">CONTINUE</button>
    </a><br><br>

    <a href="/decision/{approval_id}/ROLLBACK">
        <button style="background:red;color:white;padding:10px;">ROLLBACK</button>
    </a>
    """

# ===============================
# STATUS CHECK (Optional)
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

    if decision not in ["CONTINUE", "ROLLBACK"]:
        return "Invalid decision", 400

    # Update status
    cur.execute(
        "UPDATE approvals SET status = %s WHERE approval_id = %s",
        (decision, approval_id)
    )

    # Trigger Dify Workflow 2
    try:
        requests.post(
            DIFY_CALLBACK_URL,
            json={
                "approval_id": approval_id,
                "status": decision,
                "release_id": row["release_id"],
                "execution_id": row["execution_id"]
            },
            timeout=10
        )
    except Exception as e:
        return f"Decision saved but callback failed: {str(e)}", 500

    return f"Decision applied: {decision}"

# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
