from flask import Flask, request, jsonify
import requests, os, uuid
from datetime import datetime

app = Flask(__name__)

RUNDECK_URL = os.getenv("http://<rundeck-host>:4440")
RUNDECK_API_TOKEN = os.getenv("CmUiZAfqVq5fLfGee2oOuznsYEnmuJhS")

APPROVALS = {}

# -------------------------------
# HEALTH
# -------------------------------
@app.route("/")
def health():
    return "Approval Service running"

# -------------------------------
# CREATE APPROVAL (called by Rundeck)
# -------------------------------
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
    a = APPROVALS.get(approval_id)
    if not a:
        return "Invalid approval ID", 404

    if a["status"] != "PENDING":
        return f"Already decided: {a['status']}"

    return f"""
    <h2>🚨 Release Approval Required</h2>
    <p><b>Release:</b> {a['release_id']}</p>
    <p><b>AI Recommendation:</b> {a['ai_decision']}</p>

    <a href="/decision/{approval_id}/CONTINUE"><button>CONTINUE</button></a><br><br>
    <a href="/decision/{approval_id}/PAUSE"><button>PAUSE</button></a><br><br>
    <a href="/decision/{approval_id}/ROLLBACK"><button>ROLLBACK</button></a>
    """

# -------------------------------
# DECISION HANDLER (THIS WAS BROKEN)
# -------------------------------
@app.route("/decision/<approval_id>/<decision>")
def decision(approval_id, decision):
    a = APPROVALS.get(approval_id)
    if not a:
        return "Invalid approval ID", 404

    if a["status"] != "PENDING":
        return f"Already decided: {a['status']}"

    decision = decision.upper()
    exec_id = a["execution_id"]

    headers = {"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN}

    if decision == "CONTINUE":
        requests.post(
            f"{RUNDECK_URL}/api/41/execution/{exec_id}/resume",
            headers=headers,
            timeout=5
        )
        a["status"] = "CONTINUE"

    elif decision == "ROLLBACK":
        requests.post(
            f"{RUNDECK_URL}/api/41/execution/{exec_id}/abort",
            headers=headers,
            timeout=5
        )
        a["status"] = "ROLLBACK"

    elif decision == "PAUSE":
        a["status"] = "PAUSE"
        return "Execution remains paused."

    else:
        return "Invalid decision", 400

    return f"Decision applied: {decision}"

# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
