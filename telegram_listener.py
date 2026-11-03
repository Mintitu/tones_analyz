import os
import requests
from flask import Flask, request

app = Flask(__name__)

GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"

# Denumirile exacte ale workflow-urilor din .github/workflows/
WORKFLOW_WEEKLY = "2.Weekly.yaml"           # Declanșat de /week
DIVIDENDE_WORKFLOW_FILE = "3.Dividende.yaml" # Declanșat de /dividend
CAPITAL_WORKFLOW_FILE = "4.CapitalGain.yaml"   # Declanșat de /capital

GH_PAT = os.environ.get("GH_PAT", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://tones-analyz.onrender.com").rstrip("/")


def setup_webhook():
    if not TELEGRAM_BOT_TOKEN:
        print("Lipseste TELEGRAM_BOT_TOKEN in Render > Environment.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={"url": BASE_URL + "/", "drop_pending_updates": True},
            timeout=15,
        )
        print(f"setWebhook -> {BASE_URL}/ : HTTP {r.status_code}")
    except Exception:
        print("Eroare la setarea webhook-ului.")


def send_telegram_message(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except Exception:
        print("Nu am putut trimite mesajul pe Telegram.")


def trigger_github_workflow(chat_id, workflow_filename, starting_msg):
    send_telegram_message(chat_id, starting_msg)
    url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}"
        f"/actions/workflows/{workflow_filename}/dispatches"
    )
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        res = requests.post(url, json={"ref": "main"}, headers=headers, timeout=20)
        print(f"GitHub API status ({workflow_filename}): {res.status_code} - {res.text}")
        
        if res.status_code == 204:
            send_telegram_message(chat_id, f"✅ Acțiunea ({workflow_filename}) a pornit cu succes pe GitHub!")
        else:
            send_telegram_message(chat_id, f"❌ Eroare GitHub {res.status_code}: Verifică numele fișierului sau PAT-ul.")
    except Exception as e:
        print(f"Eroare conexiune GitHub: {e}")
        send_telegram_message(chat_id, "❌ Eroare la conectarea cu serverul GitHub.")


@app.route("/", methods=["GET", "POST"])
@app.route("/webhook", methods=["POST"])
def home():
    if request.method == "GET":
        return "Botul este activ!", 200

    data = request.get_json(silent=True) or {}
    message = data.get("message")
    if not message:
        return "OK", 200

    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    command = text.split()[0].split("@")[0] if text else ""

    if ALLOWED_CHAT_ID and str(chat_id) != ALLOWED_CHAT_ID:
        return "OK", 200  # Ignoră pe oricine altcineva

    if command == "/week":
        trigger_github_workflow(chat_id, WORKFLOW_WEEKLY, "Pornesc raportul săptămânal...")
    elif command == "/dividend":
        trigger_github_workflow(chat_id, DIVIDENDE_WORKFLOW_FILE, "Pornesc calculul dividendelor...")
    elif command == "/capital":
        trigger_github_workflow(chat_id, CAPITAL_WORKFLOW_FILE, "Pornesc calculul Capital Gain...")

    return "OK", 200


setup_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
