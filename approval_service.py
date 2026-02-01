from flask import Flask, request, jsonify
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import uuid

app = Flask(__name__)

# =========================
# CONFIG (EDIT ONLY THIS)
# =========================

RUNDECK_URL = "http://127.0.0.1:4440"
RUNDECK_API_TOKEN = "CmUiZAfqVq5fLfGee2oOuznsYEnmuJhS"

SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587
SMTP_USER = "akash.raut@wissen.com"
SMTP_PASS = "ybfbdljblzphfnqd"
EMAIL_FROM = SMTP_USER
EMAIL_TO = ["akash.raut@wissen.com"]

# Optional: Teams / Slack webhook
WEBHOOK_URL = ""  # leave empty if not using

# In-memory store (OK for POC)
APPROVALS = {}

# =========================
# HELPERS
# =========================

def send_email(subject, body):
    msg = MIMEText(body, "plain")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(EMAIL_TO)

    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    server.quit()

def send_webhook(message):
    if not WEBHOOK_URL:
        return
    requests.post(WEBHOOK_URL, json={"text": message})

def rundeck_resume(execution_id):
    url = f"{RUNDECK_URL}/api/41/execution/{execution_id}/resume"
    headers = {"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN}
    requests.post(url, headers=headers)

def rundeck_abort(execution_id):
    url = f"{RUNDECK_URL}/api/41/execution/{execution_id}/abort"
    headers = {"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN}
    requests.post(url, headers=headers)

# =========================
# ROUTES
# =========================

@app.route("/request-approval", methods=["POST"])
def request_approval():
    data = request.json

    approval_id = str(uuid.uuid4())
    APPROVALS[approval_id] = {
        "status": "PENDING",
        "execution_id": data["execution_id"],
        "release_id": data["release_id"],
        "ai_decision": data["ai_decision"],
        "created": datetime.utcnow().isoformat()
    }

    approve_link = f"http://localhost:5000/approve/{approval_id}"
    reject_link = f"http://localhost:5000/reject/{approval_id}"

    message = f"""
Release: {data['release_id']}
AI Recommendation: {data['ai_decision']}

Approve: {approve_link}
Reject : {reject_link}
"""

    send_email(
        subject=f"Release Approval Required: {data['release_id']}",
        body=message
    )

    send_webhook(message)

    return jsonify({"approval_id": approval_id}), 200


@app.route("/approve/<approval_id>")
def approve(approval_id):
    approval = APPROVALS.get(approval_id)
    if not approval:
        return "Invalid approval ID", 404

    approval["status"] = "APPROVED"
    approval["approved_at"] = datetime.utcnow().isoformat()

    rundeck_resume(approval["execution_id"])

    return "✅ Release APPROVED. You may close this page."


@app.route("/reject/<approval_id>")
def reject(approval_id):
    approval = APPROVALS.get(approval_id)
    if not approval:
        return "Invalid approval ID", 404

    approval["status"] = "REJECTED"
    approval["rejected_at"] = datetime.utcnow().isoformat()

    rundeck_abort(approval["execution_id"])

    return "❌ Release REJECTED. Rollback triggered."


# =========================
# START
# =========================

if __name__ == "__main__":
    app.run(port=5000, debug=True)
