"""
Paco's Portfolio analysis: reads list of stock from a csv file, fetches live data from Yahoo Finance,
and prints a summary table with current prices, daily change, and Profit and Loss summary.

Requirements: pip3 install yfinance pandas tabulate

Usage:
    python3 paco_portfolio_analysis.py              # defaults to 6-month look-back
    python3 paco_portfolio_analysis.py -p 1y        # use a 1-year look-back instead
    python3 paco_portfolio_analysis.py --help       # show all available options
"""

# ------- library imports
import os
import requests
import argparse       # used to parse command-line arguments (e.g. -p 1y)
import sys            # used to exit the program with an error message when needed
import warnings       # used to silence deprecation messages from third-party libraries
from pathlib import Path      # used to work with file paths
from datetime import datetime # used for printing the current date/time in the report header

import pandas as pd           # used to read the csv file and data analysis
import yfinance as yf         # downloads live and historical stock data from Yahoo Finance
from tabulate import tabulate # formats the output as a user-friendly table

# hide deprecation warnings that come from the yfinance library
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


# ------- Configuration

CSV_FILE = Path(__file__).parent / "paco_portfolio_20260517.csv"

PERIOD_LABELS = {
    "1mo": "1 Month", "3mo": "3 Months", "6mo": "6 Months",
    "1y": "1 Year", "2y": "2 Years", "5y": "5 Years", "ytd": "Year-to-Date",
}

CLR_RED    = "\033[91m"
CLR_GREEN  = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_RESET  = "\033[0m"


# ------- Command-line argument parsing

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


# ------- csv loading
def load_holdings(path: Path) -> pd.DataFrame:
    df_raw = pd.read_csv(path)
    
    # Verificăm dacă fișierul este un jurnal de tranzacții (conține coloanele Ticker și Type)
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
        # Format clasic de dețineri
        df = pd.read_csv(path, usecols=["Symbol", "Purchase Price", "Quantity"])
        df.columns = ["symbol", "purchase_price", "quantity"]
        return df


# ------- fetching data from Yahoo Finance
def fetch_quote(ticker_symbol: str, period: str) -> dict:
    t = yf.Ticker(ticker_symbol)
    info = t.info
    fast = t.fast_info
    hist = t.history(period=period)

    current_price = fast.last_price or info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = fast.previous_close or info.get("previousClose") or info.get("regularMarketPreviousClose")

    daily_chg = (current_price - prev_close) if (current_price and prev_close) else None
    daily_chg_pct = (daily_chg / prev_close * 100) if daily_chg is not None else None

    period_high = float(hist["High"].max()) if not hist.empty else None
    period_low = float(hist["Low"].min()) if not hist.empty else None

    period_start = float(hist["Close"].iloc[0]) if not hist.empty else None
    period_ret = ((current_price - period_start) / period_start * 100) if (current_price and period_start) else None

    raw_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
    dividend_yield = raw_yield if raw_yield else None

    return {
        "name": (info.get("shortName") or info.get("longName") or "")[:28],
        "current_price": current_price,
        "prev_close": prev_close,
        "daily_chg": daily_chg,
        "daily_chg_pct": daily_chg_pct,
        "period_high": period_high,
        "period_low": period_low,
        "period_ret": period_ret,
        "dividend_yield": dividend_yield,
        "currency": info.get("currency", ""),
    }


# ------- Period position helper
def week52_position(current, low, high) -> float | None:
    if None in (current, low, high) or high == low:
        return None
    return (current - low) / (high - low)


# ------- Strength label
def strength_label(pos52: float | None) -> str:
    if pos52 is None:
        return "  N/A"
    if pos52 >= 0.60:
        return "Strong"
    if pos52 <= 0.35:
        return "  Weak"
    return "Neutral"


# ------- Trading signal
def signal_label(gain_pct: float | None, pos52: float | None) -> str:
    if gain_pct is None or pos52 is None:
        return "    N/A"
    if gain_pct < -20:
        return "   Sell"
    if gain_pct < 0 and pos52 < 0.35:
        return "   Sell"
    if gain_pct > 30 and pos52 >= 0.70:
        return "Buy More"
    return "    Keep"


# ------- Output table builder
def build_table(holdings: pd.DataFrame, period: str) -> tuple[list[list], float, float]:
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
            print(f"  WARNING: could not fetch {symbol}: {e}")
            q = {k: None for k in ["name", "current_price", "prev_close", "daily_chg",
                                    "daily_chg_pct", "period_high", "period_low", "period_ret",
                                    "dividend_yield", "currency"]}

        cur = q["current_price"]
        cost_basis = purchase_price * quantity
        cur_value = (cur * quantity) if cur else None
        gain = (cur_value - cost_basis) if cur_value is not None else None
        gain_pct = (gain / cost_basis * 100) if (gain is not None and cost_basis) else None

        total_cost += cost_basis
        if cur_value is not None:
            total_value += cur_value

        pos52 = week52_position(cur, q["period_low"], q["period_high"])

        def fmt_price(v):
            return f"{v:>8.3f}" if v is not None else "       N/A"

        def fmt_pct(v, sign=True):
            if v is None:
                return "   N/A"
            prefix = "+" if (sign and v >= 0) else ""
            return f"{prefix}{v:.2f}%"

        def fmt_money(v):
            return f"{v:>9.2f}" if v is not None else "       N/A"

        div = q["dividend_yield"]
        div_cell = f"{div:.2f}%" if div else "    —"

        rows.append([
            symbol,
            q["name"],
            fmt_price(cur),
            fmt_pct(q["daily_chg_pct"]),
            fmt_pct(q["period_ret"]),
            fmt_price(q["period_high"]),
            fmt_price(q["period_low"]),
            f"{quantity:.0f}",
            fmt_price(purchase_price),
            fmt_money(cur_value),
            fmt_money(gain),
            div_cell,
            strength_label(pos52),
            signal_label(gain_pct, pos52),
        ])

    return rows, total_cost, total_value


# ------- Entry point
def main():
    args = parse_args()
    period = args.period
    period_label = PERIOD_LABELS[period]

    if not CSV_FILE.exists():
        sys.exit(f"CSV not found: {CSV_FILE}")

    print(f"\nPortfolio Analysis  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Period: {period_label}")
    print("=" * 100)

    holdings = load_holdings(CSV_FILE)
    rows, total_cost, total_value = build_table(holdings, period)
    print(" " * 40)

    headers = [
        "Symbol", "Name", "Price", "Day%", "Pd Ret%",
        "Pd Hi", "Pd Lo",
        "Qty", "Avg Cost",
        "Cur Value", "Gain/Loss",
        "Div Yield", "Strength", "Signal",
    ]

    table = tabulate(rows, headers=headers, tablefmt="rounded_outline", stralign="right")
    table = table.replace("   Sell", f"{CLR_RED}   Sell{CLR_RESET}")
    table = table.replace("Buy More", f"{CLR_GREEN}Buy More{CLR_RESET}")
    table = table.replace("    Keep", f"{CLR_YELLOW}    Keep{CLR_RESET}")
    print(table)

    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0

    print(f"\n  Total Cost Basis : ${total_cost:>10.2f}")
    print(f"  Total Value      : ${total_value:>10.2f}")
    sign = "+" if total_gain >= 0 else ""
    print(f"  Total Gain/Loss  : {sign}${total_gain:>9.2f}  ({sign}{total_gain_pct:.2f}%)")
    print()

    # --- TRIMITERE PE TELEGRAM (Plasat corect în interiorul lui main) ---
    report_text = f"📊 *Paco Portfolio Analysis* — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    report_text += f"• Perioadă: {period_label}\n"
    report_text += f"• Cost Total: ${total_cost:,.2f}\n"
    report_text += f"• Valoare Curentă: ${total_value:,.2f}\n"
    report_text += f"• Profit/Loss: {sign}${total_gain:,.2f} ({sign}{total_gain_pct:.2f}%)\n"

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
            print("Mesajul a fost trimis cu succes pe Telegram!")
        else:
            print(f"Erore la trimiterea pe Telegram: {response.text}")
    else:
        print("Lipsește TELEGRAM_BOT_TOKEN sau TELEGRAM_CHAT_ID în variabilele de mediu.")


if __name__ == "__main__":
    main()
