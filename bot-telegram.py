import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Datele tale GitHub
GITHUB_USER = "UTILIZATORUL_TAU"
REPO_NAME = "NUME_REPO"
GH_PAT = os.environ.get("GH_PAT") # Tokenul generat la Pasul 1

async def trigger_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Am pornit generarea raportului pe GitHub. Revin imediat cu datele!")

    # API-ul GitHub pentru a declanșa workflow-ul (workflow_dispatch)
    url = f"https://api.github.com/repos/{GITHUB_USER}/{REPO_NAME}/actions/workflows/main.yml/dispatches"
    
    headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json"
    }
    data = {
        "ref": "main" # sau branch-ul tău principal
    }

    response = requests.post(url, json=data, headers=headers)

    if response.status_code == 204:
        await update.message.reply_text("✅ Comanda a fost trimisă cu succes către GitHub! Verifică Telegramul în câteva secunde.")
    else:
        await update.message.reply_text(f"❌ Eroare la pornirea GitHub Actions: {response.text}")

def main():
    app = ApplicationBuilder().token(os.environ.get("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("raport", trigger_report))
    
    print("Botul ascultă comenzi...")
    app.run_polling()

if __name__ == "__main__":
    main()