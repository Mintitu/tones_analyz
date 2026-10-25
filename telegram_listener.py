import os
import requests
from flask import Flask, request

app = Flask(__name__)

print("--- WEBHOOK SERVER INITIALIZAT SI PORNIT ---")

GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"
GH_PAT = os.environ.get("GH_PAT")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

@app.route("/", methods=["GET"])
def home():
    return "Botul este activ!", 200

# Această rută captează absolut orice adresă POST trimisă de Telegram (inclusiv cele cu colon sau /webhook)
@app.route("/webhook", methods=["POST"])
@app.route("/<path:subpath>", methods=["POST"])
def catch_all_webhook(subpath=""):
    print("--- CERERE PRIMITA DE LA TELEGRAM ---")
    update = request.get_json(silent=True)
    print(f"Update primit: {update}")
    
    if update and "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        print(f"Mesaj text primit: '{text}' de la chat_id: {chat_id}")
        
        if text == "/raport":
            send_telegram_message(chat_id, "🔄 Am primit comanda! Pornesc analiza ...")
            
            url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows/1.Analiza.yaml/dispatches"
            headers = {
                "Authorization": f"Bearer {GH_PAT}",
                "Accept": "application/vnd.github+json"
            }
            
            if GH_PAT:
                print(f"Verificare GH_PAT: EXISTA (lungime: {len(GH_PAT)})")
            else:
                print("Verificare GH_PAT: LIPSESTE COMPLET!")
            
            try:
                res = requests.post(url, json={"ref": "main"}, headers=headers)
                print(f"Raspuns GitHub API -> Status: {res.status_code} | Text: {res.text}")
                
                if res.status_code == 204:
                    send_telegram_message(chat_id, "✅ GitHub Actions a pornit cu succes!")
                else:
                    send_telegram_message(chat_id, f"❌ Eroare GitHub {res.status_code}: {res.text}")
            except Exception as e:
                error_msg = str(e)
                print(f"Eroare de conexiune / sistem: {error_msg}")
                send_telegram_message(chat_id, f"❌ Eroare de sistem: {error_msg}")
                
    return "OK", 200

def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
