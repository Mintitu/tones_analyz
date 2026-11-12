import os
import pandas as pd
import requests
import yfinance as yf

# 1. Obținem lista S&P 500 direct din sursa CSV de pe GitHub
url = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv'
try:
  df_sp500 = pd.read_csv(url)
  sp500_tickers = (
      df_sp500['Symbol'].str.replace('.', '-', regex=False).tolist()
  )
except Exception as e:
  print(f'Eroare la preluarea listei: {e}')
  sp500_tickers = []

# 2. Setează pragurile de scădere
threshold_24h = -7.0  # Scădere de 7% în ultimele 24h (1 sesiune)
threshold_48h = -14.0  # Scădere de 15% în ultimele 48h (2 sesiuni)

alerts = []

if sp500_tickers:
  print(
      f'Se analizează {len(sp500_tickers)} companii din S&P 500 și se verifică'
      ' profitabilitatea...'
  )

  for ticker in sp500_tickers:
    try:
      stock = yf.Ticker(ticker)
      data = stock.history(period='5d')

      if len(data) >= 3:
        price_now = data['Close'].iloc[-1]
        price_1d_ago = data['Close'].iloc[-2]
        price_2d_ago = data['Close'].iloc[-3]

        pct_24h = ((price_now - price_1d_ago) / price_1d_ago) * 100
        pct_48h = ((price_now - price_2d_ago) / price_2d_ago) * 100

        # Verificăm dacă a atins pragul de scădere cerut de tine
        if pct_24h <= threshold_24h or pct_48h <= threshold_48h:
          # Verificare suplimentară de profitabilitate fundamentată (fundamental check)
          info = stock.info
          net_income = info.get(
              'netIncomeToCommon', info.get('netIncome', 0)
          )
          trailing_pe = info.get('trailingPE', None)

          # Considerăm companie "pe profit / sănătoasă" dacă are profit net pozitiv sau P/E pozitiv
          is_profitable = (net_income and net_income > 0) or (
              trailing_pe and trailing_pe > 0
          )

          if is_profitable:
            alerts.append({
                'Ticker': ticker,
                'Nume': info.get('shortName', ticker),
                'Preț': round(price_now, 2),
                '24h': round(pct_24h, 2),
                '48h': round(pct_48h, 2),
            })
    except Exception as e:
      continue
else:
  print('Nu există tickere de analizat.')

# 3. Construire mesaj pentru Telegram
current_time = pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d %H:%M UTC')

if alerts:
  msg = (
      f'📉 *ALERTĂ S&P 500 Drop (Companii pe Profit)* ({current_time})\n\nS-au'
      f' găsit *{len(alerts)}* acțiuni solide cu scăderi mari (potențial de'
      ' revenire):\n\n'
  )
  for item in alerts:
    msg += (
        f"• *{item['Ticker']}* ({item['Nume']}): ${item['Pre']} | 24h:"
        f" `{item['24h']}%` | 48h: `{item['48h']}%`\n"
    )
else:
  msg = (
      f'✅ *S&P 500 Daily Check* ({current_time})\n\nNicio companie solidă pe'
      ' profit nu a atins pragul de scădere de -7% (24h) sau -14% (48h).'
  )

# 4. Trimitere mesaj pe Telegram
telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

if telegram_token and telegram_chat_id:
  tg_url = f'https://api.telegram.org/bot{telegram_token}/sendMessage'
  try:
    response = requests.post(
        tg_url,
        json={
            'chat_id': telegram_chat_id,
            'text': msg,
            'parse_mode': 'Markdown',
        },
    )
    if response.status_code == 200:
      print('Notificarea Telegram a fost trimisă cu succes.')
    else:
      print(f'Eroare Telegram: {response.text}')
  except Exception as e:
    print(f'Eroare la trimiterea pe Telegram: {e}')
else:
  print('Lipsește tokenul sau chat ID-ul pentru Telegram.')
