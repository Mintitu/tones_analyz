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
import argparse       # used to parse command-line arguments (e.g. -p 1y)
import sys            # used to exit the program with an error message when needed
import warnings       # used to silence deprecation messages from third-party libraries (I need to find a better way to manage these)
from pathlib import Path      # used to work with file paths
from datetime import datetime # used for for printing the current date/time in the report header

import pandas as pd           # used to read the csv file and data analysis (calculating highs/lows, returns, etc.)
import yfinance as yf         # downloads live and historical stock data from Yahoo Finance
from tabulate import tabulate # formats the output as a user-friendly table

# here is where we hide deprecation warnings that come from the yfinance library
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)


# ------- Configuration

# Path to the csv file containing your portfolio holdings.
# For now, the script expects the file to be in the same folder as this script.
CSV_FILE = Path(__file__).parent / "paco_portfolio_20260517.csv"

# user-friendly labels for each analysis period.
# These correspond to the period codes that Yahoo Finance manages.
PERIOD_LABELS = {
    "1mo": "1 Month", "3mo": "3 Months", "6mo": "6 Months",
    "1y": "1 Year", "2y": "2 Years", "5y": "5 Years", "ytd": "Year-to-Date",
}

# ANSI escape codes for terminal colors — applied to the 'Signal' column
#   RED    → Sell      (action needed, stock is losing money or showing weakness)
#   GREEN  → Buy More  (positive momentum, keep the position or buy more)
#   YELLOW → Keep      (neutral, nothing urgent to do)
#   RESET  → restores the terminal's default color after each colored cell
CLR_RED    = "\033[91m"
CLR_GREEN  = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_RESET  = "\033[0m"


# ------- Command-line argument parsing

def parse_args() -> argparse.Namespace:
    # Defines the options that the user can pass when executing the script from the terminal.
    parser = argparse.ArgumentParser(description="Portfolio analysis using Yahoo Finance data.")
    parser.add_argument(
        "-p", "--period",
        default="6mo",                  # if the user doesn't indicate a period, the script uses 6 months as default
        choices=list(PERIOD_LABELS),
        metavar="PERIOD",
        help=f"Historical period to analyse. Choices: {', '.join(PERIOD_LABELS)}. Default: 6mo",
    )
    return parser.parse_args()


# ------- csv loading
def load_holdings(path: Path) -> pd.DataFrame:
    # reads only the indicated three columns we need from the csv file.
    df = pd.read_csv(path, usecols=["Symbol", "Purchase Price", "Quantity"])
    df.columns = ["symbol", "purchase_price", "quantity"]
    return df


# ------- fetching data from Yahoo Finance
def fetch_quote(ticker_symbol: str, period: str) -> dict:
    # Downloads both the latest quote and the historical price data for a single stock ticker.
    t = yf.Ticker(ticker_symbol)
    info = t.info        # general stock info: name, currency, 52-week range, etc.
    fast = t.fast_info   # snapshot: last price, previous close
    hist = t.history(period=period)  # daily OHLCV history for the period indicated (OHLCV stands for Open, High, Low, Close, Volume. )

    # Current price
    current_price = fast.last_price or info.get("currentPrice") or info.get("regularMarketPrice")

    # Previous closing price — used to calculate today's price change
    prev_close = fast.previous_close or info.get("previousClose") or info.get("regularMarketPreviousClose")

    # Today's price change in dollars and as a percentage
    daily_chg = (current_price - prev_close) if (current_price and prev_close) else None
    daily_chg_pct = (daily_chg / prev_close * 100) if daily_chg is not None else None

    # Pd Hi — the highest price the stock reached at any point during the period selected.
    # it is used to see how far the current price is from its more recent peak.
    period_high = float(hist["High"].max()) if not hist.empty else None

    # Pd Lo — the lowest price the stock hit during the period selected.
    # it is used to check risk and how much the stock has recovered from its recent bottom.
    period_low = float(hist["Low"].min()) if not hist.empty else None

    # Pd Ret% — how much the stock's price has changed from the first trading day of the
    # period to today, expressed as a percentage. For example, +66% means the stock was
    # 66% cheaper at the start of the period. All three values shift when you change the
    # period with -p (e.g. -p 1y shows a full year instead of the default 6 months).
    period_start = float(hist["Close"].iloc[0]) if not hist.empty else None
    period_ret = ((current_price - period_start) / period_start * 100) if (current_price and period_start) else None

    # Div Yield — the annual dividend payment expressed as a percentage of the current share
    # price. For example, 5.44% means the company pays roughly $5.44 per year for every
    # $100 worth of shares you own — money deposited into your account just for holding the
    # stock. A dash (—) in the table means the company does not currently pay a dividend.
    # Yahoo Finance already returns this value as a percentage (e.g. 4.46 means 4.46%), so no additional conversion is needed.
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
    # Returns a number between 0 and 1 that shows where the current price sits within the period's price range. 0 means at the lowest point, 1 means at the highest.
    # Example: 0.85 means the stock is near the top of its range — a sign of strength.
    if None in (current, low, high) or high == low:
        return None
    return (current - low) / (high - low)


# ------- Strength label
def strength_label(pos52: float | None) -> str:
    # Translates the 0–1 position score into a user-friendly strength label.
    #   Strong  → price is in the top 40% of its period range (≥ 60th percentile)
    #   Weak    → price is in the bottom 35% of its period range
    #   Neutral → price is somewhere in the middle
    if pos52 is None:
        return "  N/A"
    if pos52 >= 0.60:
        return "Strong"
    if pos52 <= 0.35:
        return "  Weak"
    return "Neutral"


# ------- Trading signal
def signal_label(gain_pct: float | None, pos52: float | None) -> str:
    # Suggests an action based on two combined factors:
    #   1. Your personal P&L (gain and losses): how much you're up or down vs. what you paid
    #   2. Market strength: where the stock sits in its recent price range
    #
    # Rules (suggested indicators):
    #   Sell     — you're down more than 20% from your purchase price, or you're losing money AND the stock is almost at its period low
    #   Buy More — you're already up more than 30% and the stock is near its period high
    #   Keep     — everything else; hold and monitor
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
    # Loops through every stock in the portfolio, fetches live data, calculates gain and losses, and assembles one row per stock for the output table.
    rows = []
    total_cost = 0.0    # running sum of what was originally invested
    total_value = 0.0   # running sum of what the portfolio is worth today

    for _, row in holdings.iterrows():
        symbol = row["symbol"]
        purchase_price = float(row["purchase_price"])
        quantity = float(row["quantity"])

        # I like this. it is a live progress indicator while data from each stock is being downloaded. It overwrites the same line in the terminal 
        print(f"  Fetching {symbol}...", end="\r")
        try:
            q = fetch_quote(symbol, period)
        except Exception as e:
            # If Yahoo Finance can't find the ticker, fill the row with N/A instead of giving an error and breaking the script
            print(f"  WARNING: could not fetch {symbol}: {e}")
            q = {k: None for k in ["name", "current_price", "prev_close", "daily_chg",
                                    "daily_chg_pct", "period_high", "period_low", "period_ret",
                                    "dividend_yield", "currency"]}

        # ------- Gain and Losses (P&L) calculations
        cur = q["current_price"]
        cost_basis = purchase_price * quantity          # total amount originally invested
        cur_value = (cur * quantity) if cur else None   # what those shares are worth today
        gain = (cur_value - cost_basis) if cur_value is not None else None          # dollar gain/loss
        gain_pct = (gain / cost_basis * 100) if (gain is not None and cost_basis) else None  # % gain/loss

        total_cost += cost_basis
        if cur_value is not None:
            total_value += cur_value

        # Position score used by strength_label() and signal_label()
        pos52 = week52_position(cur, q["period_low"], q["period_high"])

        # ------- FFunctions to format cell values for display in the table
        def fmt_price(v):
            return f"{v:>8.3f}" if v is not None else "       N/A"

        def fmt_pct(v, sign=True):
            if v is None:
                return "   N/A"
            prefix = "+" if (sign and v >= 0) else ""
            return f"{prefix}{v:.2f}%"

        def fmt_money(v):
            return f"{v:>9.2f}" if v is not None else "       N/A"

        # Format the dividend yield for display. If the company pays a dividend, show the
        # yield as a percentage (e.g. "5.44%"). If it doesn't pay dividends, show a dash (—).
        div = q["dividend_yield"]
        div_cell = f"{div:.2f}%" if div else "    —"

        # Each element in the list becomes one cell in the table row
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

    # Print the report header with today's date/time and the analysis period indicated
    print(f"\nPortfolio Analysis  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  Period: {period_label}")
    print("=" * 100)

    # Load the portfolio from the csv and fetch live data for every stock
    holdings = load_holdings(CSV_FILE)
    rows, total_cost, total_value = build_table(holdings, period)
    print(" " * 40)  # clear the last progress line printed by the fetching loop

    # Column headers — each corresponds to an element in the rows built above
    headers = [
        "Symbol", "Name", "Price", "Day%", "Pd Ret%",
        "Pd Hi", "Pd Lo",
        "Qty", "Avg Cost",
        "Cur Value", "Gain/Loss",
        "Div Yield", "Strength", "Signal",
    ]

    # Render the table as plain text first so tabulate calculates column widths correctly,
    # then inject ANSI colors into the 'Signal' words.
    table = tabulate(rows, headers=headers, tablefmt="rounded_outline", stralign="right")
    table = table.replace("   Sell", f"{CLR_RED}   Sell{CLR_RESET}")
    table = table.replace("Buy More", f"{CLR_GREEN}Buy More{CLR_RESET}")
    table = table.replace("    Keep", f"{CLR_YELLOW}    Keep{CLR_RESET}")
    print(table)

    # Print a portfolio-level summary below the table
    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0

    print(f"\n  Total Cost Basis : ${total_cost:>10.2f}")
    print(f"  Total Value      : ${total_value:>10.2f}")
    sign = "+" if total_gain >= 0 else ""
    print(f"  Total Gain/Loss  : {sign}${total_gain:>9.2f}  ({sign}{total_gain_pct:.2f}%)")
    print()


# Run main() only when this file is executed directly,
# not when it's imported as a module by another script.
if __name__ == "__main__":
    main()
