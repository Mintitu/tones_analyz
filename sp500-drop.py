import pandas as pd
import yfinance as yf

# 1. Obține lista ticker-elor S&P 500
url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
table = pd.read_html(url)
sp500_tickers = table[0]["Symbol"].tolist()

# 2. Verifică scăderile semnificative
drop_threshold = -7.0  # Procent de scădere (-7%)

for ticker in sp500_tickers:
    try:
        data = yf.Ticker(ticker).history(period="2d")
        if len(data) >= 2:
            prev_close = data["Close"].iloc[-2]
            curr_price = data["Close"].iloc[-1]
            pct_change = ((curr_price - prev_close) / prev_close) * 100

            if pct_change <= drop_threshold:
                print(
                    f"ALERTĂ: {ticker} a scăzut cu {pct_change:.2f}% (Preț: ${curr_price:.2f})"
                )
                # Aici integrezi trimiterea pe Telegram sau Email
    except Exception as e:
        continue