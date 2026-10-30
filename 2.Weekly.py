import os
import re
import time
import glob
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf
import requests

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output-weekly"

# Setari (se schimba din workflow, la env:)
FAST_MA = int(os.getenv("FAST_MA", "5"))                       # medie rapida, in sedinte (5 = 1 saptamana)
SLOW_MA = int(os.getenv("SLOW_MA", "10"))                      # medie lenta (10 = 2 saptamani)
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "9"))                 # RSI pe ~2 saptamani
RSI_HOT = float(os.getenv("RSI_HOT", "70"))
PROFIT_TAKE_PCT = float(os.getenv("PROFIT_TAKE_PCT", "10"))    # profit minim (%) pentru "ia profit" cand RSI e ridicat
CONCENTRATION_PCT = float(os.getenv("CONCENTRATION_PCT", "35"))  # doar avertisment in raport, NU intra in semnal
CG_TAX_PCT = float(os.getenv("CG_TAX_PCT", "10"))              # impozit pe castig de capital (%)
DIV_TAX_PCT = float(os.getenv("DIV_TAX_PCT", "16"))            # impozit pe dividende (%)
SEND_FILES = os.getenv("SEND_FILES", "1") == "1"               # trimite pe Telegram si .md/.xlsx


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


def trend_label(close, fast, slow):
    if close > fast > slow:
        return "CRESCĂTOR"
    if close < fast < slow:
        return "DESCRESCĂTOR"
    return "MIXT"


def technical_signal(trend, rsi, ret_1w):
    if trend == "CRESCĂTOR" and rsi < RSI_HOT and ret_1w > 0:
        return "CUMPĂRĂ"
    if trend == "DESCRESCĂTOR" and ret_1w < 0:
        return "VINDE"
    return "NEUTRU"


def final_signal(tech, rsi, gain_pct):
    profit = gain_pct > 0
    if tech == "VINDE":
        if profit:
            return "VINDE", f"trend săptămânal descrescător, poziția e pe profit ({gain_pct:+.1f}%): îți asiguri câștigul"
        return "NEUTRU", (f"trend săptămânal descrescător, dar poziția e în pierdere ({gain_pct:+.1f}%): "
                          f"nu vinzi la pierdere, nu suplimentezi")
    if profit and gain_pct >= PROFIT_TAKE_PCT and rsi >= RSI_HOT:
        return "VINDE PARȚIAL", f"RSI {rsi:.0f} (≥{RSI_HOT:.0f}) și profit {gain_pct:+.1f}%: poți lua profit parțial"
    if tech == "CUMPĂRĂ":
        return "CUMPĂRĂ", f"trend săptămânal crescător, RSI {rsi:.0f}"
    return "NEUTRU", "trend mixt, fără confirmare"


def estimate_next_ex_dividend(div_series, end):
    ex = div_series[(div_series.index <= end) & (div_series.index >= end - pd.Timedelta(days=400))]
    if len(ex) < 2:
        return None, None
    gap = float(ex.index.to_series().diff().dropna().dt.days.median())
    nxt = ex.index[-1] + pd.Timedelta(days=round(gap))
    if nxt <= end:
        return None, None
    return nxt, float(ex.iloc[-1])


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


def send_photo(path, caption):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return "Telegram skipped: missing credentials"
    try:
        with path.open("rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat, "caption": caption}, files={"photo": f}, timeout=(15, 90))
        return f"{path.name}: sent" if r.ok and r.json().get("ok") else f"Telegram HTTP {r.status_code}"
    except Exception:
        return "Telegram photo failed; image remains saved"


def make_image(rows, anchor, warning, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False

    bg, fg, grid = "#0f1720", "#e8edf2", "#2a3644"
    colors = {"CUMPĂRĂ": "#1f7a4d", "VINDE": "#a8322d", "VINDE PARȚIAL": "#b5573a", "NEUTRU": "#3b4654"}

    def num(v, nd=1, sign=False, comma=False):
        if v is None or pd.isna(v):
            return "n/a"
        if nd == 0 and round(v) == 0:
            return "0"
        spec = f"{'+' if sign else ''}{',' if comma else ''}.{nd}f"
        return format(v, spec)

    header = ["Ticker", "Pond %", "P/L %", "P/L $", "Săpt %", "2 săpt %", "RSI", "Trend", "Semnal"]
    body = []
    for r in rows:
        body.append([r["ticker"], num(r["weight_used_pct"]), num(r["unrealized_pct"], 1, True),
                     num(r["pnl_usd"], 0, True, True), num(r["price_return_pct"], 1, True),
                     num(r["ret_2w_pct"], 1, True), num(r["rsi14"], 0), r["trend"] or "n/a", r["signal_final"]])

    n = len(body)
    fig, ax = plt.subplots(figsize=(12, 1.5 + 0.46 * n), facecolor=bg)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.12)
    ax.axis("off")
    tbl = ax.table(cellText=body, colLabels=header, loc="center", cellLoc="center",
                   colWidths=[0.09, 0.09, 0.10, 0.11, 0.09, 0.10, 0.07, 0.17, 0.18])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1, 1.7)
    last = len(header) - 1
    for (i, j), cell in tbl.get_celld().items():
        cell.set_edgecolor(grid)
        cell.get_text().set_color(fg)
        if i == 0:
            cell.set_facecolor("#1d2a38")
            cell.get_text().set_fontweight("bold")
        else:
            cell.set_facecolor(bg if i % 2 else "#141e29")
            if j == last:
                cell.set_facecolor(colors.get(body[i - 1][last], "#6b5d1f"))
                cell.get_text().set_fontweight("bold")
            if j == 0:
                cell.get_text().set_fontweight("bold")
    fig.suptitle(f"Raport săptămânal - săptămâna încheiată {anchor}", color=fg, fontsize=14,
                 fontweight="bold", x=0.015, ha="left")
    foot = "Semnale după reguli tehnice + poziția ta; nu sunt recomandări de investiții."
    if warning:
        foot = warning + "\n" + foot
    fig.text(0.015, 0.012, foot, color="#8b98a5", fontsize=8, va="bottom")
    fig.savefig(path, dpi=130, facecolor=bg, bbox_inches="tight")
    plt.close(fig)
    return True


def main():
    OUT.mkdir(exist_ok=True)
    
    # Căutare robustă a fișierului Excel XTB
    configured = os.getenv("PORTFOLIO_FILE", "").strip()
    candidates = sorted(ROOT.glob("USD_*.xlsx"))
    
    if configured and (ROOT / configured).exists():
        path = ROOT / configured
    elif len(candidates) == 1:
        path = candidates[0]
    elif len(candidates) > 1:
        path = candidates[0]  # Ia cel mai recent sau primul găsit
        print(g := f"ℹ️ Găsite mai multe fișiere Excel, se folosește: {path.name}")
    else:
        raise ValueError("Nu s-a găsit niciun fișier Excel care să înceapă cu USD_ în director!")

    positions, stamp = portfolio(path)
    anchor, week, base, sessions = window()
    end = week[-1]

    stamp_dt = pd.to_datetime(stamp, errors="coerce")
    warning = ""
    if pd.notna(stamp_dt) and (pd.Timestamp(anchor) - stamp_dt.normalize()).days > 7:
        warning = (f"ATENȚIE: Excel-ul e din {stamp_dt.date()} (cu {(pd.Timestamp(anchor) - stamp_dt.normalize()).days} zile "
                   f"înainte de final de săptămână). Cumpărările/vânzările ulterioare nu sunt incluse.")

    benchmark = None
    try:
        b = history("SPY", sessions)
        benchmark = (float(b.loc[end, "Adj Close"]) / float(b.loc[base, "Adj Close"]) - 1) * 100
    except Exception:
        pass

    rows = []
    for _, p in positions.iterrows():
        row = {"ticker": p.symbol, "shares_excel": p.Volume, "average_cost_excel": p["Open price"],
               "value_excel": p.Value, "weight_excel_pct": p.weight_excel_pct,
               "start_close_date": str(base.date()), "end_close_date": str(end.date()),
               "price_return_pct": None, "ret_2w_pct": None, "adjusted_return_pct": None, "close_end": None,
               "ma_fast": None, "ma_slow": None, "rsi14": None, "excess_spy_pp": None, "trend": None,
               "value_end_estimate": None, "unrealized_pct": None, "pnl_usd": None, "tax_if_sold_usd": None,
               "net_if_sold_usd": None, "hypothetical_week_price_pnl": None, "weight_used_pct": p.weight_excel_pct,
               "div_ttm_per_share": None, "div_net_annual_usd": None, "next_ex_div_est": "", "next_div_est": None,
               "signal_tehnic": "FĂRĂ DATE", "signal_final": "FĂRĂ DATE", "motiv": "", "flags": ""}
        try:
            h = history(p.symbol, sessions)
            h.to_csv(OUT / f"history_{p.symbol}.csv")
            required = sessions[sessions <= end][-30:]
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
            ret2 = (close.loc[end] / close.iloc[-11] - 1) * 100
            fast, slow = close.tail(FAST_MA).mean(), close.tail(SLOW_MA).mean()
            delta = adjusted.diff()
            gain = delta.clip(lower=0).ewm(alpha=1/RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean().iloc[-1]
            loss = (-delta.clip(upper=0)).ewm(alpha=1/RSI_PERIOD, adjust=False, min_periods=RSI_PERIOD).mean().iloc[-1]
            rsi = 50.0 if gain == loss == 0 else 100.0 if loss == 0 else 100 - 100/(1+gain/loss)
            excess = ar - benchmark if benchmark is not None else None
            flags = []
            if rsi >= RSI_HOT:
                flags.append(f"RSI >={RSI_HOT:.0f}: impuls extins")
            if rsi <= 30:
                flags.append("RSI <=30: slabiciune")
            if "Stock Splits" in h and (h.loc[h.index > base, "Stock Splits"] != 0).any():
                flags.append("Split dupa inceputul perioadei: reconciliaza cantitatea si costul Excel")
                comparable = False
            else:
                comparable = True
            if p.weight_excel_pct < 1:
                flags.append("Pozitie simbolica (<1% din portofoliu)")

            if "Dividends" in h:
                divs = h.loc[:end, "Dividends"]
                divs = divs[divs > 0]
                ttm = float(divs[divs.index > end - pd.Timedelta(days=365)].sum())
                row["div_ttm_per_share"] = ttm
                row["div_net_annual_usd"] = float(p.Volume * ttm * (1 - DIV_TAX_PCT / 100))
                nxt, amt = estimate_next_ex_dividend(divs, end)
                if nxt is not None and (nxt - end).days <= 10:
                    row["next_ex_div_est"] = str(nxt.date())
                    row["next_div_est"] = amt

            pnl = float(p.Volume * (close.loc[end] - p["Open price"])) if comparable else None
            tax = max(pnl, 0.0) * CG_TAX_PCT / 100 if pnl is not None else None
            row.update(price_return_pct=float(ret), ret_2w_pct=float(ret2), adjusted_return_pct=float(ar),
                close_end=float(close.loc[end]), ma_fast=float(fast), ma_slow=float(slow), rsi14=float(rsi),
                excess_spy_pp=excess, trend=trend_label(close.loc[end], fast, slow),
                value_end_estimate=float(p.Volume * close.loc[end]) if comparable else None,
                unrealized_pct=float((close.loc[end] / p["Open price"] - 1) * 100) if comparable else None,
                pnl_usd=pnl, tax_if_sold_usd=tax, net_if_sold_usd=(pnl - tax) if pnl is not None else None,
                hypothetical_week_price_pnl=float(p.Volume * (close.loc[end] - close.loc[base])) if comparable else None,
                flags="; ".join(flags))
            if not comparable:
                row.update(signal_tehnic="FĂRĂ SEMNAL", signal_final="FĂRĂ SEMNAL",
                           motiv="split nereconciliat: poziția din Excel nu e comparabilă cu prețul")
        except Exception:
            row["flags"] = "Yahoo unavailable, unmapped symbol, short history or incomplete week; inspect history artifact"
        rows.append(row)
        time.sleep(1)

    available = sum(r["close_end"] is not None for r in rows)
    concentration = positions.nlargest(3, "Value").weight_excel_pct.sum()

    all_valued = available == len(rows) and all(r["value_end_estimate"] is not None for r in rows)
    if all_valued:
        total = sum(r["value_end_estimate"] for r in rows)
        for r in rows:
            r["weight_used_pct"] = r["value_end_estimate"] / total * 100
        weights_note = "Ponderi la final de săptămână (estimate din prețurile de închidere)."
    else:
        total = None
        weights_note = "Ponderi din Excel (acoperire incompletă sau split nereconciliat)."

    for r in rows:
        if r["close_end"] is None or r["trend"] is None or r["unrealized_pct"] is None:
            continue
        tech = technical_signal(r["trend"], r["rsi14"], r["price_return_pct"])
        final, why = final_signal(tech, r["rsi14"], r["unrealized_pct"])
        if final in ("VINDE", "VINDE PARȚIAL") and r["next_ex_div_est"] and r["next_div_est"]:
            net_div = r["shares_excel"] * r["next_div_est"] * (1 - DIV_TAX_PCT / 100)
            why = why.rstrip(".") + "."
            why += (f" Atenție: ex-dividend estimat ~{r['next_ex_div_est']} (~{r['next_div_est']:.2f}$/acțiune, "
                    f"~{net_div:,.0f}$ net pentru toată poziția): dacă vinzi înainte, nu îl încasezi.")
        r.update(signal_tehnic=tech, signal_final=final, motiv=why)
        if r["weight_used_pct"] > CONCENTRATION_PCT:
            r["flags"] = (r["flags"] + "; " if r["flags"] else "") + \
                f"Pondere {r['weight_used_pct']:.1f}% peste {CONCENTRATION_PCT:.0f}% (doar avertisment)"

    result = pd.DataFrame(rows)
    result.to_csv(OUT / "weekly_signals.csv", index=False)

    f = lambda x, nd=2: "n/a" if x is None or pd.isna(x) else f"{x:.{nd}f}"
    fm = lambda x: "n/a" if x is None or pd.isna(x) else ("0" if round(x) == 0 else f"{x:+,.0f}")
    lines = [
        "# 📊 Raport săptămânal portofoliu",
        "",
        f"Săptămâna completă încheiată la {anchor}; ședințe {week[0].date()} - {end.date()}.",
        f"Randamente: închidere {base.date()} -> închidere {end.date()}.",
        f"Excel: {path.name}; dată declarată: {stamp}.",
        f"Poziții cu date valide: {available}/{len(rows)}. Ponderea primelor 3 în Excel: {concentration:.2f}%.",
        weights_note,
    ]
    if warning:
        lines += ["", f"⚠️ {warning}"]

    lines += ["", "## Semnale (trend săptămânal + poziția ta)", "",
              "| Ticker | Pond % | P/L cost % | P/L $ | Net după impozit $ | Săpt % | 2 săpt % | RSI | Trend | Semnal tehnic | Semnal final |",
              "|:---|---:|---:|---:|---:|---:|---:|---:|:---|:---|:---|"]
    for r in rows:
        lines.append(f"| **{r['ticker']}** | {f(r['weight_used_pct'], 1)} | {f(r['unrealized_pct'], 1)} | {fm(r['pnl_usd'])} | "
                     f"{fm(r['net_if_sold_usd'])} | {f(r['price_return_pct'], 1)} | {f(r['ret_2w_pct'], 1)} | {f(r['rsi14'], 0)} | "
                     f"{r['trend'] or 'n/a'} | {r['signal_tehnic']} | **{r['signal_final']}** |")

    lines += ["", "## Detalii pe companii", ""]
    for r in rows:
        div_txt = ""
        if r["div_ttm_per_share"] is not None:
            div_txt = (f" Dividende ultimele 12 luni: {r['div_ttm_per_share']:.2f}$/acțiune; "
                       f"net după impozitul de {DIV_TAX_PCT:.0f}%: ~{r['div_net_annual_usd']:,.0f}$/an pentru poziția ta.")
        tax_txt = ""
        if r["pnl_usd"] is not None:
            if r["pnl_usd"] > 0:
                tax_txt = (f" Dacă vinzi acum: câștig {r['pnl_usd']:,.0f}$, impozit {CG_TAX_PCT:.0f}% ≈ {r['tax_if_sold_usd']:,.0f}$, "
                           f"net ≈ {r['net_if_sold_usd']:,.0f}$.")
            else:
                tax_txt = f" Poziția e în pierdere ({r['pnl_usd']:,.0f}$); nu se plătește impozit pe câștig."
        lines += [
            f"### {r['ticker']}  —  {r['signal_final']}",
            f"Poziție: {r['shares_excel']} acțiuni; cost mediu {r['average_cost_excel']:.2f} USD; "
            f"preț final {f(r['close_end'])}; P/L față de cost {f(r['unrealized_pct'], 1)}%; pondere {f(r['weight_used_pct'], 1)}%.{tax_txt}",
            f"Trend: {r['trend'] or 'n/a'} (săptămână {f(r['price_return_pct'], 1)}%, 2 săptămâni {f(r['ret_2w_pct'], 1)}%, "
            f"față de SPY {f(r['excess_spy_pp'])} pp). MA{FAST_MA} {f(r['ma_fast'])}; MA{SLOW_MA} {f(r['ma_slow'])}; RSI{RSI_PERIOD} {f(r['rsi14'], 0)}.{div_txt}",
            f"Semnal tehnic (doar trend): {r['signal_tehnic']}. Semnal final (cu poziția ta): {r['signal_final']}. {r['motiv']}",
            f"{r['flags']}",
            ""
        ]

    if total is not None:
        lines += [f"Valoare estimată a pozițiilor la final: {total:,.2f} USD; presupune cantități neschimbate."]
    else:
        lines += ["Nu se calculează valoarea integrală: acoperire incompletă / splituri nereconciliate."]

    lines += [
        "", "## Reguli și limite",
        f"- Trend CRESCĂTOR: Close > MA{FAST_MA} > MA{SLOW_MA}. DESCRESCĂTOR: Close < MA{FAST_MA} < MA{SLOW_MA}. Altfel MIXT. "
        f"MA{FAST_MA} = 1 săptămână, MA{SLOW_MA} = 2 săptămâni. Cu cât fereastra e mai scurtă, cu atât semnalele sunt mai sensibile și mai zgomotoase.",
        f"- Semnal tehnic (doar trend): CUMPĂRĂ = trend crescător, RSI{RSI_PERIOD} < {RSI_HOT:.0f} și săptămâna pozitivă; VINDE = trend descrescător și săptămâna negativă; altfel NEUTRU.",
        "- Semnal final (cu poziția ta): trend descrescător pe profit = VINDE; trend descrescător în pierdere = NEUTRU (nu se vinde la pierdere).",
        f"- RSI ≥ {RSI_HOT:.0f} cu profit ≥ {PROFIT_TAKE_PCT:.0f}% = VINDE PARȚIAL (luare de profit). Trend crescător = CUMPĂRĂ.",
        f"- Concentrarea nu intră în semnal; doar apare ca avertisment peste {CONCENTRATION_PCT:.0f}% din portofoliu.",
        f"- Impozite folosite la estimări: {CG_TAX_PCT:.0f}% pe câștig de capital, {DIV_TAX_PCT:.0f}% pe dividende. Baza fiscală e aproximată prin costul mediu din Excel; "
        "baza reală (lot cu lot) poate diferi.",
        "- Data ex-dividend este estimată din intervalul obișnuit dintre dividendele anterioare; verifică data oficială înainte de a decide.",
        "- Cantitățile/costurile sunt fotografia din Excel, nu un registru al tranzacțiilor din săptămână.",
        "- P/L săptămânal este ipotetic: aceleași cantități pe toată perioada, nu performanța reală a contului.",
        "- Prețuri Yahoo Finance (Close, ajustat pentru splituri). RSI cu netezire exponențială.",
        "- Semnalele sunt reguli tehnice automate, nu predicții și nu recomandări personalizate de investiții. Nu iau în calcul știrile sau rezultatele companiilor.",
    ]

    for name in ["Analiza.md", "analiza.md", "docs/analiza.md", "docs/Analiza.md"]:
        ap = ROOT / name
        if ap.exists():
            text = ap.read_text(encoding="utf-8")
            m = re.search(r"Data generării:\*\*\s*`([^`]+)`", text)
            gen = f" (generat la {m.group(1)})" if m else ""
            lines += ["", f"## 📈 Context din Analiza.md{gen}",
                      "_Context zilnic, doar informativ: nu influențează semnalele de mai sus._", "", text]
            break
    else:
        lines += ["", "Context indisponibil: Analiza.md nu a fost gasit."]

    report = OUT / "weekly_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")

    with pd.ExcelWriter(OUT / "weekly_report.xlsx") as writer:
        result.to_excel(writer, sheet_name="Weekly signals", index=False)
        positions.to_excel(writer, sheet_name="Excel positions", index=False)

    image = OUT / "weekly_signals.png"
    statuses = []
    if make_image(rows, anchor, warning, image):
        statuses.append(send_photo(image, f"Raport săptămânal - săptămâna încheiată {anchor}"))
    else:
        statuses.append("Imagine omisă: matplotlib lipsește")
    if SEND_FILES:
        statuses += [send(report), send(OUT / "weekly_report.xlsx")]
    (OUT / "delivery-status.txt").write_text("\n".join(statuses))
    print(f"Generated report: week ending {anchor}, valid positions {available}/{len(rows)}")
    if available == 0:
        raise RuntimeError("No valid market data; diagnostic reports saved")


if __name__ == "__main__":
    main()