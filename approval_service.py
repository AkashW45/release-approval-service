from flask import Flask, request, jsonify
import requests
from datetime import datetime
import uuid
import os

app = Flask(__name__)

# =========================
# CONFIG (SAFE FOR LOCAL + RENDER)
# =========================

# Rundeck config (use env vars in Render later)
RUNDECK_URL = os.getenv("RUNDECK_URL", "http://127.0.0.1:4440")
RUNDECK_API_TOKEN = os.getenv("RUNDECK_API_TOKEN", "REPLACE_ME_FOR_LOCAL_TEST")

# Optional: Teams / Slack webhook (text-only notifier)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # leave empty if unused

# In-memory approval store (OK for POC)
APPROVALS = {}

# =========================
# HELPERS
# =========================

def send_webhook(message: str):
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"text": message}, timeout=5)
    except Exception as e:
        print(f"Webhook send failed: {e}")

def rundeck_resume(execution_id: str):
    url = f"{RUNDECK_URL}/api/41/execution/{execution_id}/resume"
    headers = {"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN}
    requests.post(url, headers=headers, timeout=5)

def rundeck_abort(execution_id: str):
    url = f"{RUNDECK_URL}/api/41/execution/{execution_id}/abort"
    headers = {"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN}
    requests.post(url, headers=headers, timeout=5)

# =========================
# ROUTES
# =========================

@app.route("/")
def health():
    return "Approval Service is running"

@app.route("/request-approval", methods=["POST"])
def request_approval():
    data = request.json

    # Basic validation
    required = ["execution_id", "release_id", "ai_decision"]
    for key in required:
        if key not in data:
            return jsonify({"error": f"Missing field: {key}"}), 400

    approval_id = str(uuid.uuid4())

    APPROVALS[approval_id] = {
        "status": "PENDING",
        "execution_id": data["execution_id"],
        "release_id": data["release_id"],
        "ai_decision": data["ai_decision"],
        "created_at": datetime.utcnow().isoformat()
    }

    # Auto-detect base URL (localhost or Render)
    base_url = request.host_url.rstrip("/")

    approve_link = f"{base_url}/approve/{approval_id}"
    reject_link = f"{base_url}/reject/{approval_id}"

    message = (
        f"🚨 Release Approval Required\n\n"
        f"Release: {data['release_id']}\n"
        f"AI Recommendation: {data['ai_decision']}\n\n"
        f"Approve: {approve_link}\n"
        f"Reject : {reject_link}"
    )

    # Optional notifier only (no email)
    send_webhook(message)

    return jsonify({
        "approval_id": approval_id,
        "approve_url": approve_link,
        "reject_url": reject_link
    }), 200

@app.route("/approve/<approval_id>")
def approve(approval_id):
    approval = APPROVALS.get(approval_id)
    if not approval:
        return "Invalid approval ID", 404

    if approval["status"] != "PENDING":
        return f"Already {approval['status']}", 400

    approval["status"] = "APPROVED"
    approval["approved_at"] = datetime.utcnow().isoformat()

    rundeck_resume(approval["execution_id"])

    return "✅ Release APPROVED. You may close this page."

@app.route("/reject/<approval_id>")
def reject(approval_id):
    approval = APPROVALS.get(approval_id)
    if not approval:
        return "Invalid approval ID", 404

    if approval["status"] != "PENDING":
        return f"Already {approval['status']}", 400

    approval["status"] = "REJECTED"
    approval["rejected_at"] = datetime.utcnow().isoformat()

    rundeck_abort(approval["execution_id"])

    return "❌ Release REJECTED. Rollback triggered."

# =========================
# START
# =========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
