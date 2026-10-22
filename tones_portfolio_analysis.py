"""
Tones's Portfolio analysis: Ultra-compact format for Telegram reporting
"""

import os
import sys
import warnings
import argparse
from pathlib import Path
from datetime import datetime

import pandas as pd
import yfinance as yf
import requests

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

CSV_FILE = Path(__file__).parent / "paco_portfolio_20260517.csv"

PERIOD_LABELS = {
    "1mo": "1 Month", "3mo": "3 Months", "6mo": "6 Months",
    "1y": "1 Year", "2y": "2 Years", "5y": "5 Years", "ytd": "Year-to-Date",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portfolio analysis using Yahoo Finance data.")
    parser.add_argument(
        "-p", "--period",
        default="6mo",
        choices=list(PERIOD_LABELS),
        metavar="PERIOD",
        help=f"Historical period to analyse. Choices: {', '.join(PERIOD_LABELS)}. Default: 6mo",
    )
    return parser.parse_args()


def load_holdings(path: Path) -> pd.DataFrame:
    df_raw = pd.read_csv(path)
    
    if "Ticker" in df_raw.columns and "Type" in df_raw.columns:
        positions = {}
        for _, row in df_raw.iterrows():
            ticker = str(row['Ticker']).strip()
            t_type = str(row['Type']).strip().lower()
            try:
                shares = float(row['Shares'])
                value = float(row['Value'])
            except (ValueError, TypeError):
                continue
            
            if ticker not in positions:
                positions[ticker] = {'shares': 0.0, 'total_cost': 0.0}
                
            if t_type == 'buy':
                positions[ticker]['shares'] += shares
                positions[ticker]['total_cost'] += value
            elif t_type == 'sell':
                current_shares = positions[ticker]['shares']
                if current_shares > 0:
                    avg_cost = positions[ticker]['total_cost'] / current_shares
                    positions[ticker]['shares'] -= shares
                    positions[ticker]['total_cost'] -= shares * avg_cost
                    if positions[ticker]['shares'] < 1e-6:
                        positions[ticker]['shares'] = 0.0
                        positions[ticker]['total_cost'] = 0.0
                        
        holdings = []
        for ticker, data in positions.items():
            if data['shares'] > 1e-6:
                avg_price = data['total_cost'] / data['shares']
                holdings.append({
                    'symbol': ticker,
                    'purchase_price': avg_price,
                    'quantity': data['shares']
                })
        return pd.DataFrame(holdings)
    else:
        df = pd.read_csv(path, usecols=["Symbol", "Purchase Price", "Quantity"])
        df.columns = ["symbol", "purchase_price", "quantity"]
        return df


def calculate_rsi(hist_df: pd.DataFrame, window: int = 14) -> float | None:
    if hist_df.empty or len(hist_df) < window + 1:
        return None
    delta = hist_df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))
    last_rsi = rsi_series.iloc[-1]
    return float(last_rsi) if not pd.isna(last_rsi) else None


def fetch_quote(ticker_symbol: str, period: str) -> dict:
    t = yf.Ticker(ticker_symbol)
    info = t.info
    fast = t.fast_info
    hist = t.history(period="1y")

    current_price = fast.last_price or info.get("currentPrice") or info.get("regularMarketPrice")
    period_high = float(hist["High"].max()) if not hist.empty else None
    gap_from_high = ((current_price - period_high) / period_high * 100) if (current_price and period_high) else None

    rsi = calculate_rsi(hist)

    return {
        "current_price": current_price,
        "gap_from_high": gap_from_high,
        "rsi": rsi,
    }


def generate_recommendation(gain_pct: float, rsi: float | None, gap: float | None) -> tuple[str, str]:
    if rsi is not None and rsi < 35 and gain_pct < 0:
        return "🟢 BUY", "Supravândut"
    elif rsi is not None and rsi > 70 and gain_pct > 20:
        return "🔴 TAKE PROFIT", "Supracumpărat"
    elif gain_pct < -20:
        return "🔴 CUT LOSS", "Scădere mare"
    elif gap is not None and gap < -25:
        return "🟢 STRONG BUY", "Discount din vârf"
    else:
        return "🟡 HOLD", "Neutru"


def main():
    args = parse_args()
    period = args.period

    if not CSV_FILE.exists():
        sys.exit(f"CSV not found: {CSV_FILE}")

    holdings = load_holdings(CSV_FILE)
    rows = []
    total_cost = 0.0
    total_value = 0.0

    for _, row in holdings.iterrows():
        symbol = row["symbol"]
        purchase_price = float(row["purchase_price"])
        quantity = float(row["quantity"])

        print(f"  Fetching {symbol}...", end="\r")
        try:
            q = fetch_quote(symbol, period)
        except Exception as e:
            q = {"current_price": None, "gap_from_high": None, "rsi": None}

        cur = q["current_price"]
        cost_basis = purchase_price * quantity
        cur_value = (cur * quantity) if cur else cost_basis
        gain = cur_value - cost_basis
        gain_pct = (gain / cost_basis * 100) if cost_basis else 0.0

        total_cost += cost_basis
        total_value += cur_value

        signal, reason = generate_recommendation(gain_pct, q["rsi"], q["gap_from_high"])

        rows.append({
            "symbol": symbol,
            "cur_price": cur,
            "gain_pct": gain_pct,
            "rsi": q["rsi"],
            "gap": q["gap_from_high"],
            "signal": signal,
        })

    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0
    sign = "+" if total_gain >= 0 else ""

    # --- FORMAT FĂRĂ VALOARE TOTALĂ ÎN TITLU ---
    report_text = f"📈 *TONES PORTFOLIO* — {datetime.now().strftime('%d %b %Y')}\n"
    report_text += f"📊 *P&L Total:* `{sign}${total_gain:,.2f}` (`{sign}{total_gain_pct:.2f}%`)\n"
    report_text += f"━━━━━━━━━━━━━━━━━━━━━━\n"

    for r in rows:
        p_pct = r['gain_pct']
        p_sign = "+" if p_pct >= 0 else ""
        rsi_str = f"RSI:{r['rsi']:.0f}" if r['rsi'] is not None else "RSI:-"
        gap_str = f"Gap:{r['gap']:.0f}%" if r['gap'] is not None else "Gap:-"
        price_str = f"${r['cur_price']:.2f}" if r['cur_price'] is not None else "N/A"

        report_text += f"▪️ *{r['symbol']}* ({p_sign}{p_pct:.1f}%) | {price_str} | {rsi_str}, {gap_str} | {r['signal']}\n"

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": report_text,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("Raportul compact a fost trimis pe Telegram!")
        else:
            print(f"Erore: {response.text}")


if __name__ == "__main__":
    main()
