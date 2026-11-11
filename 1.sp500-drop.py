"""
Alerta zilnica S&P 500: scaderi mari pe un ticker, in sedinte de bursa (nu in zile calendaristice).

- "24h"  = inchiderea de azi fata de inchiderea sedintei anterioare.
- "48h"  = inchiderea de azi fata de inchiderea de acum 2 sedinte.
Weekendul si sarbatorile nu sunt sedinte, deci luni "48h" = joi -> luni (vinerea e cuplata cu lunea).

Trimite mesaj pe Telegram DOAR daca gaseste ceva. Daca nu gaseste nimic, nu trimite nimic.
"""
import html
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# Setari (se pot schimba din workflow, la env:)
DROP_24H = float(os.getenv("DROP_24H", "7"))        # scadere mai mare de 7% fata de sedinta anterioara
DROP_48H = float(os.getenv("DROP_48H", "14"))       # scadere mai mare de 14% fata de acum 2 sedinte
ONLY_IF_SESSION_TODAY = os.getenv("ONLY_IF_SESSION_TODAY", "1") == "1"   # 0 = ruleaza oricand (test manual)
NOTIFY_ERRORS = os.getenv("NOTIFY_ERRORS", "1") == "1"                    # mesaj pe Telegram si la erori

CSV_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
DAYS_RO = ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"]


def now_ny():
    return datetime.now(ZoneInfo("America/New_York"))


def send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Lipsesc TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
        ok = r.ok and r.json().get("ok", False)
        if not ok:
            print(f"Telegram a refuzat mesajul (HTTP {r.status_code}).")
        return ok
    except Exception:
        print("Eroare de conexiune cu Telegram.")   # fara detalii: URL-ul contine tokenul
        return False


def fail(message):
    print(f"EROARE: {message}")
    if NOTIFY_ERRORS:
        send_telegram(f"⚠️ <b>Verificare S&amp;P 500 eșuată</b>\n{html.escape(message)}")
    sys.exit(1)


def get_constituents():
    """Intoarce {ticker_yahoo: nume}, din fisierul CSV public de pe GitHub."""
    try:
        df = pd.read_csv(CSV_URL)
        symbols, names = df["Symbol"].astype(str), df["Security"].astype(str)
    except Exception:
        fail("nu am putut prelua lista S&P 500 de pe GitHub.")
    return {sym.strip().replace(".", "-"): nm.strip() for sym, nm in zip(symbols, names)}


def download(tickers, batch=100):
    """Descarca inchiderile (ajustate si brute) in loturi; intoarce doua DataFrame-uri (date x ticker)."""
    adj_parts, raw_parts = [], []
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        data = None
        for attempt in range(2):
            try:
                data = yf.download(chunk, period="14d", interval="1d", auto_adjust=False,
                                   progress=False, threads=True)
                if data is not None and not data.empty:
                    break
            except Exception:
                pass
            time.sleep(5)
        if data is None or data.empty:
            continue
        adj, raw = data["Adj Close"], data["Close"]
        if isinstance(adj, pd.Series):          # lot cu un singur ticker
            adj, raw = adj.to_frame(chunk[0]), raw.to_frame(chunk[0])
        adj_parts.append(adj)
        raw_parts.append(raw)
    if not adj_parts:
        fail("Yahoo Finance nu a returnat date.")
    adj = pd.concat(adj_parts, axis=1).dropna(how="all")
    raw = pd.concat(raw_parts, axis=1).reindex(adj.index)
    return adj, raw


def fmt_day(ts):
    return f"{DAYS_RO[ts.weekday()]} {ts.date()}"


def main():
    names = get_constituents()
    tickers = list(names)
    print(f"Se analizeaza {len(tickers)} companii din S&P 500...")
    adj, raw = download(tickers)

    if len(adj) < 3:
        fail("mai putin de 3 sedinte in datele descarcate.")
    d0, d1, d2 = adj.index[-1], adj.index[-2], adj.index[-3]

    if ONLY_IF_SESSION_TODAY:
        now = now_ny()
        if d0.date() != now.date():
            print(f"Nu a fost sedinta azi (ultima sedinta: {d0.date()}): weekend sau sarbatoare. Nu verific nimic.")
            return
        if (now.hour, now.minute) < (16, 15):
            print("Piata din SUA e inca deschisa; verificarea se face dupa inchidere. Nu verific nimic.")
            return

    p0, p1, p2 = adj.loc[d0], adj.loc[d1], adj.loc[d2]
    valid = p0.notna() & p1.notna() & p2.notna()
    coverage = valid.sum() / len(tickers)
    print(f"Date valide pentru {valid.sum()}/{len(tickers)} tickere ({coverage:.0%}).")
    if coverage < 0.9:
        fail(f"date incomplete: doar {valid.sum()} din {len(tickers)} tickere au preturi valide.")

    pct24 = (p0 / p1 - 1) * 100
    pct48 = (p0 / p2 - 1) * 100
    hit = valid & ((pct24 < -DROP_24H) | (pct48 < -DROP_48H))

    if not hit.any():
        print("Nicio actiune nu a depasit pragurile. Nu trimit nimic.")
        return

    order = pd.concat([pct24[hit], pct48[hit]], axis=1).min(axis=1).sort_values().index
    header = (f"📉 <b>ALERTĂ S&amp;P 500</b> - {hit.sum()} acțiuni în scădere mare\n"
              f"Sesiune: {fmt_day(d0)}. 24h = față de {fmt_day(d1)}; 48h = față de {fmt_day(d2)}.\n"
              f"Praguri: 24h &lt; -{DROP_24H:g}%, 48h &lt; -{DROP_48H:g}% (⚠️ = prag depășit)\n")

    lines = []
    for t in order:
        w24 = "⚠️" if pct24[t] < -DROP_24H else ""
        w48 = "⚠️" if pct48[t] < -DROP_48H else ""
        name = names[t] if len(names[t]) <= 22 else names[t][:21] + "…"
        lines.append(f"• <b>{html.escape(t)}</b> {html.escape(name)} | ${raw.loc[d0, t]:.2f} | "
                     f"24h {pct24[t]:.1f}%{w24} | 48h {pct48[t]:.1f}%{w48}")

    # Jurnalul din GitHub Actions contine lista completa
    print("\n".join(lines))

    # UN SINGUR mesaj Telegram (limita 4096 de caractere): ordonat de la cea mai mare scadere;
    # daca nu incap toate (zi de prabusire), restul e doar numarat.
    limit = 3900
    message = header
    shown = 0
    for line in lines:
        if len(message) + len(line) + 1 > limit:
            break
        message += "\n" + line
        shown += 1
    rest = len(lines) - shown
    if rest:
        message += f"\n… și încă {rest} acțiuni (lista completă în logul rulării din GitHub Actions)."

    if not send_telegram(message):
        fail("alerta a fost găsită, dar trimiterea pe Telegram a eșuat.")
    print(f"Alerta trimisa pe Telegram: un singur mesaj, {shown} din {len(lines)} companii afisate.")


if __name__ == "__main__":
    main()
