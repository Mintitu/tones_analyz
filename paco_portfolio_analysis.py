"""
Tones's Portfolio analysis with Advanced Technical & Fundamental Metrics + Telegram Reporting
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
from tabulate import tabulate

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
    hist = t.history(period="1y") # Folosim 1 an pentru un RSI și Max/Min mai precis

    current_price = fast.last_price or info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = fast.previous_close or info.get("previousClose") or info.get("regularMarketPreviousClose")

    daily_chg = (current_price - prev_close) if (current_price and prev_close) else None
    daily_chg_pct = (daily_chg / prev_close * 100) if daily_chg is not None else None

    period_high = float(hist["High"].max()) if not hist.empty else None
    period_low = float(hist["Low"].min()) if not hist.empty else None

    # Calcul GAP față de maxim (Cât % mai are până la Vârf)
    gap_from_high = ((current_price - period_high) / period_high * 100) if (current_price and period_high) else None

    # Indicatori avansați
    rsi = calculate_rsi(hist)
    ev_ebitda = info.get("enterpriseToEbitda")

    return {
        "name": (info.get("shortName") or info.get("longName") or "")[:28],
        "current_price": current_price,
        "daily_chg_pct": daily_chg_pct,
        "period_high": period_high,
        "period_low": period_low,
        "gap_from_high": gap_from_high,
        "rsi": rsi,
        "ev_ebitda": ev_ebitda,
    }


def generate_recommendation(gain_pct: float, rsi: float | None, gap: float | None, ev_ebitda: float | None) -> tuple[str, str]:
    """
    Generează o recomandare inteligentă combinând P&L, RSI, GAP și EV/EBITDA.
    """
    reasons = []
    
    # Factor 1: RSI
    if rsi is not None:
        if rsi < 35:
            reasons.append("RSI Scăzut (Oportunitate)")
        elif rsi > 70:
            reasons.append("RSI Ridicat (Supracumpărat)")

    # Factor 2: GAP față de Maxim
    if gap is not None and gap < -20:
        reasons.append("Reducere >20% din Vârf")

    # Factor 3: P&L personal
    if gain_pct > 25:
        reasons.append("Profit excelent marcabil")
    elif gain_pct < -15:
        reasons.append("Pierdere semnificativă")

    # Decizie finală
    if rsi is not None and rsi < 35 and gain_pct < 0:
        return "🟢 BUY MORE", "Supravândut + Preț bun de acumulare"
    elif rsi is not None and rsi > 70 and gain_pct > 20:
        return "🔴 SELL / TAKE PROFIT", "Supracumpărat + Profit mare"
    elif gain_pct < -20 and (rsi is None or rsi > 50):
        return "🔴 SELL (CUT LOSS)", "Scădere sub pragul de risc"
    elif gap is not None and gap < -25 and gain_pct > -10:
        return "🟢 STRONG BUY", "Corecție mare din vârf (Discount)"
    else:
        return "🟡 HOLD", "Echilibrat / Monitorizează"


def build_table(holdings: pd.DataFrame, period: str):
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
            print(f"  WARNING: error fetching {symbol}: {e}")
            q = {k: None for k in ["name", "current_price", "daily_chg_pct", "period_high", "period_low", "gap_from_high", "rsi", "ev_ebitda"]}

        cur = q["current_price"]
        cost_basis = purchase_price * quantity
        cur_value = (cur * quantity) if cur else None
        gain = (cur_value - cost_basis) if cur_value is not None else None
        gain_pct = (gain / cost_basis * 100) if (gain is not None and cost_basis) else 0.0

        total_cost += cost_basis
        if cur_value is not None:
            total_value += cur_value

        rec_signal, rec_reason = generate_recommendation(gain_pct, q["rsi"], q["gap_from_high"], q["ev_ebitda"])

        rows.append({
            "symbol": symbol,
            "name": q["name"],
            "qty": quantity,
            "avg_price": purchase_price,
            "cur_price": cur,
            "gain_pct": gain_pct,
            "day_chg": q["daily_chg_pct"],
            "gap": q["gap_from_high"],
            "rsi": q["rsi"],
            "ev_ebitda": q["ev_ebitda"],
            "signal": rec_signal,
            "reason": rec_reason
        })

    return rows, total_cost, total_value


def main():
    args = parse_args()
    period = args.period
    period_label = PERIOD_LABELS[period]

    if not CSV_FILE.exists():
        sys.exit(f"CSV not found: {CSV_FILE}")

    holdings = load_holdings(CSV_FILE)
    rows, total_cost, total_value = build_table(holdings, period)

    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0
    sign = "+" if total_gain >= 0 else ""

    # --- FORMATARE MESAJ TELEGRAM SPANȚAT ȘI STRUCTURAT ---
    report_text = f"📈 *PACO PORTFOLIO REPORT* — {datetime.now().strftime('%d %b %Y %H:%M')}\n"
    report_text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    report_text += f"💰 *Cost Total Basis:* `${total_cost:,.2f}`\n"
    report_text += f"💎 *Valoare Portofoliu:* `${total_value:,.2f}`\n"
    report_text += f"📊 *P&L Total:* `{sign}${total_gain:,.2f}` (`{sign}{total_gain_pct:.2f}%`)\n"
    report_text += f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
    report_text += "📋 *ANALIZĂ PE FIECARE ACȚIUNE:*\n\n"

    for r in rows:
        sym = r['symbol']
        p_pct = r['gain_pct']
        p_sign = "+" if p_pct >= 0 else ""
        
        rsi_str = f"{r['rsi']:.1f}" if r['rsi'] is not None else "N/A"
        gap_str = f"{r['gap']:.1f}%" if r['gap'] is not None else "N/A"
        ev_str = f"{r['ev_ebitda']:.1f}x" if r['ev_ebitda'] is not None else "N/A"
        
        # Emoji semnal
        if "BUY" in r['signal']:
            icon = "🟢"
        elif "SELL" in r['signal']:
            icon = "🔴"
        else:
            icon = "🟡"

        # Card individual pentru fiecare acțiune
        report_text += f"{icon} *{sym}* ({r['qty']:.0f} buc)\n"
        report_text += f"├ 💵 Preț: `${r['cur_price']:.2f}` (Avg: `${r['avg_price']:.2f}`)\n"
        report_text += f"├ 📊 *P&L: {p_sign}{p_pct:.2f}%*\n"
        report_text += f"├ 📉 GAP Vârf: `{gap_str}` | RSI: `{rsi_str}` | EV/EBITDA: `{ev_str}`\n"
        report_text += f"└ 🎯 *Rec:* `{r['signal']}`\n"
        report_text += f"   _Motiv: {r['reason']}_\n\n"

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
            print("Raportul detaliat cu indicatori tehnici a fost trimis pe Telegram!")
        else:
            print(f"Erore la trimiterea pe Telegram: {response.text}")
    else:
        print("Lipsește TELEGRAM_BOT_TOKEN sau TELEGRAM_CHAT_ID din mediu.")


if __name__ == "__main__":
    main()
