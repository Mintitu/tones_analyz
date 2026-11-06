import os
import re
import requests
from flask import Flask, request

app = Flask(__name__)

GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"
WORKFLOW_RAPORT = "1.Analiza.yaml"      # EXACT numele fisierelor din .github/workflows/
WORKFLOW_EMAIL = "trimite_email.yaml"
EMAIL_IMPLICIT = "pining78@yahoo.com"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

GH_PAT = os.environ.get("GH_PAT", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://tones-analyz.onrender.com").rstrip("/")


def setup_webhook():
    """Seteaza webhook-ul DOAR daca nu e deja setat corect.
    Important: NU stergem mesajele in asteptare (drop_pending_updates), altfel comanda care a trezit
    serverul s-ar pierde la fiecare pornire."""
    if not TELEGRAM_BOT_TOKEN:
        print("Lipseste TELEGRAM_BOT_TOKEN in Render > Environment.")
        return
    wanted = BASE_URL + "/"
    try:
        info = requests.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=15).json()
        if info.get("ok") and info.get("result", {}).get("url") == wanted:
            print("Webhook deja setat corect; nu il schimb.")
            return
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={"url": wanted},
            timeout=15,
        )
        print(f"setWebhook -> {wanted} : HTTP {r.status_code} {r.json().get('description', '')}")
    except Exception:
        print("Eroare la verificarea/setarea webhook-ului (conexiune).")  # fara exceptie: contine tokenul


def send_telegram_message(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except Exception:
        print("Nu am putut trimite mesajul pe Telegram.")


def trigger_workflow(workflow_file, inputs=None):
    url = (
        f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}"
        f"/actions/workflows/{workflow_file}/dispatches"
    )
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {"ref": "main"}
    if inputs:
        body["inputs"] = inputs
    return requests.post(url, json=body, headers=headers, timeout=20)


def run_and_report(chat_id, workflow_file, ok_text, inputs=None):
    try:
        res = trigger_workflow(workflow_file, inputs)
        print(f"GitHub API ({workflow_file}) status: {res.status_code}")
        if res.status_code == 204:
            send_telegram_message(chat_id, ok_text)
        else:
            send_telegram_message(chat_id, f"Eroare GitHub {res.status_code}: {res.text[:300]}")
    except Exception:
        send_telegram_message(chat_id, "Eroare la conectarea cu GitHub.")


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
    parts = (message.get("text") or "").split()
    command = parts[0].split("@")[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else ""

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
        run_and_report(chat_id, WORKFLOW_RAPORT, "GitHub Actions a pornit. Raportul vine in cateva minute.")

    elif command == "/email":
        destinatar = arg or EMAIL_IMPLICIT
        if not EMAIL_RE.match(destinatar):
            send_telegram_message(chat_id, "Adresa de email nu este valida. Exemplu: /email nume@domeniu.com")
        else:
            send_telegram_message(chat_id, f"Trimit cele 3 fisiere pe email la {destinatar}...")
            run_and_report(chat_id, WORKFLOW_EMAIL,
                           "Workflow-ul de email a pornit. Emailul ajunge in cateva minute.",
                           inputs={"destinatar": destinatar})

    else:
        # Orice alt mesaj/comanda trezeste serverul si primeste confirmare
        send_telegram_message(chat_id, "Sunt treaz. Comenzi: /raport, /email [adresa]")

    return "OK", 200


setup_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
