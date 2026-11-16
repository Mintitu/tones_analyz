"""
Scanner zilnic de semnale swing: tendinta (pret > SMA200) + MACD incrucisare in sus + RSI care a coborat recent.

Ruleaza dupa inchiderea bursei SUA. Trimite UN SINGUR mesaj pe Telegram, doar daca exista semnale
(sau la erori). Filtrele Z-score si volum sunt optionale (dezactivate implicit).
"""
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

# --- Setari (din workflow, la env:) -----------------------------------------------------------
TICKERS = [t.strip().upper() for t in os.getenv(
    "TICKERS", "AAPL,MSFT,PEP,AVGO,ARCC,KGS,ARE,CAG,QYLD,PFLT,DX,SCM").split(",") if t.strip()]
RSI_DIP = float(os.getenv("RSI_DIP", "42"))             # RSI a coborat sub acest nivel in ultimele 5 sedinte
RSI_MAX_NOW = float(os.getenv("RSI_MAX_NOW", "60"))     # si acum e sub acest nivel (nu e deja ridicat)


def _opt_float(name):
    v = os.getenv(name, "").strip()
    return float(v) if v else None


Z_MAX = _opt_float("Z_MAX")            # optional: Z-score minim pe 5 zile <= valoare (ex. -1)
VOL_MIN = _opt_float("VOL_MIN")        # optional: volum azi / media ultimelor 20 de sedinte >= valoare (ex. 1)
ONLY_IF_SESSION_TODAY = os.getenv("ONLY_IF_SESSION_TODAY", "1") == "1"   # 0 = ruleaza oricand (test manual)
SEND_IF_NONE = os.getenv("SEND_IF_NONE", "0") == "1"                      # 1 = mesaj scurt si fara semnale
NOTIFY_ERRORS = os.getenv("NOTIFY_ERRORS", "1") == "1"


def now_ny():
    return datetime.now(ZoneInfo("America/New_York"))


def send_telegram(text):
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN") or "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("Lipsesc TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (secrets din GitHub).")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
        if not (r.ok and r.json().get("ok")):
            print(f"Telegram a refuzat mesajul (HTTP {r.status_code}).")
            return False
        return True
    except Exception:
        print("Eroare de conexiune cu Telegram.")      # fara detalii: URL-ul contine tokenul
        return False


def fail(message):
    print(f"EROARE: {message}")
    if NOTIFY_ERRORS:
        send_telegram(f"⚠️ <b>Scanner swing eșuat</b>\n{message}")
    sys.exit(1)


def download(ticker):
    """Istoric zilnic pe 1 an (cu o reincercare). Intoarce DataFrame simplu: Open/High/Low/Close/Volume."""
    for attempt in range(2):
        try:
            df = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=True)
            if df is not None and not df.empty:
                return df.dropna(subset=["Close"])
        except Exception:
            pass
        time.sleep(3)
    return None


def indicators(df):
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]

    sma200 = close.rolling(200).mean()

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    rsi = rsi.where(loss != 0, 100.0)                       # fara pierderi => RSI 100, nu NaN

    sma20, std20 = close.rolling(20).mean(), close.rolling(20).std()
    z = (close - sma20) / std20

    prev_close = close.shift(1)
    true_range = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    vol_avg20 = vol.iloc[-21:-1].mean()                     # media celor 20 de sedinte dinaintea de azi
    return {
        "price": float(close.iloc[-1]), "sma200": float(sma200.iloc[-1]),
        "macd": float(macd.iloc[-1]), "macd_prev": float(macd.iloc[-2]),
        "signal": float(macd_signal.iloc[-1]), "signal_prev": float(macd_signal.iloc[-2]),
        "rsi": float(rsi.iloc[-1]), "rsi_min5": float(rsi.iloc[-5:].min()),
        "z": float(z.iloc[-1]), "z_min5": float(z.iloc[-5:].min()),
        "atr": float(atr.iloc[-1]),
        "vol_ratio": float(vol.iloc[-1] / vol_avg20) if vol_avg20 and vol_avg20 > 0 else None,
    }


def scan_confluence(ticker, df):
    """Mesajul pentru ticker daca toate conditiile sunt indeplinite, altfel None."""
    if df is None or len(df) < 210:
        return None
    ind = indicators(df)
    values = [ind[k] for k in ("sma200", "macd", "macd_prev", "signal", "signal_prev", "rsi", "rsi_min5")]
    if any(pd.isna(v) for v in values):
        return None

    trend_ok = ind["price"] > ind["sma200"]
    cross_up = ind["macd_prev"] <= ind["signal_prev"] and ind["macd"] > ind["signal"]
    rsi_ok = ind["rsi_min5"] <= RSI_DIP and ind["rsi"] < RSI_MAX_NOW
    z_ok = Z_MAX is None or (not pd.isna(ind["z_min5"]) and ind["z_min5"] <= Z_MAX)
    vol_ok = VOL_MIN is None or (ind["vol_ratio"] is not None and ind["vol_ratio"] >= VOL_MIN)
    if not (trend_ok and cross_up and rsi_ok and z_ok and vol_ok):
        return None

    stop = ind["price"] - 2 * ind["atr"]
    vol_txt = f" | volum {ind['vol_ratio']:.1f}x media" if ind["vol_ratio"] is not None else ""
    return (
        f"🟢 <b>{ticker}</b> — ${ind['price']:.2f} (SMA200: ${ind['sma200']:.2f})\n"
        f"   • RSI: <b>{ind['rsi']:.1f}</b> (min 5z: {ind['rsi_min5']:.1f})\n"
        f"   • Z-Score: <b>{ind['z']:.2f}</b> (min 5z: {ind['z_min5']:.2f}){vol_txt}\n"
        f"   • MACD: {ind['macd']:.3f} față de semnal {ind['signal']:.3f} (încrucișare în sus)\n"
        f"   • Stop orientativ (2×ATR): ${stop:.2f} ({(stop / ind['price'] - 1) * 100:.1f}%)"
    )


def market_gate():
    """True daca azi a fost sedinta si bursa s-a inchis. Evita repetarea semnalelor de ieri in sarbatori."""
    df = download("SPY")
    if df is None:
        fail("nu am putut verifica sesiunea de bursa (SPY indisponibil).")
    last = df.index[-1]
    last_date = pd.Timestamp(last).date()
    now = now_ny()
    if last_date != now.date():
        print(f"Nu a fost sedinta azi (ultima sedinta: {last_date}). Nu scanez.")
        return False
    if (now.hour, now.minute) < (16, 15):
        print("Piata din SUA e inca deschisa; scanez dupa inchidere. Nu scanez.")
        return False
    return True


def main():
    if ONLY_IF_SESSION_TODAY and not market_gate():
        return

    signals, errors = [], []
    for t in TICKERS:
        try:
            df = download(t)
            if df is None:                      # Yahoo nu a returnat date: eroare, nu "fara semnal"
                errors.append(t)
                print(f"Date indisponibile pentru {t}.")
                continue
            res = scan_confluence(t, df)
            if res:
                signals.append(res)
        except Exception as e:
            errors.append(t)
            print(f"Eroare la {t}: {e.__class__.__name__}")

    if len(errors) > len(TICKERS) / 2:
        fail(f"date indisponibile pentru {len(errors)} din {len(TICKERS)} tickere.")

    if not signals:
        print("Niciun semnal detectat azi.")
        if SEND_IF_NONE and not send_telegram("ℹ️ Scanare swing finalizată: niciun semnal de confluență azi."):
            fail("trimiterea mesajului pe Telegram a eșuat.")
        return

    filters = ""
    if Z_MAX is not None:
        filters += f", Z-min5 ≤ {Z_MAX:g}"
    if VOL_MIN is not None:
        filters += f", volum ≥ {VOL_MIN:g}x"
    header = f"📊 <b>Semnale Swing</b> (preț > SMA200 + MACD cross + RSI{filters})\n\n"
    message = header + "\n\n".join(signals)
    if len(message) > 3900:
        message = message[:3900].rsplit("\n\n", 1)[0] + "\n\n… (lista continuă, vezi logul rulării)"
    if errors:
        message += f"\n\n⚠️ Date indisponibile pentru: {', '.join(errors)}"

    print(message)
    if not send_telegram(message):
        fail("semnalele au fost găsite, dar trimiterea pe Telegram a eșuat.")


if __name__ == "__main__":
    main()
