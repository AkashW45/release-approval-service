from flask import Flask, request, jsonify, render_template_string
from datetime import datetime
import requests
import os
import hmac
import hashlib
import base64
import json

app = Flask(__name__)

# ================= CONFIG =================

RUNDECK_URL = os.getenv("RUNDECK_URL", "http://127.0.0.1:4440")
RUNDECK_API_TOKEN = os.getenv("RUNDECK_API_TOKEN", "CmUiZAfqVq5fLfGee2oOuznsYEnmuJhS")
SIGNING_SECRET = os.getenv("SIGNING_SECRET", "super-secret-key")

# ================= HELPERS =================

def sign_payload(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(SIGNING_SECRET.encode(), raw.encode(), hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(sig + raw.encode()).decode()
    return token

def verify_token(token: str) -> dict:
    decoded = base64.urlsafe_b64decode(token.encode())
    sig = decoded[:32]
    raw = decoded[32:]
    expected = hmac.new(SIGNING_SECRET.encode(), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("Invalid signature")
    return json.loads(raw)

def rundeck_resume(exec_id):
    requests.post(
        f"{RUNDECK_URL}/api/41/execution/{exec_id}/resume",
        headers={"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN},
        timeout=5
    )

def rundeck_abort(exec_id):
    requests.post(
        f"{RUNDECK_URL}/api/41/execution/{exec_id}/abort",
        headers={"X-Rundeck-Auth-Token": RUNDECK_API_TOKEN},
        timeout=5
    )

# ================= ROUTES =================

@app.route("/")
def health():
    return "Approval Service running"

@app.route("/request-approval", methods=["POST"])
def request_approval():
    data = request.json
    payload = {
        "execution_id": data["execution_id"],
        "release_id": data["release_id"],
        "ai_decision": data["ai_decision"],
        "ts": datetime.utcnow().isoformat()
    }

    token = sign_payload(payload)
    approval_url = f"{request.host_url}approval/{token}"

    return jsonify({
        "approval_url": approval_url
    })

@app.route("/approval/<token>")
def approval_page(token):
    try:
        payload = verify_token(token)
    except Exception:
        return "Invalid or expired approval", 400

    return render_template_string("""
        <h2>🚨 Release Approval Required</h2>
        <p><b>Release:</b> {{r}}</p>
        <p><b>AI Recommendation:</b> {{d}}</p>

        <form method="post" action="/decision/{{t}}">
            <button name="action" value="CONTINUE">✅ Continue</button>
            <button name="action" value="PAUSE">⏸ Pause</button>
            <button name="action" value="ROLLBACK">❌ Rollback</button>
        </form>
    """, r=payload["release_id"], d=payload["ai_decision"], t=token)

@app.route("/decision/<token>", methods=["POST"])
def decision(token):
    try:
        payload = verify_token(token)
    except Exception:
        return "Invalid decision token", 400

    action = request.form.get("action")
    exec_id = payload["execution_id"]

    if action == "CONTINUE":
        rundeck_resume(exec_id)
        return "✅ Continued"

    if action == "ROLLBACK":
        rundeck_abort(exec_id)
        return "❌ Rolled back"

    return "⏸ Paused (no action taken)"

# ================= START =================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
