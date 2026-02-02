from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import uuid
import requests
import os

app = Flask(__name__)

# =========================================================
# CONFIG (ENV VARS)
# =========================================================

RUNDECK_URL = os.getenv("RUNDECK_URL", "http://127.0.0.1:4440")
RUNDECK_API_TOKEN = os.getenv("CmUiZAfqVq5fLfGee2oOuznsYEnmuJhS")

# =========================================================
# IN-MEMORY STORE (POC OK)
# =========================================================

APPROVALS = {}

# =========================================================
# RUNDECK ACTIONS
# =========================================================

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

# =========================================================
# ROUTES
# =========================================================

@app.route("/")
def health():
    return "Approval Service running"

# ---------------------------------------------------------
# CREATE APPROVAL (CALLED BY RUNDECK)
# ---------------------------------------------------------
@app.route("/request-approval", methods=["POST"])
def request_approval():
    data = request.json

    for k in ["execution_id", "release_id", "ai_decision"]:
        if k not in data:
            return jsonify({"error": f"Missing {k}"}), 400

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
        "approval_url": f"{base}/approval/{approval_id}"
    })

# ---------------------------------------------------------
# APPROVAL PAGE (HUMAN UI)
# ---------------------------------------------------------
@app.route("/approval/<approval_id>")
def approval_page(approval_id):
    approval = APPROVALS.get(approval_id)
    if not approval:
        return "Invalid approval ID", 404

    if approval["status"] != "PENDING":
        return f"Already decided: {approval['status']}"

    return render_template_string("""
        <h2>🚨 Release Approval Required</h2>
        <p><b>Release:</b> {{ release }}</p>
        <p><b>AI Recommendation:</b> {{ ai }}</p>

        <form method="post" action="/decision/{{ id }}/CONTINUE">
            <button style="padding:10px;">✅ CONTINUE</button>
        </form>

        <form method="post" action="/decision/{{ id }}/PAUSE">
            <button style="padding:10px;">⏸️ PAUSE</button>
        </form>

        <form method="post" action="/decision/{{ id }}/ROLLBACK">
            <button style="padding:10px;">🔁 ROLLBACK</button>
        </form>
    """, id=approval_id, release=approval["release_id"], ai=approval["ai_decision"])

# ---------------------------------------------------------
# HANDLE DECISION
# ---------------------------------------------------------
@app.route("/decision/<approval_id>/<decision>", methods=["POST"])
def decide(approval_id, decision):
    approval = APPROVALS.get(approval_id)
    if not approval:
        return "Invalid approval ID", 404

    if approval["status"] != "PENDING":
        return f"Already decided: {approval['status']}"

    approval["status"] = decision
    approval["decided_at"] = datetime.utcnow().isoformat()

    if decision == "CONTINUE":
        rundeck_resume(approval["execution_id"])
        return "✅ CONTINUE selected. Rundeck resumed."

    if decision == "ROLLBACK":
        rundeck_abort(approval["execution_id"])
        return "🔁 ROLLBACK selected. Rundeck aborted."

    if decision == "PAUSE":
        return "⏸️ PAUSE selected. Rundeck remains halted."

    return "Invalid decision", 400

# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
