from flask import Flask, request, jsonify
from datetime import datetime
import uuid
import requests
import os

app = Flask(__name__)

RUNDECK_URL = os.getenv("RUNDECK_URL", "http://127.0.0.1:4440")
RUNDECK_API_TOKEN = os.getenv("RUNDECK_API_TOKEN", "CmUiZAfqVq5fLfGee2oOuznsYEnmuJhS")

APPROVALS = {}

# ------------------ Rundeck helpers ------------------

def rundeck_resume(execution_id):
    requests.post(
        f"{RUNDECK_URL}/api/41/execution/{execution_id}/resume",
        headers={"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN},
        timeout=5
    )

def rundeck_abort(execution_id):
    requests.post(
        f"{RUNDECK_URL}/api/41/execution/{execution_id}/abort",
        headers={"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN},
        timeout=5
    )

# ------------------ Routes ------------------

@app.route("/")
def health():
    return "Approval Service running"

# Rundeck calls this
@app.route("/request-approval", methods=["POST"])
def request_approval():
    data = request.json
    approval_id = f"appr_{uuid.uuid4().hex[:12]}"

    APPROVALS[approval_id] = {
        "execution_id": data["execution_id"],
        "release_id": data["release_id"],
        "ai_decision": data["ai_decision"],
        "status": "PENDING",
        "created_at": datetime.utcnow().isoformat()
    }

    base = request.host_url.rstrip("/")
    return jsonify({
        "approval_id": approval_id,
        "approve_url": f"{base}/approval/{approval_id}"
    })

# Human opens this
@app.route("/approval/<approval_id>")
def approval_page(approval_id):
    if approval_id not in APPROVALS:
        return "Invalid approval ID", 404

    return f"""
    <h2>Release Approval Required</h2>
    <p><b>Release:</b> {APPROVALS[approval_id]['release_id']}</p>
    <p><b>AI Recommendation:</b> {APPROVALS[approval_id]['ai_decision']}</p>

    <form method="post" action="/decision/{approval_id}">
        <button name="decision" value="CONTINUE">✅ Continue</button>
        <button name="decision" value="PAUSE">⏸ Pause</button>
        <button name="decision" value="ROLLBACK">❌ Rollback</button>
    </form>
    """

# Human clicks button
@app.route("/decision/<approval_id>", methods=["POST"])
def decision(approval_id):
    approval = APPROVALS.get(approval_id)
    if not approval or approval["status"] != "PENDING":
        return "Invalid or already decided", 400

    decision = request.form["decision"]
    approval["status"] = decision
    approval["decided_at"] = datetime.utcnow().isoformat()

    if decision == "CONTINUE":
        rundeck_resume(approval["execution_id"])
        return "✅ Release CONTINUED"

    if decision == "ROLLBACK":
        rundeck_abort(approval["execution_id"])
        return "❌ Release ROLLED BACK"

    return "⏸ Release PAUSED (no action taken)"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
