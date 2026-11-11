import os
import pandas as pd
import requests
import yfinance as yf

# 1. Obține lista ticker-elor S&P 500 de pe Wikipedia
url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
table = pd.read_html(url)
sp500_tickers = table[0]["Symbol"].tolist()

# Inlocuim '.' cu '-' pentru simboluri de tip BRK.B -> BRK-B (Yahoo Finance)
sp500_tickers = [ticker.replace(".", "-") for ticker in sp500_tickers]

# 2. Setează pragurile de scădere
threshold_24h = -7.0
threshold_48h = -15.0

alerts = []

print(f"Se analizează {len(sp500_tickers)} companii din S&P 500...")

for ticker in sp500_tickers:
  try:
    data = yf.Ticker(ticker).history(period="5d")

    if len(data) >= 3:
      price_now = data["Close"].iloc[-1]
      price_1d_ago = data["Close"].iloc[-2]
      price_2d_ago = data["Close"].iloc[-3]

      pct_24h = ((price_now - price_1d_ago) / price_1d_ago) * 100
      pct_48h = ((price_now - price_2d_ago) / price_2d_ago) * 100

      if pct_24h <= threshold_24h or pct_48h <= threshold_48h:
        alerts.append({
            "Ticker": ticker,
            "Preț Curent ($)": round(price_now, 2),
            "Scădere 24h (%)": round(pct_24h, 2),
            "Scădere 48h (%)": round(pct_48h, 2),
        })
  except Exception as e:
    continue

# 3. Generare fișier SP500-drop.md
md_content = "# 📉 Raport Scăderi S&P 500\n\n"
md_content += (
    f"_Ultima verificare: {pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')}_\n\n"
)

if alerts:
  df_alerts = pd.DataFrame(alerts)
  md_content += df_alerts.to_markdown(index=False)
else:
  md_content += (
      "✅ Nicio acțiune din S&P 500 nu a atins pragul de scădere de -7% (24h)"
      " sau -15% (48h)."
  )

with open("SP500-drop.md", "w", encoding="utf-8") as f:
  f.write(md_content)

print("Fișierul SP500-drop.md a fost generat cu succes.")

# 4. Trimitere alertă pe Telegram (opțional)
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

if telegram_token and telegram_chat_id and alerts:
  msg = f"📉 *ALERTĂ S&P 500 Drop*\n\nS-au găsit {len(alerts)} acțiuni cu scăderi mari!\nVerifică raportul `SP500-drop.md`."
  tg_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
  try:
    requests.post(
        tg_url, json={"chat_id": telegram_chat_id, "text": msg, "parse_mode": "Markdown"}
    )
    print("Notificarea Telegram a fost trimisă.")
  except Exception as e:
    print(f"Eroare la trimiterea pe Telegram: {e}")