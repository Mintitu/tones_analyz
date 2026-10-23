import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# DATELE TALE CORECTATE:
GITHUB_USER = "Mintitu"
REPO_NAME = "tones_analyz"  # <-- Pune aici numele repo-ului (ex: tones-portfolio)
GH_PAT = os.environ.get("GH_PAT")                # Tokenul tău personal GitHub

async def trigger_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Am pornit generarea raportului pe GitHub. Revin imediat cu datele!")

    # ATENȚIE: Aici am pus "tones.yml" conform fișierului tău de pe GitHub
    url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows/tones.yml/dispatches"
    
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json"
    }
    data = {
        "ref": "main" # sau "master", depinde ce branch principal ai pe GitHub
    }

    response = requests.post(url, json=data, headers=headers)

    if response.status_code == 204:
        await update.message.reply_text("✅ Comanda a fost trimisă cu succes către GitHub! Verifică Telegramul în câteva secunde.")
    else:
        await update.message.reply_text(f"❌ Eroare la pornirea GitHub Actions: {response.text}")

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Eroare: TELEGRAM_BOT_TOKEN nu este setat!")
        return

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("raport", trigger_report))
    
    print("Botul ascultă comenzi...")
    app.run_polling()

if __name__ == "__main__":
    main()
