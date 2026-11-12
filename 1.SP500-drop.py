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
WATCH_24H = float(os.getenv("WATCH_24H", "5"))      # semnal suplimentar: scadere mai mare de 5% pe ultima sesiune
ONLY_PROFITABLE = os.getenv("ONLY_PROFITABLE", "1") == "1"   # doar companii pe profit (net income > 0 sau P/E > 0)
SEND_IF_NONE = os.getenv("SEND_IF_NONE", "0") == "1"         # 1 = mesaj scurt si cand nu se gaseste nimic
MAX_INFO_CHECKS = 80                                          # peste atatea alerte nu mai verific profitul (ar dura prea mult)
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


def is_profitable(ticker):
    """True / False dupa regula: profit net pozitiv SAU P/E pozitiv. None daca datele nu pot fi aflate."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return None

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    net_income = num(info.get("netIncomeToCommon", info.get("netIncome")))
    pe = num(info.get("trailingPE"))
    if net_income is None and pe is None:
        return None
    return bool((net_income is not None and net_income > 0) or (pe is not None and pe > 0))


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
    strong = valid & ((pct24 < -DROP_24H) | (pct48 < -DROP_48H))      # semnal mare
    watch = valid & (pct24 < -WATCH_24H) & ~strong                    # semnal suplimentar (5% pe ultima sesiune)
    hit = strong | watch

    def none_found():
        print("Nicio actiune nu a depasit pragurile." + ("" if SEND_IF_NONE else " Nu trimit nimic."))
        if SEND_IF_NONE and not send_telegram(
                f"✅ S&amp;P 500 ({fmt_day(d0)}): nicio acțiune nu a depășit pragurile "
                f"(24h &lt; -{WATCH_24H:g}%/-{DROP_24H:g}%, 48h &lt; -{DROP_48H:g}%)."):
            fail("trimiterea mesajului pe Telegram a esuat.")

    if not hit.any():
        none_found()
        return

    # Ordine: intai semnalele mari (cea mai mare scadere prima), apoi cele de 5%
    worst = pd.concat([pct24[hit], pct48[hit]], axis=1).min(axis=1)
    order = list(worst[strong[hit]].sort_values().index) + list(worst[watch[hit]].sort_values().index)

    # Filtru de profitabilitate (doar pentru firmele care au intrat in alerta)
    excluded = []
    unknown = set()
    filter_applied = False
    if ONLY_PROFITABLE:
        if len(order) > MAX_INFO_CHECKS:
            print(f"{len(order)} alerte: prea multe pentru verificarea profitului; le afisez nefiltrate.")
        else:
            filter_applied = True
            kept = []
            for t in order:
                prof = is_profitable(t)
                if prof is False:
                    excluded.append(t)
                    continue
                if prof is None:
                    unknown.add(t)
                kept.append(t)
            order = kept

    if excluded:
        print("Excluse (fara profit): " + ", ".join(excluded))
    if not order:
        none_found()
        return

    n_strong = sum(1 for t in order if strong[t])
    n_watch = len(order) - n_strong
    header = (f"📉 <b>ALERTĂ S&amp;P 500</b>{' (doar companii pe profit)' if filter_applied else ''} - "
              f"{len(order)} acțiuni: 🔴 {n_strong} mari, 🟠 {n_watch} la peste {WATCH_24H:g}%\n"
              f"Sesiune: {fmt_day(d0)}. 24h = față de {fmt_day(d1)}; 48h = față de {fmt_day(d2)}.\n"
              f"🔴 = 24h &lt; -{DROP_24H:g}% sau 48h &lt; -{DROP_48H:g}%; 🟠 = 24h &lt; -{WATCH_24H:g}% (⚠️ = prag depășit)\n")
    if excluded:
        header += f"{len(excluded)} {'firmă' if len(excluded) == 1 else 'firme'} fără profit {'exclusă' if len(excluded) == 1 else 'excluse'}.\n"
    if ONLY_PROFITABLE and not filter_applied:
        header += "Filtrul de profit nu s-a aplicat (prea multe alerte).\n"

    lines = []
    for t in order:
        w24 = "⚠️" if pct24[t] < -min(DROP_24H, WATCH_24H) else ""
        w48 = "⚠️" if pct48[t] < -DROP_48H else ""
        name = names[t] if len(names[t]) <= 22 else names[t][:21] + "…"
        dot = "🔴" if strong[t] else "🟠"
        unk = " ❔profit" if t in unknown else ""
        lines.append(f"{dot} <b>{html.escape(t)}</b> {html.escape(name)} | ${raw.loc[d0, t]:.2f} | "
                     f"24h {pct24[t]:.1f}%{w24} | 48h {pct48[t]:.1f}%{w48}{unk}")

    # Jurnalul din GitHub Actions contine lista completa
    print("\n".join(lines))

    # UN SINGUR mesaj Telegram (limita 4096 de caractere); daca nu incap toate, restul e doar numarat.
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
    if unknown:
        message += "\n❔profit = nu s-a putut verifica profitabilitatea (date indisponibile)."

    if not send_telegram(message):
        fail("alerta a fost găsită, dar trimiterea pe Telegram a eșuat.")
    print(f"Alerta trimisa pe Telegram: un singur mesaj, {shown} din {len(lines)} companii afisate.")


if __name__ == "__main__":
    main()
