import os
import re
from pathlib import Path

import requests
from flask import Flask, request

app = Flask(__name__)

GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"
EMAIL_IMPLICIT = "pining78@yahoo.com"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# comanda Telegram -> workflow GitHub.
#   files   = numele exacte incercate pe rand (.github/workflows/); 'keyword' = rezerva: daca niciun nume nu exista,
#             caut in lista de workflow-uri unul al carui nume de fisier contine cuvantul.
COMMANDS = {
    "signals":   {"files": ["1-Signals.yaml", "1-Signals.yml"], "keyword": "signals",
                  "desc": "Semnale swing de azi (/signals backtest, /signals all)"},
    "analiza":   {"files": ["1.Analiza.yaml", "1.Analiza.yml"], "keyword": "analiza",
                  "desc": "Analiza portofoliului"},
    "drop":      {"files": ["1.sp500-drop.yaml", "1.SP500-drop.yaml", "1.sp500-drop.yml", "1.SP500-drop.yml"],
                  "keyword": "drop", "desc": "Alerta scaderi mari S&P 500"},
    "week":      {"files": ["2.Weekly.yaml", "2.Weekly.yml"], "keyword": "weekly",
                  "desc": "Raportul saptamanal"},
    "dividende": {"files": ["3.Dividende.yaml", "3.Dividende.yml"], "keyword": "dividende",
                  "desc": "Raport dividende"},
    "capital":   {"files": ["4.CapitalGain.yaml", "4.CapitalGain.yml"], "keyword": "capitalgain",
                  "desc": "Raport capital gain"},
    "email":     {"files": ["trimite_email.yaml", "trimite_email.yml"], "keyword": "email",
                  "desc": "Trimite cele 3 fisiere pe email (/email adresa)"},
}
ALIASES = {"weekly": "week", "dividend": "dividende", "gain": "capital", "capitalgain": "capital",
           "capital_gain": "capital"}
SIGNALS_MODES = {"": "scan", "scan": "scan", "backtest": "backtest", "all": "both", "toate": "both", "both": "both"}

GH_PAT = os.environ.get("GH_PAT", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://tones-analyz.onrender.com").rstrip("/")


# ----------------------------------------------------------------------------- Telegram
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
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
                          json={"url": wanted}, timeout=15)
        print(f"setWebhook -> {wanted} : HTTP {r.status_code} {r.json().get('description', '')}")
    except Exception:
        print("Eroare la verificarea/setarea webhook-ului (conexiune).")  # fara exceptie: contine tokenul


def setup_commands():
    """Meniul de comenzi din Telegram (apare cand scrii '/')."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        commands = [{"command": k, "description": v["desc"][:250]} for k, v in COMMANDS.items()]
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands",
                          json={"commands": commands}, timeout=15)
        print(f"setMyCommands: HTTP {r.status_code}")
    except Exception:
        print("Eroare la setarea meniului de comenzi.")


def send_telegram_message(chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=15)
    except Exception:
        print("Nu am putut trimite mesajul pe Telegram.")


# ----------------------------------------------------------------------------- GitHub
def _headers():
    return {"Authorization": f"Bearer {GH_PAT}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def trigger_workflow(workflow, inputs=None):
    """workflow = nume de fisier (ex. 1-Signals.yaml) sau id numeric."""
    url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows/{workflow}/dispatches"
    body = {"ref": "main"}
    if inputs:
        body["inputs"] = inputs
    return requests.post(url, json=body, headers=_headers(), timeout=20)


def list_workflows():
    r = requests.get(f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows?per_page=100",
                     headers=_headers(), timeout=20)
    return r.json().get("workflows", []) if r.ok else None


def finish(chat_id, res, ok_text):
    if res.status_code == 204:
        send_telegram_message(chat_id, ok_text)
    else:
        extra = ""
        if res.status_code == 422:
            extra = "\n(Probabil workflow-ul nu are 'workflow_dispatch:' in fisierul .yaml.)"
        send_telegram_message(chat_id, f"Eroare GitHub {res.status_code}: {res.text[:300]}{extra}")


def run_command(chat_id, key, ok_text, inputs=None):
    """Porneste workflow-ul comenzii: intai numele exacte, apoi cautare dupa cuvant in lista de workflow-uri."""
    spec = COMMANDS[key]
    try:
        for name in spec["files"]:
            res = trigger_workflow(name, inputs)
            print(f"GitHub API ({name}) status: {res.status_code}")
            if res.status_code != 404:
                finish(chat_id, res, ok_text)
                return
        workflows = list_workflows()
        if workflows is None:
            send_telegram_message(chat_id, f"Nu gasesc workflow-ul pentru /{key} si nu pot lista workflow-urile "
                                           f"(verifica GH_PAT).")
            return
        matches = [w for w in workflows if spec["keyword"] in Path(w["path"]).name.lower()]
        if len(matches) == 1:
            finish(chat_id, trigger_workflow(matches[0]["id"], inputs), ok_text)
        elif matches:
            names = ", ".join(Path(w["path"]).name for w in matches)
            send_telegram_message(chat_id, f"Pentru /{key} se potrivesc mai multe workflow-uri: {names}. "
                                           f"Pune numele exact in COMMANDS din telegram_listener.py.")
        else:
            names = ", ".join(Path(w["path"]).name for w in workflows) or "niciunul"
            send_telegram_message(chat_id, f"Nu gasesc workflow pentru /{key}. Workflow-uri existente: {names}")
    except Exception:
        send_telegram_message(chat_id, "Eroare la conectarea cu GitHub.")


HELP = ("Sunt treaz. Comenzi:\n/signals [backtest|all] - semnale swing\n/analiza - analiza portofoliului\n"
        "/drop - scaderi mari S&P 500\n/week - raport saptamanal\n/dividende - raport dividende\n"
        "/capital - raport capital gain\n/email [adresa] - trimite fisierele pe email")


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
    raw = parts[0].split("@")[0].lstrip("/").lower() if parts and parts[0].startswith("/") else ""
    command = ALIASES.get(raw, raw)
    arg = parts[1] if len(parts) > 1 else ""

    if not ALLOWED_CHAT_ID:
        send_telegram_message(chat_id, f"Chat ID-ul tau este {chat_id}. Pune-l in Render > Environment "
                                       f"ca TELEGRAM_CHAT_ID.")
        return "OK", 200
    if str(chat_id) != ALLOWED_CHAT_ID:
        return "OK", 200  # ignora pe oricine altcineva

    if command == "signals":
        mode = SIGNALS_MODES.get(arg.lower())
        if mode is None:
            send_telegram_message(chat_id, "Foloseste: /signals (semnale de azi), /signals backtest, /signals all")
        else:
            what = {"scan": "semnalele de azi", "backtest": "backtestul", "both": "semnalele de azi si backtestul"}[mode]
            send_telegram_message(chat_id, f"Pornesc {what} pe GitHub...")
            run_command(chat_id, "signals", "GitHub Actions a pornit. Rezultatul vine in cateva minute.",
                        inputs={"mode": mode})

    elif command == "email":
        destinatar = arg or EMAIL_IMPLICIT
        if not EMAIL_RE.match(destinatar):
            send_telegram_message(chat_id, "Adresa de email nu este valida. Exemplu: /email nume@domeniu.com")
        else:
            send_telegram_message(chat_id, f"Trimit cele 3 fisiere pe email la {destinatar}...")
            run_command(chat_id, "email", "Workflow-ul de email a pornit. Emailul ajunge in cateva minute.",
                        inputs={"destinatar": destinatar})

    elif command in COMMANDS:                       # analiza, drop, week, dividende, capital
        send_telegram_message(chat_id, f"Pornesc /{command} pe GitHub...")
        run_command(chat_id, command, "GitHub Actions a pornit. Rezultatul vine in cateva minute.")

    else:
        # Orice alt mesaj/comanda trezeste serverul si primeste confirmare
        send_telegram_message(chat_id, HELP)

    return "OK", 200


setup_webhook()
setup_commands()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
