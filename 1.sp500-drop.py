"""
Alerta zilnica S&P 500: scaderi mari pe un ticker, in sedinte de bursa (nu in zile calendaristice).

- "24h"  = inchiderea de azi fata de inchiderea sedintei anterioare.
- "48h"  = inchiderea de azi fata de inchiderea de acum 2 sedinte.
Weekendul si sarbatorile nu sunt sedinte, deci luni "48h" = joi -> luni (vinerea e cuplata cu lunea).

Semnale pe randamente ajustate pentru dividende. Trimite rezumat si fara semnale.
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
RISE_24H = float(os.getenv("RISE_24H", "7"))
NOTIFY_NO_HITS = os.getenv("NOTIFY_NO_HITS", "1") == "1"
TEST_TELEGRAM = os.getenv("TEST_TELEGRAM", "0") == "1"

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
                data = yf.download(chunk, period="3mo", interval="1d", auto_adjust=False,
                                   progress=False, threads=True, repair=True)
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
    if TEST_TELEGRAM and not send_telegram("Test Telegram: scanarea S&P 500 a pornit."):
        print("Test Telegram esuat: verifica tokenul si chat_id in GitHub Secrets.")
        sys.exit(1)
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
            text = f"Scanare omisa: ultima data Yahoo {d0.date()}, data New York {now.date()}. Posibila zi fara sedinta sau date intarziate."
            print(text)
            if NOTIFY_NO_HITS and not send_telegram(html.escape(text)):
                sys.exit(1)
            return
        if (now.hour, now.minute) < (16, 15):
            print("Rulare programata inainte de 16:15 New York.")
            if NOTIFY_NO_HITS and not send_telegram("Scanare omisa: inainte de 16:15 New York."):
                sys.exit(1)
            return

    p0, p1, p2 = adj.loc[d0], adj.loc[d1], adj.loc[d2]
    valid = (p0.notna() & p1.notna() & p2.notna() & (p0 > 0) & (p1 > 0) & (p2 > 0)
             & raw.loc[d0].notna() & raw.loc[d1].notna() & raw.loc[d2].notna()
             & (raw.loc[d0] > 0) & (raw.loc[d1] > 0) & (raw.loc[d2] > 0))
    coverage = valid.sum() / len(tickers)
    print(f"Date valide pentru {valid.sum()}/{len(tickers)} tickere ({coverage:.0%}).")
    if coverage < 0.9:
        fail(f"date incomplete: doar {valid.sum()} din {len(tickers)} tickere au preturi valide.")

    pct24 = (p0 / p1 - 1) * 100
    pct48 = (p0 / p2 - 1) * 100
    raw24 = (raw.loc[d0] / raw.loc[d1] - 1) * 100
    raw48 = (raw.loc[d0] / raw.loc[d2] - 1) * 100
    rise = valid & (pct24 >= RISE_24H - 1e-9)
    drop1 = valid & (pct24 <= -DROP_24H + 1e-9)
    drop2 = valid & (pct48 <= -DROP_48H + 1e-9)
    hit = rise | drop1 | drop2
    price_only = valid & ~hit & ((raw24 <= -DROP_24H + 1e-9) | (raw48 <= -DROP_48H + 1e-9))

    from pathlib import Path
    out = Path("output-sp500")
    out.mkdir(exist_ok=True)
    audit = pd.DataFrame({"adjusted_1_session_pct": pct24,
                          "adjusted_2_sessions_pct": pct48,
                          "price_1_session_pct": raw24,
                          "price_2_sessions_pct": raw48,
                          "valid": valid, "alert": hit,
                          "price_only_drop_not_alerted": price_only})
    audit.index.name = "ticker"
    audit.to_csv(out / "scan.csv")

    if not hit.any():
        message = (f"S&amp;P 500 verificat: {d0.date()}. Date valide: {valid.sum()}/{len(tickers)}.\n"
                   f"Niciun prag atins pe randament ajustat: +{RISE_24H:g}% / o sedinta, "
                   f"-{DROP_24H:g}% / o sedinta sau -{DROP_48H:g}% / doua.\n"
                   f"Scaderi doar pe pret neconfirmate pe ajustat: {int(price_only.sum())}.\n"
                   "Ajustarile Yahoo pot contine erori sau intarzieri.")
        print(html.unescape(message))
        if NOTIFY_NO_HITS and not send_telegram(message):
            sys.exit(1)
        return

    order = pd.concat([pct24[hit].abs(), pct48[hit].abs()], axis=1).max(axis=1).sort_values(ascending=False).index
    header = (f"<b>ALERTA S&amp;P 500 - AJUSTAT DIVIDENDE</b>: {hit.sum()} simboluri\n"
              f"Sesiune {fmt_day(d0)}; referinte {fmt_day(d1)} / {fmt_day(d2)}.\n"
              f"Praguri ajustate: +{RISE_24H:g}% / o sedinta, -{DROP_24H:g}% / o sedinta, -{DROP_48H:g}% / doua.\n"
              "Pretul in dolari: Close. Semnale: Adj Close Yahoo.\n")
    lines = []
    for t in order:
        tags = []
        if rise[t]: tags.append("CRESTERE")
        if drop1[t]: tags.append("SCADERE 1S")
        if drop2[t]: tags.append("SCADERE 2S")
        name = names[t][:24]
        lines.append(f"<b>{html.escape(t)}</b> {html.escape(name)} | ${raw.loc[d0,t]:.2f} | "
                     f"ajustat 1S {pct24[t]:+.2f}%, 2S {pct48[t]:+.2f}% | "
                     f"pret 1S {raw24[t]:+.2f}% | {', '.join(tags)}")

    # Jurnalul din GitHub Actions contine lista completa
    print("\n".join(lines))

    # Un singur mesaj; ordonare dupa magnitudinea miscarii ajustate;
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
