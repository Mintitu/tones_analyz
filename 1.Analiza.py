"""
Analiza Portofoliu XTB - Citire directă din Excel & Salvare/Trimire Fișier Markdown pe Telegram
Modelat după arhitectura AI Financial Agents (virattt / TradingAgents / Free US Investment Agent)
"""

import os
import sys
import warnings
import argparse
import glob
from pathlib import Path
from datetime import datetime

import pandas as pd
import yfinance as yf
import requests

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

PERIOD_LABELS = {
    "1mo": "1 Month", "3mo": "3 Months", "6mo": "6 Months",
    "1y": "1 Year", "2y": "2 Years", "5y": "5 Years", "ytd": "Year-to-Date",
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portfolio analysis using Yahoo Finance data.")
    parser.add_argument(
        "-p", "--period", default="6mo", choices=list(PERIOD_LABELS),
        metavar="PERIOD", help="Historical period to analyse.",
    )
    return parser.parse_args()

def load_holdings_from_excel() -> pd.DataFrame:
    """Citește pozițiile deschise direct din fișierele Excel XTB din folder."""
    excel_files = glob.glob("USD_*.xlsx") + glob.glob("*.xlsx")
    positions = {}

    for file_path in excel_files:
        try:
            xls = pd.ExcelFile(file_path)
            for sheet in xls.sheet_names:
                if 'open' in sheet.lower():
                    df_raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
                    header_idx = None
                    for idx, row in df_raw.iterrows():
                        if 'Ticker' in row.values and ('Volume' in row.values or 'Instrument/Position' in row.values):
                            header_idx = idx
                            break
                    if header_idx is not None:
                        df = df_raw.iloc[header_idx + 1:].copy()
                        df.columns = df_raw.iloc[header_idx].values
                        df = df.loc[:, df.columns.notna()]
                        for _, row in df.iterrows():
                            cat = str(row.get('Category', '')).strip()
                            ticker_raw = str(row.get('Ticker', '')).strip()
                            if ticker_raw and ticker_raw != 'nan' and cat in ['STOCK', 'ETF']:
                                ticker = ticker_raw.replace('.US', '').replace('.UK', '')
                                try:
                                    volume = float(row.get('Volume', 0))
                                    open_price = float(row.get('Open price', 0))
                                except ValueError:
                                    volume, open_price = 0.0, 0.0
                                
                                if volume > 0 and open_price > 0:
                                    if ticker not in positions:
                                        positions[ticker] = {'shares': 0.0, 'total_cost': 0.0}
                                    positions[ticker]['shares'] += volume
                                    positions[ticker]['total_cost'] += volume * open_price
        except Exception as e:
            print(f"Eroare la citirea Excel-ului {file_path}: {e}")

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
    ev_ebitda = info.get("enterpriseToEbitda")
    roic = info.get("returnOnCapital") or info.get("returnOnEquity")
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    target_price = info.get("targetMeanPrice")

    return {
        "current_price": current_price, "gap_from_high": gap_from_high, "rsi": rsi,
        "ev_ebitda": ev_ebitda, "roic": roic, "trailing_pe": trailing_pe,
        "forward_pe": forward_pe, "target_price": target_price,
    }

def calculate_score_and_signal(
    gain_pct: float, 
    rsi: float | None, 
    gap: float | None, 
    roic: float | None, 
    forward_pe: float | None
) -> tuple[str, int, str]:
    """
    Sistem de decizie multi-agent inspirat din TradingAgents & virattt AI Agent Framework:
    🟢 STRONG BUY / BULLISH (Verde) - Oportunitate clară de cumpărare / Profit solid
    🟡 HOLD / NEUTRAL / ACCUMULATE (Galben) - Consolidare, Valoare Fair, Cumpărare treptată
    🟧 CAUTION / TAKE PROFIT (Portocaliu) - Supracumpărat moderat sau corecție ușoară
    🔴 RISK / BEARISH (Roșu) - Scădere critică sau supracumpărare extremă
    """
    score = 50

    # Ajustare Scor bazată pe Momentum & P&L
    if gain_pct > 0:
        score += min(25, int(gain_pct / 1.5))
    else:
        score -= min(25, int(abs(gain_pct) / 1.5))

    # Ajustare Tehnică (RSI)
    if rsi is not None:
        if rsi < 30:
            score += 25
        elif rsi < 40:
            score += 10
        elif rsi > 70:
            score -= 20

    # Ajustare Valuare & Fundamental
    if gap is not None and gap < -20:
        score += 15
    if roic is not None and roic > 0.15:
        score += 10
    if forward_pe is not None and forward_pe < 15:
        score += 10

    score = max(0, min(99, score))

    # Algoritm decizional cu integrare stări Neutru/Acumulare (🟡)
    if rsi is not None and rsi < 28 and gain_pct < 0:
        return "🟢", score, "Strong Buy (Supravândut)"
    elif gap is not None and gap < -30 and (rsi is None or rsi < 45):
        return "🟢", score, "Oportunitate Discount"
    elif gain_pct >= 20 and (rsi is None or rsi <= 72):
        return "🟢", score, "Profit Solid"
    elif gain_pct >= 5 and gain_pct < 20 and (rsi is None or rsi <= 65):
        return "🟢", score, "Trend Ascendent"
    
    # Stări Galbene (🟡) - Acumulare, consolidare, zona neutră
    elif rsi is not None and 40 <= rsi <= 55 and -5 <= gain_pct <= 5:
        return "🟡", score, "Consolidare / Neutral"
    elif gap is not None and -20 <= gap <= -10 and (rsi is None or rsi < 55):
        return "🟡", score, "Zone de Acumulare"
    elif gain_pct >= 0 and gain_pct < 5 and (rsi is None or rsi <= 60):
        return "🟡", score, "Stabil / Fair Value"
    elif gain_pct < 0 and gain_pct >= -5 and (rsi is None or rsi >= 40):
        return "🟡", score, "Corecție Ușoară"
    
    # Stări Portocalii (🟧) - Atenție / Rebalansare
    elif gain_pct < -5 and gain_pct >= -15:
        return "🟧", score, "Corecție Medie"
    elif rsi is not None and 70 <= rsi < 78:
        return "🟧", score, "Supracumpărat Mediu"
    
    # Stări Roșii (🔴) - Risc Sporit
    elif gain_pct < -15:
        return "🔴", score, "Scădere Critică"
    elif rsi is not None and rsi >= 78:
        return "🔴", score, "Supracumpărat Extrem"

    return "🟡", score, "Menținere (Hold)"

def send_telegram_document(token: str, chat_id: str, file_path: str, caption: str = ""):
    """Trimite fișierul Markdown ca document atasat pe Telegram."""
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(file_path, "rb") as doc:
            files = {"document": doc}
            data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "Markdown"
            }
            res = requests.post(url, data=data, files=files)
            if res.status_code == 200:
                print(" Documentul Markdown a fost trimis pe Telegram cu succes!")
            else:
                print(f" Eroare Telegram Document: {res.text}")
    except Exception as e:
        print(f" Eroare la trimitere document: {e}")

def main():
    args = parse_args()
    period = args.period

    holdings = load_holdings_from_excel()
    if holdings.empty:
        sys.exit("Eroare: Nu s-au găsit poziții în fișierele Excel XTB!")

    rows = []
    total_cost = 0.0
    total_value = 0.0

    for _, row in holdings.iterrows():
        symbol = row["symbol"]
        purchase_price = float(row["purchase_price"])
        quantity = float(row["quantity"])

        print(f"  Fetching {symbol}...")
        try:
            q = fetch_quote(symbol, period)
        except Exception as e:
            q = {"current_price": None, "gap_from_high": None, "rsi": None, "ev_ebitda": None, "roic": None, "trailing_pe": None, "forward_pe": None, "target_price": None}

        cur = q["current_price"]
        cost_basis = purchase_price * quantity
        cur_value = (cur * quantity) if cur else cost_basis
        gain = cur_value - cost_basis
        gain_pct = (gain / cost_basis * 100) if cost_basis else 0.0

        total_cost += cost_basis
        total_value += cur_value

        bullet, score, reason = calculate_score_and_signal(
            gain_pct, q["rsi"], q["gap_from_high"], q["roic"], q["forward_pe"]
        )

        rows.append({
            "symbol": symbol, "cur_price": cur, "gain_pct": gain_pct,
            "rsi": q["rsi"], "gap": q["gap_from_high"], "ev_ebitda": q["ev_ebitda"],
            "roic": q["roic"], "trailing_pe": q["trailing_pe"],
            "forward_pe": q["forward_pe"], "target_price": q["target_price"],
            "bullet": bullet, "score": score, "reason": reason,
        })

    total_gain = total_value - total_cost
    total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0
    sign = "+" if total_gain >= 0 else ""

    current_time = datetime.now().strftime('%d %b %Y %H:%M')
    
    # Generare conținut Markdown detaliat
    report_md = f"# 📈 Analiză Portofoliu XTB - AI Financial Agent\n\n"
    report_md += f"**Data generării:** `{current_time}`  \n"
    report_md += f"**P&L Total Portofoliu:** `{sign}{total_gain_pct:.2f}%`  \n"
    report_md += f"**Valoare Totală:** `${total_value:,.2f}`  \n\n"
    report_md += f"---\n\n"
    report_md += f"## 📊 Detalii Poziții & Semnale\n\n"

    for r in rows:
        p_pct = r['gain_pct']
        p_sign = "+" if p_pct >= 0 else ""
        price_str = f"{r['cur_price']:.2f}$" if r['cur_price'] is not None else "N/A"
        tp_str = f"TP: {r['target_price']:.1f}$" if r['target_price'] is not None else "TP: N/A"
        gap_str = f"Gap: {r['gap']:.0f}%" if r['gap'] is not None else "Gap: N/A"
        ev_str = f"EV/EBITDA: {r['ev_ebitda']:.1f}x" if r['ev_ebitda'] is not None else "EV/EBITDA: N/A"
        roic_val = r['roic'] * 100 if r['roic'] is not None else None
        roic_str = f"ROIC: {roic_val:.1f}%" if roic_val is not None else "ROIC: N/A"
        rsi_str = f"RSI: {r['rsi']:.0f}" if r['rsi'] is not None else "RSI: N/A"
        pe_val = r['trailing_pe']
        pe_str = f"P/E: {pe_val:.1f}" if pe_val is not None else "P/E: N/A"
        fwd_pe_str = f"Fwd P/E: {r['forward_pe']:.1f}" if r['forward_pe'] is not None else "Fwd P/E: N/A"

        report_md += f"### {r['bullet']} [{r['score']}/99] {r['symbol']} — {price_str} ({p_sign}{p_pct:.2f}%)\n"
        report_md += f"**Semnal AI:** `{r['reason']}`  \n"
        report_md += f"**Tehnic & Valuation:** `{tp_str}` | `{gap_str}` | `{rsi_str}`  \n"
        report_md += f"**Fundamente:** `{ev_str}` | `{roic_str}` | `{pe_str}` | `{fwd_pe_str}`  \n\n"

    # Salvare fișiere pe disc
    with open("Analiza.md", "w", encoding="utf-8") as f:
        f.write(report_md)

    with open("AnalizaTG.md", "w", encoding="utf-8") as f:
        f.write(report_md)

    print("Fișierele Analiza.md și AnalizaTG.md au fost salvate pe disc!")

    # Trimitere ca fișier atașat pe Telegram
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if token and chat_id:
        caption_msg = f"📈 *Raport Analiză Portofoliu XTB*\n🗓 `{current_time}`\n📊 P&L Total: `{sign}{total_gain_pct:.2f}%`"
        send_telegram_document(token, chat_id, "AnalizaTG.md", caption=caption_msg)

if __name__ == "__main__":
    main()