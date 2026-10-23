import os
import requests
from flask import Flask, request

app = Flask(__name__)

GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"
GH_PAT = os.environ.get("GH_PAT")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    update = request.get_json()
    
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        
        if text == "/raport":
            # Trimite mesaj pe Telegram că a pornit
            send_telegram_message(chat_id, "🔄 Am primit comanda! Pornesc raportul pe GitHub...")
            
            # Declanșează GitHub Actions
            url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows/tones.yml/dispatches"
            headers = {
                "Authorization": f"Bearer {GH_PAT}",
                "Accept": "application/vnd.github+json"
            }
            res = requests.post(url, json={"ref": "main"}, headers=headers)
            
            if res.status_code == 204:
                send_telegram_message(chat_id, "✅ GitHub Actions a pornit cu succes!")
            else:
                send_telegram_message(chat_id, f"❌ Eroare: {res.text}")
                
    return "OK", 200

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
