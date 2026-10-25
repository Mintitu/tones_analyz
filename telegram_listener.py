import os
import requests
from flask import Flask, request

app = Flask(__name__)

GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"
WORKFLOW_FILE = "1.Analiza.yaml"   # trebuie sa fie EXACT numele fisierului din .github/workflows/

GH_PAT = os.environ.get("GH_PAT", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
# Doar acest chat are voie sa porneasca raportul (pune-l in Render > Environment)
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
# Render seteaza singur RENDER_EXTERNAL_URL; fallback = adresa serviciului tau
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
        print(f"setWebhook -> {BASE_URL}/ : HTTP {r.status_code} {r.json().get('description', '')}")
    except Exception:
        # nu afisam exceptia: contine URL-ul cu tokenul
        print("Eroare la setarea webhook-ului (conexiune).")


def send_telegram_message(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except Exception:
        print("Nu am putut trimite mesajul pe Telegram.")


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

    if not ALLOWED_CHAT_ID:
        send_telegram_message(
            chat_id,
            f"Chat ID-ul tau este {chat_id}. Pune-l in Render > Environment ca TELEGRAM_CHAT_ID.",
        )
        return "OK", 200

    if str(chat_id) != ALLOWED_CHAT_ID:
        return "OK", 200  # ignora pe oricine altcineva

    if command == "/raport":
        send_telegram_message(chat_id, "Pornesc analiza pe GitHub...")
        url = (
            f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}"
            f"/actions/workflows/{WORKFLOW_FILE}/dispatches"
        )
        headers = {
            "Authorization": f"Bearer {GH_PAT}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            res = requests.post(url, json={"ref": "main"}, headers=headers, timeout=20)
            print(f"GitHub API status: {res.status_code}")
            if res.status_code == 204:
                send_telegram_message(chat_id, "GitHub Actions a pornit. Raportul vine in cateva minute.")
            else:
                send_telegram_message(chat_id, f"Eroare GitHub {res.status_code}: {res.text[:300]}")
        except Exception:
            send_telegram_message(chat_id, "Eroare la conectarea cu GitHub.")

    return "OK", 200


setup_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
