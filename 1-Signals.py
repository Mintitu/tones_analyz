"""
Swing pe portofoliul tau: tickerele si pozitiile vin din Excel-ul XTB. Un singur script, trei moduri (variabila MODE):

  scan      -> semnale de INTRARE si de IESIRE pe Telegram (un singur mesaj; zilnic vine doar daca e ceva de spus)
  backtest  -> testeaza aceleasi reguli pe istoric si trimite raportul pe Telegram
  both      -> ambele

Pornire: python 1-Signals.py (MODE din env) sau cu --backtest / --all. Din Telegram: /signals, /signals backtest, /signals all.

INTRARE: pret > SMA200 + MACD incrucisare in sus + RSI care a coborat recent (RSI min 5z <= RSI_DIP, acum < RSI_MAX_NOW).
IESIRE : (a) MACD incrucisare in jos dupa RSI ridicat (RSI max 5z >= RSI_PEAK, acum > RSI_MIN_NOW) sau
         (b) pretul inchide sub SMA200 (rupere de trend). Pozitiile in pierdere NU se propun spre vanzare.
"""
import glob
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output-signals"

# --- Setari (din workflow, la env:) -----------------------------------------------------------
MODE = os.getenv("MODE", "scan").strip().lower()          # scan | backtest | both
CONTEXT = os.getenv("BACKTEST_CONTEXT", "1") == "1"        # linie de istoric (backtest) la fiecare semnal de intrare
EXTRA_TICKERS = [t.strip().upper() for t in os.getenv("EXTRA_TICKERS", "").split(",") if t.strip()]  # de urmarit, fara sa le ai
PORTFOLIO_FILE = os.getenv("PORTFOLIO_FILE", "").strip() or "USD_*.xlsx"
RSI_DIP = float(os.getenv("RSI_DIP", "42"))              # intrare: RSI a coborat sub acest nivel in ultimele 5 sedinte
RSI_MAX_NOW = float(os.getenv("RSI_MAX_NOW", "60"))      # intrare: ... si acum e sub acest nivel
RSI_PEAK = float(os.getenv("RSI_PEAK", "58"))            # iesire: RSI a urcat peste acest nivel in ultimele 5 sedinte
RSI_MIN_NOW = float(os.getenv("RSI_MIN_NOW", "40"))      # iesire: ... si acum e peste acest nivel
MIN_POSITION_USD = float(os.getenv("MIN_POSITION_USD", "50"))   # sub aceasta valoare nu propun iesiri
BACKTEST_YEARS = int(os.getenv("BACKTEST_YEARS", "5"))
MAX_HOLD = int(os.getenv("MAX_HOLD", "20"))              # backtest, varianta mecanica: iesire dupa maximum N sedinte
COST_PCT = float(os.getenv("COST_PCT", "0.1"))           # backtest: cost per tranzactie (%), la intrare si la iesire
HORIZONS = (5, 10, 20)


def _opt_float(name):
    v = os.getenv(name, "").strip()
    return float(v) if v else None


Z_MAX = _opt_float("Z_MAX")            # optional (doar intrare): Z-score minim pe 5 zile <= valoare
VOL_MIN = _opt_float("VOL_MIN")        # optional (doar intrare): volum azi / media 20 sedinte >= valoare
ONLY_IF_SESSION_TODAY = os.getenv("ONLY_IF_SESSION_TODAY", "1") == "1"
SEND_IF_NONE = os.getenv("SEND_IF_NONE", "0") == "1"
NOTIFY_ERRORS = os.getenv("NOTIFY_ERRORS", "1") == "1"


def now_ny():
    return datetime.now(ZoneInfo("America/New_York"))


# ============================================================================= Telegram
def _creds():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return token, chat


def send_telegram(text):
    token, chat = _creds()
    if not token or not chat:
        print("Lipsesc TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (secrets din GitHub).")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                          timeout=20)
        if not (r.ok and r.json().get("ok")):
            print(f"Telegram a refuzat mesajul (HTTP {r.status_code}).")
            return False
        return True
    except Exception:
        print("Eroare de conexiune cu Telegram.")      # fara detalii: URL-ul contine tokenul
        return False


def send_files(paths, caption):
    """Imagini .png ca album (un singur mesaj), alte fisiere ca document."""
    token, chat = _creds()
    if not token or not chat:
        return False
    paths = [Path(p) for p in paths]
    images = [p for p in paths if p.suffix.lower() == ".png"]
    docs = [p for p in paths if p.suffix.lower() != ".png"]
    ok = True
    try:
        if len(images) == 1:
            with images[0].open("rb") as f:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                                  data={"chat_id": chat, "caption": caption}, files={"photo": f}, timeout=(15, 90))
            ok &= r.ok
        elif images:
            files, media, handles = {}, [], []
            for i, p in enumerate(images[:10]):
                fh = p.open("rb")
                handles.append(fh)
                files[f"photo{i}"] = (p.name, fh, "image/png")
                item = {"type": "photo", "media": f"attach://photo{i}"}
                if i == 0:
                    item["caption"] = caption
                media.append(item)
            try:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMediaGroup",
                                  data={"chat_id": chat, "media": json.dumps(media)}, files=files, timeout=(15, 120))
                ok &= r.ok
            finally:
                for fh in handles:
                    fh.close()
        for p in docs:
            mime = "text/markdown" if p.suffix.lower() == ".md" else "application/octet-stream"
            with p.open("rb") as f:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                                  data={"chat_id": chat}, files={"document": (p.name, f, mime)}, timeout=(15, 90))
            ok &= r.ok
    except Exception:
        print("Eroare la trimiterea fisierelor pe Telegram.")
        return False
    return ok


def fail(message):
    print(f"EROARE: {message}")
    if NOTIFY_ERRORS:
        send_telegram(f"⚠️ <b>Scanner swing eșuat</b>\n{html.escape(message)}")
    sys.exit(1)


# ============================================================================= portofoliu din Excel
def yahoo_symbol(xtb_ticker):
    """XTB -> Yahoo. Doar tickere americane (.US); restul sunt sarite (nu ghicesc simboluri)."""
    t = str(xtb_ticker).strip()
    if t.upper().endswith(".US"):
        return t[:-3].replace(".", "-").upper()
    return None


def _stamp(path):
    try:
        raw = pd.read_excel(path, sheet_name="Open Positions", header=None)
    except Exception:
        return None
    for _, row in raw.iterrows():
        if str(row.iloc[0]) == "Data as of report generated":
            return pd.to_datetime(row.iloc[1], errors="coerce")
    return pd.NaT


def _name_date(path):
    found = re.findall(r"\d{4}-\d{2}-\d{2}", Path(path).name)
    return pd.Timestamp(found[-1]) if found else pd.Timestamp.min


def load_positions():
    """DataFrame cu symbol, shares, avg_cost din cel mai recent Excel XTB; None daca nu gasesc niciunul."""
    valid = []
    for p in sorted(glob.glob(str(ROOT / PORTFOLIO_FILE))):
        st = _stamp(p)
        if st is not None:
            valid.append((st if pd.notna(st) else pd.Timestamp.min, _name_date(p), Path(p).name, p))
    if not valid:
        return None
    valid.sort(key=lambda t: (t[0], t[1], t[2]))
    path = valid[-1][3]
    print(f"Excel folosit: {Path(path).name}")

    raw = pd.read_excel(path, sheet_name="Open Positions", header=None)
    header = next((i for i, row in raw.iterrows() if "Ticker" in row.values and "Volume" in row.values), None)
    if header is None:
        return None
    df = pd.read_excel(path, sheet_name="Open Positions", header=header)
    df = df[df.Type.isna() & df.Ticker.notna()].copy()          # randurile "parinte", cate unul per instrument
    out, skipped = [], []
    for _, r in df.iterrows():
        sym = yahoo_symbol(r["Ticker"])
        if sym is None:
            skipped.append(str(r["Ticker"]))
            continue
        out.append({"symbol": sym, "shares": float(r["Volume"]), "avg_cost": float(r["Open price"])})
    if skipped:
        print("Sarite (nu sunt tickere .US): " + ", ".join(skipped))
    return pd.DataFrame(out)


# ============================================================================= date si indicatori
def download(ticker, period="1y"):
    """Istoric zilnic (cu o reincercare): Open/High/Low/Close/Volume ajustate. None daca Yahoo nu raspunde."""
    for attempt in range(2):
        try:
            df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
            if df is not None and not df.empty:
                return df.dropna(subset=["Close"])
        except Exception:
            pass
        time.sleep(3)
    return None


def indicator_frame(df):
    """Indicatorii pentru TOATE zilele (aceeasi logica la scanare si la backtest)."""
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    ind = pd.DataFrame(index=df.index)
    ind["close"] = close
    ind["sma200"] = close.rolling(200).mean()

    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    ind["macd"] = macd
    ind["signal"] = macd.ewm(span=9, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = (100 - 100 / (1 + gain / loss)).where(loss != 0, 100.0).where(gain.notna())
    ind["rsi"] = rsi
    ind["rsi_min5"] = rsi.rolling(5).min()
    ind["rsi_max5"] = rsi.rolling(5).max()

    z = (close - close.rolling(20).mean()) / close.rolling(20).std()
    ind["z"] = z
    ind["z_min5"] = z.rolling(5).min()

    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    ind["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    avg20 = vol.rolling(20).mean().shift(1)                      # media celor 20 de sedinte dinaintea zilei
    ind["vol_ratio"] = (vol / avg20).where(avg20 > 0)
    return ind


def entry_flags(ind):
    macd_up = (ind["macd"].shift(1) <= ind["signal"].shift(1)) & (ind["macd"] > ind["signal"])
    f = (ind["close"] > ind["sma200"]) & macd_up & (ind["rsi_min5"] <= RSI_DIP) & (ind["rsi"] < RSI_MAX_NOW)
    if Z_MAX is not None:
        f &= ind["z_min5"] <= Z_MAX
    if VOL_MIN is not None:
        f &= ind["vol_ratio"] >= VOL_MIN
    return f.fillna(False)


def exit_flags(ind):
    """Doua feluri de iesire: momentum (MACD in jos dupa RSI ridicat) si rupere de trend (sub SMA200)."""
    macd_down = (ind["macd"].shift(1) >= ind["signal"].shift(1)) & (ind["macd"] < ind["signal"])
    momentum = (macd_down & (ind["rsi_max5"] >= RSI_PEAK) & (ind["rsi"] > RSI_MIN_NOW)).fillna(False)
    broke = ((ind["close"] < ind["sma200"]) & (ind["close"].shift(1) >= ind["sma200"].shift(1))).fillna(False)
    return momentum, broke


# ============================================================================= scanare zilnica
def market_gate():
    df = download("SPY", "1mo")
    if df is None:
        fail("nu am putut verifica sesiunea de bursa (SPY indisponibil).")
    last_date = pd.Timestamp(df.index[-1]).date()
    now = now_ny()
    if last_date != now.date():
        print(f"Nu a fost sedinta azi (ultima sedinta: {last_date}). Nu scanez.")
        return False
    if (now.hour, now.minute) < (16, 15):
        print("Piata din SUA e inca deschisa; scanez dupa inchidere. Nu scanez.")
        return False
    return True


def entry_text(t, r):
    stop = r["close"] - 2 * r["atr"]
    vol = f" | volum {r['vol_ratio']:.1f}x media" if pd.notna(r["vol_ratio"]) else ""
    return (f"🟢 <b>{t}</b> — ${r['close']:.2f} (SMA200: ${r['sma200']:.2f})\n"
            f"   • RSI: <b>{r['rsi']:.1f}</b> (min 5z: {r['rsi_min5']:.1f}) | Z-Score: {r['z']:.2f}{vol}\n"
            f"   • MACD: {r['macd']:.3f} față de semnal {r['signal']:.3f} (încrucișare în sus)\n"
            f"   • Stop orientativ (2×ATR): ${stop:.2f} ({(stop / r['close'] - 1) * 100:.1f}%)")


def entry_context(t):
    """O linie de istoric pentru tickerul cu semnal: cum au mers semnalele de acelasi fel pe acest ticker (backtest)."""
    if not CONTEXT:
        return ""
    try:
        df = download(t, f"{BACKTEST_YEARS + 1}y")
        if df is None or len(df) < 260:
            return ""
        r = backtest_ticker(df)
        ev, base = r["events"][10], r["base"][10]
        if r["signals"] == 0 or len(ev) == 0 or len(base) == 0:
            return ""
        small = " (eșantion mic)" if len(ev) < 5 else ""
        return (f"\n   • Istoric {BACKTEST_YEARS}a pe {t}: {r['signals']} semnale; după 10 ședințe ret. mediu "
                f"{ev.mean() * 100:+.1f}% (bază: {base.mean() * 100:+.1f}%), {(ev > 0).mean() * 100:.0f}% pozitive{small}")
    except Exception:
        return ""


def exit_reasons(r, momentum, broke):
    reasons = []
    if momentum:
        reasons.append(f"MACD a încrucișat în jos după RSI ridicat (max 5z: {r['rsi_max5']:.0f}, acum {r['rsi']:.0f})")
    if broke:
        reasons.append(f"prețul a închis sub SMA200 (${r['sma200']:.2f})")
    return "; ".join(reasons)


def main_scan():
    positions = load_positions()
    holdings = {}
    if positions is not None and not positions.empty:
        holdings = {r.symbol: (r.shares, r.avg_cost) for r in positions.itertuples()}
    universe = list(dict.fromkeys(list(holdings) + EXTRA_TICKERS))
    if not universe:
        fail("nu am gasit Excel-ul cu pozitiile (PORTFOLIO_FILE) si nici EXTRA_TICKERS; fara pozitii nu pot da semnale.")

    if ONLY_IF_SESSION_TODAY and not market_gate():
        return

    entries, exits, held_at_loss, errors = [], [], [], []
    for t in universe:
        try:
            df = download(t, "1y")
            if df is None:
                errors.append(t)
                print(f"Date indisponibile pentru {t}.")
                continue
            if len(df) < 210:
                print(f"{t}: istoric prea scurt ({len(df)} sedinte); sarit.")
                continue
            ind = indicator_frame(df)
            last = ind.iloc[-1]
            if pd.isna(last["sma200"]) or pd.isna(last["rsi"]):
                continue
            if entry_flags(ind).iloc[-1]:
                entries.append(entry_text(t, last) + entry_context(t))
            if t in holdings:
                shares, avg_cost = holdings[t]
                momentum, broke = exit_flags(ind)
                if (momentum.iloc[-1] or broke.iloc[-1]) and shares * last["close"] >= MIN_POSITION_USD:
                    pl = (last["close"] / avg_cost - 1) * 100
                    why = exit_reasons(last, momentum.iloc[-1], broke.iloc[-1])
                    if pl > 0:
                        exits.append(f"🔴 <b>{t}</b> — ${last['close']:.2f} | cost mediu ${avg_cost:.2f} | "
                                     f"profit <b>{pl:+.1f}%</b>\n   • {why}")
                    else:
                        held_at_loss.append(f"⚪ <b>{t}</b> — P/L {pl:+.1f}% | {why}")
        except Exception as e:
            errors.append(t)
            print(f"Eroare la {t}: {e.__class__.__name__}")

    if len(errors) > len(universe) / 2:
        fail(f"date indisponibile pentru {len(errors)} din {len(universe)} tickere.")

    if not (entries or exits or held_at_loss):
        print("Niciun semnal detectat azi.")
        if SEND_IF_NONE and not send_telegram("ℹ️ Scanare swing finalizată: niciun semnal azi."):
            fail("trimiterea mesajului pe Telegram a eșuat.")
        return

    parts = []
    if entries:
        parts.append("📈 <b>Semnale de INTRARE</b> (preț > SMA200 + MACD cross + RSI)\n\n" + "\n\n".join(entries))
    if exits:
        parts.append("📉 <b>Semnale de IEȘIRE</b> (poziții pe profit)\n\n" + "\n\n".join(exits))
    if held_at_loss:
        parts.append("⚪ <b>Ieșire tehnică, dar în pierdere</b> (nu vinzi la pierdere)\n\n" + "\n".join(held_at_loss))
    message = "\n\n".join(parts)
    if len(message) > 3900:
        message = message[:3900].rsplit("\n", 1)[0] + "\n… (lista continuă, vezi logul rulării)"
    if errors:
        message += f"\n\n⚠️ Date indisponibile pentru: {', '.join(errors)}"
    print(message)
    if not send_telegram(message):
        fail("semnalele au fost găsite, dar trimiterea pe Telegram a eșuat.")


# ============================================================================= backtest
def sim_mechanical(entry, exitf, openp, closep, max_hold, cost):
    """Intrare la deschiderea zilei urmatoare semnalului; iesire la deschiderea zilei de dupa semnalul de iesire
    sau dupa max_hold sedinte. O singura pozitie pe ticker."""
    n, trades, i = len(openp), [], 0
    while i < n - 1:
        if entry[i]:
            e = i + 1
            px_in = openp[e]
            d, exit_i = e, None
            while d < n - 1:
                if exitf[d] or (d - e + 1) >= max_hold:
                    exit_i = d + 1
                    break
                d += 1
            if exit_i is None:
                trades.append({"i": e, "ret": closep[-1] / px_in - 1 - cost, "days": n - 1 - e, "open": True,
                               "mae": float(np.min(closep[e:] / px_in - 1))})
                break
            trades.append({"i": e, "ret": openp[exit_i] / px_in - 1 - 2 * cost, "days": exit_i - e, "open": False,
                           "mae": float(np.min(closep[e:exit_i] / px_in - 1))})
            i = exit_i
            continue
        i += 1
    return trades


def sim_rule(entry, exitf, openp, closep, cost):
    """Regula ta: iesi doar la semnal de iesire SI doar daca pozitia e pe profit; nu exista stop sau limita de timp."""
    n, trades, i = len(openp), [], 0
    while i < n - 1:
        if entry[i]:
            e = i + 1
            px_in = openp[e]
            d, exit_i = e, None
            while d < n - 1:
                if exitf[d] and closep[d] > px_in:
                    exit_i = d + 1
                    break
                d += 1
            if exit_i is None:
                trades.append({"i": e, "ret": closep[-1] / px_in - 1 - cost, "days": n - 1 - e, "open": True,
                               "mae": float(np.min(closep[e:] / px_in - 1))})
                break
            trades.append({"i": e, "ret": openp[exit_i] / px_in - 1 - 2 * cost, "days": exit_i - e, "open": False,
                           "mae": float(np.min(closep[e:exit_i] / px_in - 1))})
            i = exit_i
            continue
        i += 1
    return trades


def fwd_returns(openp, closep, h):
    """Pentru fiecare zi-semnal i: cumperi la deschiderea i+1, privesti inchiderea dupa h sedinte (ziua i+h)."""
    n = len(openp)
    r = np.full(n, np.nan)
    if n > h:
        r[:n - h] = closep[h:] / openp[1:n - h + 1] - 1
    return r


def backtest_ticker(df):
    ind = indicator_frame(df)
    momentum, broke = exit_flags(ind)
    entry = entry_flags(ind).to_numpy()
    exitf = (momentum | broke).to_numpy()
    openp, closep = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
    valid = (ind["sma200"].notna() & ind["rsi"].notna()).to_numpy()
    cost = COST_PCT / 100
    entry = entry & valid
    res = {
        "signals": int(entry[:-1].sum()),
        "M": sim_mechanical(entry, exitf, openp, closep, MAX_HOLD, cost),
        "P": sim_rule(entry, exitf, openp, closep, cost),
        "dates": df.index, "valid_from": df.index[valid][0] if valid.any() else None,
        "events": {}, "base": {},
    }
    for h in HORIZONS:
        r = fwd_returns(openp, closep, h)
        res["events"][h] = r[entry & ~np.isnan(r)]
        res["base"][h] = r[valid & ~np.isnan(r)]
    res["close_last"] = closep[-1]
    return res


def _pct(x, nd=1, sign=False):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else format(x * 100, f"{'+' if sign else ''}.{nd}f")


def _stats(trades):
    closed = [t for t in trades if not t["open"]]
    opened = [t for t in trades if t["open"]]
    rets = np.array([t["ret"] for t in closed]) if closed else np.array([])
    return {
        "n": len(closed),
        "win": float((rets > 0).mean()) if len(rets) else None,
        "avg": float(rets.mean()) if len(rets) else None,
        "med": float(np.median(rets)) if len(rets) else None,
        "days": float(np.mean([t["days"] for t in closed])) if closed else None,
        "worst": float(rets.min()) if len(rets) else None,
        "mae_avg": float(np.mean([t["mae"] for t in trades])) if trades else None,
        "mae_worst": float(min(t["mae"] for t in trades)) if trades else None,
        "all_avg": float(np.mean([t["ret"] for t in trades])) if trades else None,
        "open_n": len(opened),
        "open_avg": float(np.mean([t["ret"] for t in opened])) if opened else None,
    }


def table_image(title, header, rows, widths, footnote, path, bold_last=2):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    bg, fg, grid = "#0f1720", "#e8edf2", "#2a3644"
    n = len(rows)
    fig, ax = plt.subplots(figsize=(14, 1.5 + 0.40 * n), facecolor=bg)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.88, bottom=0.12)
    ax.axis("off")
    tbl = ax.table(cellText=rows, colLabels=header, loc="upper center", cellLoc="center", colWidths=widths)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10.5)
    tbl.scale(1, 1.55)
    for (i, j), cell in tbl.get_celld().items():
        cell.set_edgecolor(grid)
        cell.get_text().set_color(fg)
        if i == 0:
            cell.set_facecolor("#1d2a38")
            cell.get_text().set_fontweight("bold")
        else:
            is_total = i > n - bold_last
            cell.set_facecolor("#1b2b3d" if is_total else (bg if i % 2 else "#141e29"))
            if is_total or j == 0:
                cell.get_text().set_fontweight("bold")
    fig.suptitle(title, color=fg, fontsize=13, fontweight="bold", x=0.012, ha="left")
    fig.text(0.012, 0.012, footnote, color="#8b98a5", fontsize=7.5, va="bottom")
    fig.savefig(path, dpi=130, facecolor=bg, bbox_inches="tight")
    plt.close(fig)


def main_backtest():
    OUT.mkdir(exist_ok=True)
    positions = load_positions()
    universe = list(dict.fromkeys(([] if positions is None else list(positions.symbol)) + EXTRA_TICKERS))
    if not universe:
        fail("backtest: nu am gasit Excel-ul cu pozitiile (PORTFOLIO_FILE) si nici EXTRA_TICKERS.")
    results, skipped = {}, []
    for t in universe:
        df = download(t, f"{BACKTEST_YEARS + 1}y")
        if df is None or len(df) < 260:
            skipped.append(t)
            continue
        results[t] = backtest_ticker(df)
        time.sleep(0.5)
    if not results:
        fail("backtest: nu am putut descarca istoric pentru niciun ticker.")

    # ---- tabelul 1: iesire mecanica + studiu de evenimente
    rows1, all_M, all_P = [], [], []
    pooled_ev = {h: [] for h in HORIZONS}
    pooled_base = {h: [] for h in HORIZONS}
    for t, r in results.items():
        s = _stats(r["M"])
        all_M += r["M"]
        all_P += r["P"]
        for h in HORIZONS:
            pooled_ev[h].append(r["events"][h])
            pooled_base[h].append(r["base"][h])
        ev = [_pct(float(np.mean(r["events"][h])) if len(r["events"][h]) else None, 1, True) for h in HORIZONS]
        rows1.append([t, r["signals"], s["n"], _pct(s["win"], 0), _pct(s["avg"], 1, True), _pct(s["med"], 1, True),
                      "n/a" if s["days"] is None else f"{s['days']:.0f}", _pct(s["worst"], 1, True)] + ev)
    sm = _stats(all_M)
    ev_all = {h: np.concatenate(pooled_ev[h]) if pooled_ev[h] else np.array([]) for h in HORIZONS}
    base_all = {h: np.concatenate(pooled_base[h]) if pooled_base[h] else np.array([]) for h in HORIZONS}
    rows1.append(["TOTAL", sum(r["signals"] for r in results.values()), sm["n"], _pct(sm["win"], 0),
                  _pct(sm["avg"], 1, True), _pct(sm["med"], 1, True),
                  "n/a" if sm["days"] is None else f"{sm['days']:.0f}", _pct(sm["worst"], 1, True)]
                 + [_pct(float(ev_all[h].mean()) if len(ev_all[h]) else None, 1, True) for h in HORIZONS])
    rows1.append(["Bază: orice zi", "", "", "", "", "", "", ""]
                 + [_pct(float(base_all[h].mean()) if len(base_all[h]) else None, 1, True) for h in HORIZONS])
    header1 = ["Ticker", "Semnale", "Tranz. închise", "% câștig.", "Ret. mediu", "Ret. median", "Zile med.", "Cea mai slabă",
               "După 5z", "După 10z", "După 20z"]
    widths1 = [0.12, 0.08, 0.10, 0.08, 0.09, 0.09, 0.08, 0.10, 0.09, 0.09, 0.09]

    # ---- tabelul 2: regula ta (fara vanzare la pierdere)
    rows2 = []
    for t, r in results.items():
        s = _stats(r["P"])
        rows2.append([t, r["signals"], s["n"], _pct(s["avg"], 1, True), _pct(s["all_avg"], 1, True),
                      "n/a" if s["days"] is None else f"{s['days']:.0f}",
                      _pct(s["mae_avg"], 1), _pct(s["mae_worst"], 1), s["open_n"], _pct(s["open_avg"], 1, True)])
    sp = _stats(all_P)
    rows2.append(["TOTAL", sum(r["signals"] for r in results.values()), sp["n"], _pct(sp["avg"], 1, True),
                  _pct(sp["all_avg"], 1, True), "n/a" if sp["days"] is None else f"{sp['days']:.0f}",
                  _pct(sp["mae_avg"], 1), _pct(sp["mae_worst"], 1), sp["open_n"], _pct(sp["open_avg"], 1, True)])
    header2 = ["Ticker", "Semnale", "Închise", "Ret. mediu închise", "Ret. mediu TOATE*", "Zile med. până la ieșire",
               "Scădere max. medie", "Cea mai mare scădere", "Deschise acum", "P/L mediu deschise"]
    widths2 = [0.09, 0.07, 0.07, 0.11, 0.11, 0.13, 0.11, 0.12, 0.09, 0.10]

    p1, p2 = OUT / "backtest_mecanic.png", OUT / "backtest_regula_ta.png"
    start = min(r["valid_from"] for r in results.values() if r["valid_from"] is not None)
    end = max(r["dates"][-1] for r in results.values())
    period_txt = f"{pd.Timestamp(start).date()} - {pd.Timestamp(end).date()}"
    common = (f"Perioadă {period_txt}. Intrare la deschiderea zilei următoare semnalului; cost {COST_PCT:g}% pe tranzacție; "
              f"prețuri ajustate (cu dividende); fără impozite. Rezultatele trecute nu garantează viitorul.")
    try:
        table_image(f"Backtest 1/2 - ieșire mecanică (la semnal de ieșire sau după {MAX_HOLD} ședințe)", header1, rows1,
                    widths1, common + " 'După Nz' = randament mediu la N ședințe după semnal; 'Bază' = media pentru orice zi.", p1)
        table_image("Backtest 2/2 - regula ta: ieși doar pe profit, fără stop și fără limită de timp", header2, rows2, widths2,
                    common + " 'Scădere max.' = cea mai mare scădere sub prețul de intrare cât timp ai ținut poziția. *TOATE = închise + deschise (la prețul de azi).", p2,
                    bold_last=1)
        images = [p1, p2]
    except Exception:
        images = []

    # ---- raport .md
    def md_table(header, rows):
        return (["| " + " | ".join(header) + " |", "|:---|" + "---:|" * (len(header) - 1)]
                + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])
    open_lines = []
    for t, r in results.items():
        for tr in r["P"]:
            if tr["open"]:
                open_lines.append(f"- **{t}**: intrare {pd.Timestamp(r['dates'][tr['i']]).date()}, "
                                  f"{tr['days']} ședințe deschisă, P/L {tr['ret'] * 100:+.1f}%, "
                                  f"cea mai mare scădere {tr['mae'] * 100:.1f}%")
    lines = [f"# Backtest semnale swing ({period_txt})", "",
             f"Tickere testate: {', '.join(results)}." + (f" Sărite (istoric insuficient): {', '.join(skipped)}." if skipped else ""),
             f"Reguli: intrare = preț > SMA200 + MACD cross în sus + RSI min 5z ≤ {RSI_DIP:g} și RSI < {RSI_MAX_NOW:g}"
             + (f" + Z-min5 ≤ {Z_MAX:g}" if Z_MAX is not None else "") + (f" + volum ≥ {VOL_MIN:g}x" if VOL_MIN is not None else "")
             + f"; ieșire = MACD cross în jos după RSI max 5z ≥ {RSI_PEAK:g} (acum > {RSI_MIN_NOW:g}) sau închidere sub SMA200.",
             "", "## 1. Ieșire mecanică (vinde la semnal de ieșire sau după " + f"{MAX_HOLD} ședințe)", ""]
    lines += md_table(header1, rows1)
    lines += ["", "## 2. Regula ta: ieși doar la semnal de ieșire și doar pe profit, fără stop", ""]
    lines += md_table(header2, rows2)
    lines += ["", "### Poziții rămase deschise la finalul istoricului (regula 2)", ""] + (open_lines or ["- niciuna"])
    lines += ["", "## Cum se citește", "",
              "- **Varianta 1** măsoară dacă semnalele au valoare în sine (cu o ieșire mecanică). Compară 'După 5/10/20z' cu 'Bază': "
              "dacă nu sunt clar peste bază, intrarea nu adaugă nimic față de a cumpăra într-o zi oarecare.",
              "- **Varianta 2** urmărește regula ta de a nu vinde la pierdere. Câștigurile închise arată bine prin construcție; "
              "partea importantă e 'Ret. mediu TOATE' (include pozițiile încă deschise), 'Scădere max.' și pozițiile rămase deschise: costul de a nu avea stop.",
              "- Numărul de tranzacții e mic (câteva pe ticker în 5 ani); mediile pe ticker sunt zgomotoase, totalul e mai de încredere. "
              "Dacă ajustezi pragurile RSI după aceste rezultate, riști să le potrivești pe trecut (overfitting).",
              "- Fără impozite; costul presupus e setabil (COST_PCT). Prețuri ajustate (yfinance auto_adjust): dividendele sunt incluse, ca și cum ar fi reinvestite."]
    md = OUT / "backtest_report.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

    if not send_files(images + [md], f"Backtest swing - {period_txt}"):
        fail("backtestul s-a terminat, dar trimiterea pe Telegram a eșuat.")
    print("Backtest trimis pe Telegram.")


if __name__ == "__main__":
    mode = "backtest" if "--backtest" in sys.argv else ("both" if "--all" in sys.argv else MODE)
    if mode not in ("scan", "backtest", "both"):
        fail(f"MODE necunoscut: '{mode}' (valori: scan, backtest, both).")
    if mode in ("scan", "both"):
        main_scan()
    if mode in ("backtest", "both"):
        main_backtest()
