import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output-weekly"


def portfolio(path):
    raw = pd.read_excel(path, sheet_name="Open Positions", header=None)
    header = next((i for i, row in raw.iterrows() if "Ticker" in row.values and "Volume" in row.values), None)
    if header is None:
        raise ValueError("XTB header not found")
    df = pd.read_excel(path, sheet_name="Open Positions", header=header)
    df = df[df.Type.isna() & df.Ticker.notna()].copy()
    for col in ["Volume", "Value", "Open price"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if df.empty or df[["Volume", "Value", "Open price"]].isna().any().any():
        raise ValueError("Missing or invalid portfolio values; no invented fallback")
    if (df.Volume <= 0).any() or (df.Value < 0).any():
        raise ValueError("This version supports long stock positions only")
    if not df.Ticker.astype(str).str.endswith(".US").all():
        raise ValueError("Non-US tickers require explicit mapping")
    df["symbol"] = df.Ticker.str.removesuffix(".US").str.replace(".", "-", regex=False)
    if df.symbol.duplicated().any():
        raise ValueError("Duplicate parent ticker: review portfolio before aggregating")
    df["weight_excel_pct"] = df.Value / df.Value.sum() * 100
    stamp = next((row.iloc[1] for _, row in raw.iterrows() if str(row.iloc[0]) == "Data as of report generated"), "unknown")
    return df, str(stamp)


def window():
    today = datetime.now(ZoneInfo("America/New_York")).date()
    override = os.getenv("WEEK_END", "").strip()
    if override:
        anchor = pd.Timestamp(override).date()
        if anchor.weekday() != 4 or anchor >= today:
            raise ValueError("WEEK_END must be a past Friday, YYYY-MM-DD")
    else:
        yesterday = today - timedelta(days=1)
        anchor = yesterday - timedelta(days=(yesterday.weekday() - 4) % 7)
    sessions = mcal.get_calendar("NYSE").schedule(start_date=anchor-timedelta(days=400), end_date=anchor).index
    sessions = pd.DatetimeIndex(sessions).tz_localize(None).normalize()
    week = sessions[sessions >= pd.Timestamp(anchor-timedelta(days=4))]
    if week.empty:
        raise ValueError("No exchange sessions in selected week")
    baseline = sessions[sessions < week[0]][-1]
    return anchor, week, baseline, sessions


def history(symbol, sessions):
    for attempt in range(2):
        try:
            obj = yf.Ticker(symbol)
            h = obj.history(start=sessions[0].strftime("%Y-%m-%d"),
                end=(sessions[-1]+pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                auto_adjust=False, actions=True, raise_errors=True, timeout=25)
            if h.empty or (obj.get_history_metadata() or {}).get("currency") != "USD":
                raise ValueError("Missing history or wrong currency")
            h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
            h = h[~h.index.duplicated()].sort_index()
            return h
        except Exception:
            if attempt == 0:
                time.sleep(4)
    raise RuntimeError("Yahoo unavailable, invalid symbol, or history inaccessible")


def signal(ret, close, ma20, ma50, excess):
    if ret <= -5 and close < ma20 and close < ma50:
        return "RISC TEHNIC RIDICAT: revizuieste pozitia, nu cumparare automata"
    if ret > 0 and close > ma20 > ma50 and excess > 0:
        return "TREND POZITIV: urmarire; nu ordin automat de cumparare"
    if ret < 0 and close < ma20 < ma50:
        return "TREND NEGATIV: prudenta la suplimentare"
    return "MIXT / NEUTRU: asteapta confirmare"


def send(path):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return "Telegram skipped: missing credentials"
    try:
        with path.open("rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat}, files={"document": f}, timeout=(15, 90))
        return f"{path.name}: sent" if r.ok and r.json().get("ok") else f"Telegram HTTP {r.status_code}"
    except Exception:
        return "Telegram failed; reports remain saved"


def main():
    OUT.mkdir(exist_ok=True)
    configured = os.getenv("PORTFOLIO_FILE", "").strip()
    candidates = sorted(ROOT.glob("USD_*.xlsx"))
    if configured:
        path = ROOT / configured
    elif len(candidates) == 1:
        path = candidates[0]
    else:
        raise ValueError("Set PORTFOLIO_FILE explicitly if zero or multiple Excel files exist")
    positions, stamp = portfolio(path)
    anchor, week, base, sessions = window()
    end = week[-1]
    benchmark = None
    try:
        b = history("SPY", sessions)
        benchmark = (float(b.loc[end,"Adj Close"]) / float(b.loc[base,"Adj Close"]) - 1) * 100
    except Exception:
        pass
    rows = []
    for _, p in positions.iterrows():
        row = {"ticker": p.symbol, "shares_excel": p.Volume, "average_cost_excel": p["Open price"],
               "value_excel": p.Value, "weight_excel_pct": p.weight_excel_pct,
               "start_close_date": str(base.date()), "end_close_date": str(end.date()),
               "price_return_pct": None, "adjusted_return_pct": None, "close_end": None,
               "sma20": None, "sma50": None, "rsi14": None, "excess_spy_pp": None,
               "value_end_estimate": None, "unrealized_vs_excel_cost_estimate": None,
               "hypothetical_week_price_pnl": None, "signal": "DATE INDISPONIBILE", "flags": ""}
        try:
            h = history(p.symbol, sessions)
            h.to_csv(OUT / f"history_{p.symbol}.csv")
            required = sessions[sessions <= end][-60:]
            if not required.isin(h.index).all() or base not in h.index:
                raise ValueError("Missing exchange sessions; no stale-price substitution")
            for col in ["Close", "Adj Close", "Volume"]:
                if pd.to_numeric(h.loc[required, col], errors="coerce").isna().any():
                    raise ValueError("Incomplete numeric market data")
            close = h.Close.loc[:end]
            adjusted = h["Adj Close"].loc[:end]
            if (adjusted.loc[required] <= 0).any() or (close.loc[required] <= 0).any():
                raise ValueError("Invalid price")
            ret = (close.loc[end] / close.loc[base] - 1) * 100
            ar = (adjusted.loc[end] / adjusted.loc[base] - 1) * 100
            ma20, ma50 = close.tail(20).mean(), close.tail(50).mean()
            delta = adjusted.diff()
            gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean().iloc[-1]
            loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean().iloc[-1]
            rsi = 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100/(1+gain/loss)
            excess = ar - benchmark if benchmark is not None else None
            flags = []
            if rsi >= 70:
                flags.append("RSI >=70: impuls extins, nu vanzare automata")
            if rsi <= 30:
                flags.append("RSI <=30: slabiciune, nu cumparare automata")
            if "Stock Splits" in h and (h.loc[h.index > base, "Stock Splits"] != 0).any():
                flags.append("Split dupa inceputul perioadei: reconciliaza cantitatea si costul Excel")
                comparable = False
            else:
                comparable = True
            if p.weight_excel_pct > float(os.getenv("CONCENTRATION_PCT", "15")):
                flags.append("Pondere Excel peste pragul configurat")
            row.update(price_return_pct=float(ret), adjusted_return_pct=float(ar), close_end=float(close.loc[end]),
                sma20=float(ma20), sma50=float(ma50), rsi14=float(rsi), excess_spy_pp=excess,
                value_end_estimate=float(p.Volume*close.loc[end]) if comparable else None,
                unrealized_vs_excel_cost_estimate=float(p.Volume*(close.loc[end]-p["Open price"])) if comparable else None,
                hypothetical_week_price_pnl=float(p.Volume*(close.loc[end]-close.loc[base])) if comparable else None,
                signal=signal(ret,close.loc[end],ma20,ma50,excess) if excess is not None else "SEMNALE PARTIALE: benchmark indisponibil",
                flags="; ".join(flags))
        except Exception:
            row["flags"] = "Yahoo unavailable, unmapped symbol, short history or incomplete week; inspect history artifact"
        rows.append(row)
        time.sleep(1)
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "weekly_signals.csv", index=False)
    available = result.close_end.notna().sum()
    concentration = positions.nlargest(3,"Value").weight_excel_pct.sum()
    lines = ["# Raport saptamanal portofoliu", "",
        f"Saptamana completa incheiata la {anchor}; sedinte {week[0].date()} - {end.date()}.",
        f"Randamente: inchidere {base.date()} -> inchidere {end.date()}.",
        f"Excel: {path.name}; data declarata: {stamp}.",
        f"Pozitii cu date valide: {available}/{len(rows)}. Ponderea primelor 3 in Excel: {concentration:.2f}%.",
        "", "## Limite si interpretare",
        "- Cantitatile/costurile sunt fotografia Excel, nu un registru al tranzactiilor din saptamana.",
        "- P/L saptamanal este ipotetic: aceleasi cantitati detinute toata perioada; nu performanta reala a contului.",
        "- Ponderile Excel nu sunt ponderi live. Ponderile la final se estimeaza doar daca toate pozitiile au date.",
        "- Pret: Close ajustat pentru splituri, nu dividende. Randament ajustat: Adj Close Yahoo, aproximare de randament cu ajustari de distributii.",
        "- Diferenta fata de SPY este in puncte procentuale; benchmark general, nu sectorial.",
        "- Semnalele sunt reguli tehnice configurate, nu predictii, recomandari personalizate sau ordine.",
        "- RSI foloseste netezire exponentiala alpha=1/14; praguri 30/70. MA20 si MA50 folosesc Close.",
        "- Reguli: pozitiv daca randament >0, Close>MA20>MA50 si depaseste SPY; negativ daca randament<0 si Close<MA20<MA50; risc ridicat daca <=-5% si sub ambele medii.",
        "- Analiza.md este anexata ca text contextual, nu verificata sau interpretata automat.", "", "## Semnale pe companii"]
    for r in rows:
        f = lambda x: "n/a" if x is None else f"{x:.2f}"
        lines += [f"### {r['ticker']}",
            f"Actiuni: {r['shares_excel']}; cost mediu Excel: {r['average_cost_excel']:.2f} USD; pondere Excel: {r['weight_excel_pct']:.2f}%.",
            f"Pret final: {f(r['close_end'])}; variatie pret: {f(r['price_return_pct'])}%; variatie ajustata: {f(r['adjusted_return_pct'])}%; fata de SPY: {f(r['excess_spy_pp'])} pp.",
            f"MA20: {f(r['sma20'])}; MA50: {f(r['sma50'])}; RSI14: {f(r['rsi14'])}.",
            f"Semnal: {r['signal']}. {r['flags']}", ""]
    if available == len(rows) and result.value_end_estimate.notna().all():
        total = result.value_end_estimate.sum()
        result["weight_end_estimate_pct"] = result.value_end_estimate / total * 100
        lines += [f"Valoare estimata a pozitiilor la final: {total:,.2f} USD; presupune cantitati neschimbate."]
    else:
        lines += ["Nu se calculeaza valoarea integrala sau randamentul agregat: acoperire incompleta / splituri nereconciliate."]
    for name in ["analiza.md", "docs/analiza.md"]:
        ap = ROOT / name
        if ap.exists():
            lines += ["", "## Context din analiza.md (neschimbat, data de verificat)", ap.read_text(encoding="utf-8")]
            break
    else:
        lines += ["", "Context indisponibil: analiza.md nu a fost gasit."]
    report = OUT / "weekly_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    result.to_csv(OUT / "weekly_signals.csv", index=False)
    with pd.ExcelWriter(OUT / "weekly_report.xlsx") as writer:
        result.to_excel(writer,sheet_name="Weekly signals",index=False)
        positions.to_excel(writer,sheet_name="Excel positions",index=False)
    statuses = [send(report), send(OUT/"weekly_report.xlsx")]
    (OUT/"delivery-status.txt").write_text("\n".join(statuses))
    print(f"Generated report: week ending {anchor}, valid positions {available}/{len(rows)}")
    if available == 0:
        raise RuntimeError("No valid market data; diagnostic reports saved")

if __name__ == "__main__":
    main()
