import os
import requests
from flask import Flask, request

app = Flask(__name__)

GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"
GH_PAT = os.environ.get("GH_PAT")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Setează automat webhook-ul corect orientat spre /webhook la pornire
def setup_webhook():
    if TELEGRAM_BOT_TOKEN:
        render_url = "https://tones-analz.onrender.com/webhook"
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook?url={render_url}"
        try:
            r = requests.get(tg_url)
            print(f"Auto-set Webhook Response: {r.text}")
        except Exception as e:
            print(f"Eroare setare webhook: {e}")

@app.route("/", methods=["GET"])
def home():
    return "Botul este activ!", 200

# Rută curată, fixă, fără caractere speciale care să blocheze Flask
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    print(f"Cerere primită de la Telegram: {data}")
    
    if not data or "message" not in data:
        return "OK", 200
        
    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "")
    
    if text == "/raport":
        send_telegram_message(chat_id, "🔄 Pornesc analiza pe GitHub...")
        
        url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows/1.Analiza.yaml/dispatches"
        headers = {
            "Authorization": f"Bearer {GH_PAT}",
            "Accept": "application/vnd.github+json"
        }
        
        try:
            res = requests.post(url, json={"ref": "main"}, headers=headers)
            print(f"GitHub API Status: {res.status_code} | Text: {res.text}")
            
            if res.status_code == 204:
                send_telegram_message(chat_id, "✅ GitHub Actions a pornit cu succes!")
            else:
                send_telegram_message(chat_id, f"❌ Eroare GitHub {res.status_code}: {res.text}")
        except Exception as e:
            send_telegram_message(chat_id, f"❌ Eroare: {str(e)}")
            
    return "OK", 200

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
else:
    setup_webhook()
