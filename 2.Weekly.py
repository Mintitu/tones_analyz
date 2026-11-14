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
SEND_FILES = os.getenv("SEND_FILES", "1") == "1"               # trimite pe Telegram .md si .csv (fara xlsx)


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


def fmt_num(x, nd=6):
    t = f"{float(x):.{nd}f}".rstrip("0").rstrip(".")
    return t if t not in ("", "-0") else "0"


def export_wealthfolio(positions, anchor):
    which = os.getenv("WEALTHFOLIO_FILES", "holdings,activities").lower()
    paths = []

    if "holdings" in which:
        rows = []
        for _, p in positions.iterrows():
            rows.append({
                "Symbol": p.symbol,
                "Quantity": fmt_num(p.Volume),
                "Average cost basis": fmt_num(p["Open price"]),
                "Currency": "USD",
                "Description": str(p.get("Instrument/Position", p.symbol)),
            })
        path = OUT / "Wealthfolio_Holdings.csv"
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
        paths.append(path)

    if "activities" in which:
        date_str = f"{anchor}T00:00:00.000Z"
        rows = []
        for _, p in positions.iterrows():
            rows.append({
                "date": date_str,
                "symbol": p.symbol,
                "quantity": fmt_num(p.Volume),
                "activityType": "BUY",
                "unitPrice": fmt_num(p["Open price"]),
                "currency": "USD",
                "fee": 0,
                "amount": fmt_num(p.Volume * p["Open price"], 2),
            })
        path = OUT / "Wealthfolio_Activities.csv"
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8", lineterminator="\n")
        paths.append(path)

    return paths


def report_stamp(path):
    try:
        raw = pd.read_excel(path, sheet_name="Open Positions", header=None)
    except Exception:
        return None
    for _, row in raw.iterrows():
        if str(row.iloc[0]) == "Data as of report generated":
            return pd.to_datetime(row.iloc[1], errors="coerce")
    return pd.NaT


def name_date(path):
    found = re.findall(r"\d{4}-\d{2}-\d{2}", path.name)
    return pd.Timestamp(found[-1]) if found else pd.Timestamp.min


def pick_portfolio_file():
    pattern = os.getenv("PORTFOLIO_FILE", "").strip() or "USD_*.xlsx"
    found = sorted(Path(p) for p in glob.glob(str(ROOT / pattern)))
    valid = []
    for p in found:
        st = report_stamp(p)
        if st is not None:
            valid.append((st if pd.notna(st) else pd.Timestamp.min, name_date(p), p.name, p))
    if not valid:
        raise ValueError(f"Nu am gasit niciun Excel XTB cu foaia 'Open Positions' dupa modelul '{pattern}'.")
    valid.sort(key=lambda t: (t[0], t[1], t[2]))
    chosen = valid[-1][3]
    print(f"Excel folosit: {chosen.name}")
    return chosen


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
    mime = {".csv": "text/csv", ".md": "text/markdown"}.get(path.suffix.lower(), "application/octet-stream")
    try:
        with path.open("rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat}, files={"document": (path.name, f, mime)}, timeout=(15, 90))
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
    trend_colors = {"CRESCĂTOR": "#4cc38a", "DESCRESCĂTOR": "#ff7b72"}

    def num(v, nd=1, sign=False):
        if v is None or pd.isna(v):
            return "n/a"
        if nd == 0 and round(v) == 0:
            return "0"
        return format(v, f"{'+' if sign else ''}.{nd}f")

    header = ["Trend", "Semnal", "Ticker", "Săpt %", "2 săpt %", "1 lună %", "3 luni %", "RSI", "vs VWAP %", "vs max 52s %", "Vol rel."]
    body = []
    for r in rows:
        body.append([r["trend"] or "n/a", r["signal_final"], r["ticker"],
                     num(r["price_return_pct"], 1, True), num(r["ret_2w_pct"], 1, True),
                     num(r["ret_1m_pct"], 1, True), num(r["ret_3m_pct"], 1, True), num(r["rsi14"], 0),
                     num(r["vs_vwap_pct"], 1, True), num(r["vs_high52_pct"], 1, True),
                     "n/a" if r["vol_ratio"] is None else f"{r['vol_ratio']:.2f}x"])

    n = len(body)
    fig, ax = plt.subplots(figsize=(13.5, 1.6 + 0.46 * n), facecolor=bg)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.14)
    ax.axis("off")
    tbl = ax.table(cellText=body, colLabels=header, loc="center", cellLoc="center",
                   colWidths=[0.13, 0.18, 0.07, 0.07, 0.07, 0.08, 0.08, 0.05, 0.09, 0.11, 0.07])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1, 1.7)
    for (i, j), cell in tbl.get_celld().items():
        cell.set_edgecolor(grid)
        cell.get_text().set_color(fg)
        if i == 0:
            cell.set_facecolor("#1d2a38")
            cell.get_text().set_fontweight("bold")
        else:
            cell.set_facecolor(bg if i % 2 else "#141e29")
            if j == 0:
                cell.get_text().set_color(trend_colors.get(body[i - 1][0], fg))
                cell.get_text().set_fontweight("bold")
            if j == 1:
                cell.set_facecolor(colors.get(body[i - 1][1], "#6b5d1f"))
                cell.get_text().set_fontweight("bold")
            if j == 2:
                cell.get_text().set_fontweight("bold")
    fig.suptitle(f"Raport săptămânal - săptămâna încheiată {anchor}", color=fg, fontsize=14,
                 fontweight="bold", x=0.015, ha="left")
    foot = ("VWAP = preț mediu ponderat cu volumul pe săptămână; 1 lună / 3 luni = randament total cu dividende (21 / 63 ședințe); "
            "Vol rel. = volum săptămână / medie 20 ședințe.\nSemnale după reguli tehnice + poziția ta; nu sunt recomandări de investiții.")
    if warning:
        foot = warning + "\n" + foot
    fig.text(0.015, 0.012, foot, color="#8b98a5", fontsize=8, va="bottom")
    fig.savefig(path, dpi=130, facecolor=bg, bbox_inches="tight")
    plt.close(fig)
    return True


# =============================================================================
# LOGICA BDC & NII INTEGRATĂ DIRECT ÎN SCRIPT
# =============================================================================
DEFAULT_BDCS = ("ARCC,MAIN,GAIN,GLAD,SCM,PFLT,PNNT,HRZN,GSBD,BXSL,TSLX,GBDC,TRIN,OBDC,FSK,HTGC,CGBD,NMFC,OCSL,"
                "PSEC,SLRC,CCAP,TCPC,BBDC,WHF,FDUS,CSWC,MSIF,MFIC,LRFC,PFX,OFS,SAR,RWAY,GECC,ICMB,PTMN,OXSQ,"
                "CION,KBDC,TPVG,BCSF,CPTA,OBDE")

LABELS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "expenses": ["Total Expenses", "Operating Expense"],
    "nii": ["Net Investment Income", "Net Investment Income Loss"],
    "interest": ["Interest Expense", "Interest Expense Non Operating"],
    "ebit": ["EBIT", "Operating Income"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
    "pretax": ["Pretax Income"],
    "div_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid", "Payment Of Dividends"],
    "ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "fcf": ["Free Cash Flow"],
    "capex": ["Capital Expenditure"],
    "net_debt": ["Net Debt"],
    "total_debt": ["Total Debt"],
    "cash": ["Cash And Cash Equivalents", "Cash Cash Equivalents And Federal Funds Sold"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
}

STATEMENTS = {
    "q_inc": "quarterly_income_stmt", "q_cf": "quarterly_cashflow", "q_bs": "quarterly_balance_sheet",
    "a_inc": "income_stmt", "a_cf": "cashflow", "a_bs": "balance_sheet",
}

def bdc_set():
    return {t.strip().upper() for t in (os.getenv("BDC_TICKERS") or DEFAULT_BDCS).split(",") if t.strip()}

def get_frame(obj, attr, errors):
    try:
        df = getattr(obj, attr)
    except Exception:
        df = None
    if df is None or not hasattr(df, "empty") or df.empty:
        errors.append(f"{attr}: indisponibil")
        return None
    df = df.copy()
    df.columns = pd.to_datetime(df.columns, errors="coerce")
    df = df.loc[:, df.columns.notna()].sort_index(axis=1, ascending=False)
    return df

def val(df, col, key, used=None):
    if df is None or col is None or col not in df.columns:
        return None
    idx = {str(i).strip().lower(): i for i in df.index}
    for name in LABELS[key]:
        i = idx.get(name.lower())
        if i is None:
            continue
        try:
            v = float(df.loc[i, col])
        except (TypeError, ValueError):
            continue
        if not np.isnan(v):
            if used is not None:
                used[key] = name
            return v
    return None

def align(df, col, tol_days=10):
    if df is None or len(df.columns) == 0:
        return None
    diffs = [abs((c - col).days) for c in df.columns]
    j = int(np.argmin(diffs))
    return df.columns[j] if diffs[j] <= tol_days else None

def price_at(px, d):
    s = px[px.index <= d]
    return float(s.iloc[-1]) if len(s) else None

def div_sum(divs, start, end, include_start=False):
    m = (divs.index >= start) if include_start else (divs.index > start)
    return float(divs[m & (divs.index <= end)].sum())

def period_metrics(inc, cf, bs, col, div_ps, used):
    c_cf, c_bs = align(cf, col), align(bs, col)
    rev, exp = val(inc, col, "revenue", used), val(inc, col, "expenses", used)
    nii, approx = val(inc, col, "nii", used), False
    if nii is None and rev is not None and exp is not None:
        nii, approx = rev - abs(exp), True
        used["nii"] = "Total Revenue - Total Expenses (aproximare)"
    interest = val(inc, col, "interest", used)
    interest = abs(interest) if interest is not None else None
    ebit = val(inc, col, "ebit", used)
    ebitda = val(inc, col, "ebitda", used)
    if ebitda is None:
        pretax = val(inc, col, "pretax", used)
        if pretax is not None and interest is not None:
            ebitda = pretax + interest
            used["ebitda"] = "Pretax Income + Interest Expense (aproximare)"
    dp, dp_approx = val(cf, c_cf, "div_paid", used), False
    dp = abs(dp) if dp is not None else None
    if dp is None:
        sh = val(bs, c_bs, "shares", used)
        if sh and div_ps:
            dp, dp_approx = div_ps * sh, True
            used["div_paid"] = "dividend/actiune x nr. actiuni (aproximare)"
    fcf = val(cf, c_cf, "fcf", used)
    if fcf is None:
        ocf = val(cf, c_cf, "ocf", used)
        if ocf is not None:
            capex = val(cf, c_cf, "capex", used)
            fcf = ocf - abs(capex or 0.0)
            used["fcf"] = "Operating Cash Flow - Capex (calculat)"
    nd = val(bs, c_bs, "net_debt", used)
    if nd is None:
        td, cash = val(bs, c_bs, "total_debt", used), val(bs, c_bs, "cash", used)
        if td is not None and cash is not None:
            nd = td - cash
            used["net_debt"] = "Total Debt - Cash (calculat)"
    return {"nii": nii, "nii_approx": approx, "interest": interest, "ebit": ebit, "ebitda": ebitda,
            "div_paid": dp, "div_approx": dp_approx, "fcf": fcf, "net_debt": nd}

def ratios(m, annualize=1):
    nii, dp, fcf, ie = m.get("nii"), m.get("div_paid"), m.get("fcf"), m.get("interest")
    out = {}
    out["div_nii"] = dp / nii * 100 if (dp is not None and nii is not None and nii > 0) else None
    out["div_fcf"] = dp / fcf * 100 if (dp is not None and fcf is not None and fcf > 0) else None
    out["fcf_neg"] = fcf is not None and fcf <= 0
    if nii is not None and ie and ie > 0:
        out["cov"] = (nii + ie) / ie
    elif m.get("ebit") is not None and ie and ie > 0:
        out["cov"] = m["ebit"] / ie
    else:
        out["cov"] = None
    eb, nd = m.get("ebitda"), m.get("net_debt")
    out["nd_ebitda"] = nd / (eb * annualize) if (eb is not None and eb > 0 and nd is not None) else None
    return out

def ssum(values):
    return None if any(v is None for v in values) else float(sum(values))

def collect_bdc(sym, name, anchor):
    anchor = pd.Timestamp(anchor)
    d = {"symbol": sym, "name": name, "errors": [], "used": {}, "frames": {}}
    obj = yf.Ticker(sym)
    try:
        h = obj.history(period="3y", auto_adjust=False, actions=True)
        h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
        h = h[h.index <= anchor]
        px = h["Close"].dropna()
        divs = h["Dividends"][h["Dividends"] > 0] if "Dividends" in h else pd.Series(dtype=float)
    except Exception:
        d["errors"].append("istoric de pret/dividende indisponibil")
        px, divs = pd.Series(dtype=float), pd.Series(dtype=float)

    fr = {k: get_frame(obj, attr, d["errors"]) for k, attr in STATEMENTS.items()}
    d["frames"] = {k: ([str(i) for i in v.index] if v is not None else None) for k, v in fr.items()}
    last = px.index[-1] if len(px) else anchor

    monthly = []
    for k in range(12):
        ref = anchor - pd.DateOffset(months=k)
        m_start = ref.replace(day=1)
        m_end = min(m_start + pd.offsets.MonthEnd(0), anchor)
        price = price_at(px, m_end)
        ttm = div_sum(divs, m_end - pd.DateOffset(months=12), m_end)
        monthly.append({"label": f"{m_start:%Y-%m}", "price": price,
                        "div_ps": div_sum(divs, m_start, m_end, include_start=True),
                        "yield": ttm / price * 100 if (price and ttm) else None})
    d["monthly"] = monthly

    quarters = []
    q_inc, q_cf, q_bs = fr["q_inc"], fr["q_cf"], fr["q_bs"]
    if q_inc is not None:
        for col in list(q_inc.columns)[:5]:
            div_ps = div_sum(divs, col - pd.DateOffset(months=3), col)
            used = {}
            m = period_metrics(q_inc, q_cf, q_bs, col, div_ps, used)
            r = ratios(m, annualize=4)
            price = price_at(px, col)
            ttm = div_sum(divs, col - pd.DateOffset(months=12), col)
            quarters.append({"label": f"T{(col.month - 1) // 3 + 1} {col.year}", "end": col, "price": price,
                             "div_ps": div_ps, "yield": ttm / price * 100 if (price and ttm) else None,
                             **m, **r})
            if not d["used"]:
                d["used"] = used
    d["quarters"] = quarters

    ttm_row = {}
    if len(quarters) >= 4:
        q4 = quarters[:4]
        agg = {k: ssum([q[k] for q in q4]) for k in ("nii", "interest", "ebitda", "div_paid", "fcf", "ebit")}
        agg["net_debt"] = q4[0]["net_debt"]
        agg["nii_approx"] = any(q["nii_approx"] for q in q4)
        agg["div_approx"] = any(q["div_approx"] for q in q4)
        ttm_row = {**agg, **ratios(agg, annualize=1)}
    price_now = price_at(px, last)
    ttm_div = div_sum(divs, last - pd.DateOffset(months=12), last)
    ttm_row.update({"label": "12L (TTM)", "price": price_now, "div_ps": ttm_div,
                    "yield": ttm_div / price_now * 100 if (price_now and ttm_div) else None})
    d["ttm"] = ttm_row

    prev = div_sum(divs, last - pd.DateOffset(months=24), last - pd.DateOffset(months=12))
    has_hist = len(px) and px.index[0] <= last - pd.DateOffset(months=23)
    d["div_change"] = (ttm_div / prev - 1) * 100 if (has_hist and prev > 0) else None

    annual = []
    a_inc, a_cf, a_bs = fr["a_inc"], fr["a_cf"], fr["a_bs"]
    if a_inc is not None:
        for col in list(a_inc.columns)[:4]:
            div_ps = div_sum(divs, col - pd.DateOffset(months=12), col)
            m = period_metrics(a_inc, a_cf, a_bs, col, div_ps, {})
            r = ratios(m, annualize=1)
            price = price_at(px, col)
            annual.append({"label": f"FY {col:%Y-%m}", "end": col, "price": price, "div_ps": div_ps,
                           "yield": div_ps / price * 100 if (price and div_ps) else None, **m, **r})
    d["annual"] = annual
    return d

def fundamental_signal(d):
    src = d["ttm"] if (d["ttm"].get("div_nii") is not None or d["ttm"].get("cov") is not None) else \
        (d["annual"][0] if d["annual"] else {})
    score, known, why = 0, 0, []
    dn, cov, chg, y = src.get("div_nii"), src.get("cov"), d.get("div_change"), d["ttm"].get("yield")
    if dn is not None:
        known += 1
        score += 2 if dn <= 95 else 1 if dn <= 105 else 0 if dn <= 115 else -2
        why.append(f"dividende/NII {dn:.0f}%")
    if cov is not None:
        known += 1
        score += 1 if cov >= 2.5 else 0 if cov >= 1.8 else -1 if cov >= 1.3 else -2
        why.append(f"acoperire dobânzi {cov:.1f}x")
    if chg is not None:
        known += 1
        score += -2 if chg <= -10 else -1 if chg <= -3 else 1 if chg >= 3 else 0
        why.append(f"dividend 12L {chg:+.0f}% față de anul anterior")
    if y is not None and y > 15:
        score -= 1
        why.append(f"randament {y:.1f}% (foarte mare)")
    if known < 2:
        return "DATE INSUFICIENTE", "; ".join(why) or "fără indicatori fundamentali de la Yahoo"
    label = "SOLID" if score >= 2 else "ATENȚIE" if score >= -1 else "RISC"
    return label, "; ".join(why)

def fm(v, approx=False):
    return "n/a" if v is None or pd.isna(v) else f"{v / 1e6:,.1f}{'≈' if approx else ''}"

def fp(v, nd=1):
    return "n/a" if v is None or pd.isna(v) else f"{v:.{nd}f}"

def fx(v):
    return "n/a" if v is None or pd.isna(v) else f"{v:.2f}x"

def fdiv(v):
    return "-" if v is None or pd.isna(v) or abs(v) < 1e-9 else f"{v:.3f}"

def fmoney(v):
    return "n/a" if v is None or pd.isna(v) else f"{v:,.2f}"

def table_rows_bdc(d):
    rows = [("section", ["ULTIMELE 12 LUNI"] + [""] * 9)]
    t = d["ttm"]
    fcf_txt = lambda r: "FCF<0" if r.get("fcf_neg") else fp(r.get("div_fcf"), 0)
    rows.append(("ttm", [t["label"], fmoney(t.get("price")), fdiv(t.get("div_ps")), fp(t.get("yield")),
                         fm(t.get("nii"), t.get("nii_approx")), fm(t.get("div_paid"), t.get("div_approx")),
                         fp(t.get("div_nii"), 0), fcf_txt(t), fx(t.get("nd_ebitda")), fx(t.get("cov"))]))
    for m in d["monthly"]:
        rows.append(("row", [m["label"], fmoney(m["price"]), fdiv(m["div_ps"]), fp(m["yield"])] + ["·"] * 6))
    if d["quarters"]:
        rows.append(("section", ["TRIMESTRIAL"] + [""] * 9))
        for q in d["quarters"]:
            rows.append(("row", [q["label"], fmoney(q["price"]), fdiv(q["div_ps"]), fp(q["yield"]),
                                 fm(q["nii"], q["nii_approx"]), fm(q["div_paid"], q["div_approx"]),
                                 fp(q["div_nii"], 0), fcf_txt(q), fx(q["nd_ebitda"]), fx(q["cov"])]))
    if d["annual"]:
        rows.append(("section", ["ANUAL"] + [""] * 9))
        for a in d["annual"]:
            rows.append(("row", [a["label"], fmoney(a["price"]), fdiv(a["div_ps"]), fp(a["yield"]),
                                 fm(a["nii"], a["nii_approx"]), fm(a["div_paid"], a["div_approx"]),
                                 fp(a["div_nii"], 0), fcf_txt(a), fx(a["nd_ebitda"]), fx(a["cov"])]))
    return rows

BDC_HEADER = ["Perioadă", "Preț $", "Div/acț $", "Yield %", "NII $M", "Div. plătite $M", "Div/NII %", "Div/FCF %",
              "ND/EBITDA", "Cov. dobânzi"]
SIGNAL_COLORS = {"SOLID": "#1f7a4d", "ATENȚIE": "#b58a1f", "RISC": "#a8322d", "DATE INSUFICIENTE": "#3b4654"}

def make_detail_image_bdc(d, label, why, tech, anchor, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = table_rows_bdc(d)
    bg, fg, grid = "#0f1720", "#e8edf2", "#2a3644"
    n = len(rows)
    fig, ax = plt.subplots(figsize=(13, 1.9 + 0.285 * n), facecolor=bg)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.09)
    ax.axis("off")
    tbl = ax.table(cellText=[r[1] for r in rows], colLabels=BDC_HEADER, loc="upper center", cellLoc="center",
                   colWidths=[0.17, 0.08, 0.08, 0.07, 0.09, 0.11, 0.09, 0.09, 0.10, 0.12])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.5)
    tbl.scale(1, 1.25)
    for (i, j), cell in tbl.get_celld().items():
        cell.set_edgecolor(grid)
        cell.get_text().set_color(fg)
        if i == 0:
            cell.set_facecolor("#1d2a38")
            cell.get_text().set_fontweight("bold")
            continue
        kind = rows[i - 1][0]
        text = rows[i - 1][1][j]
        if kind == "section":
            cell.set_facecolor("#24364a")
            cell.get_text().set_fontweight("bold")
            if j != 0:
                cell.get_text().set_text("")
            else:
                cell.get_text().set_ha("left")
                cell._loc = "left"
            continue
        cell.set_facecolor("#1b2b3d" if kind == "ttm" else (bg if i % 2 else "#141e29"))
        if kind == "ttm":
            cell.get_text().set_fontweight("bold")
        if j == 6 and text not in ("n/a", "·", "-"):
            try:
                v = float(text.replace("≈", ""))
                cell.get_text().set_color("#4cc38a" if v <= 100 else "#ff7b72" if v > 110 else "#e3b341")
            except ValueError:
                pass
        if j == 9 and text not in ("n/a", "·"):
            try:
                v = float(text.replace("x", ""))
                cell.get_text().set_color("#4cc38a" if v >= 2.5 else "#ff7b72" if v < 1.5 else fg)
            except ValueError:
                pass
    fig.text(0.015, 0.955, f"{d['symbol']} - {d['name']}", color=fg, fontsize=14, fontweight="bold", va="center")
    fig.text(0.985, 0.955, f"Semnal fundamental: {label}", color="white", fontsize=12, fontweight="bold",
             ha="right", va="center",
             bbox=dict(boxstyle="round,pad=0.35", facecolor=SIGNAL_COLORS.get(label, "#3b4654"), edgecolor="none"))
    fig.text(0.015, 0.905, f"{why}   |   Semnal tehnic (trend): {tech or 'n/a'}   |   săptămâna încheiată {anchor}",
             color="#aab6c2", fontsize=9, va="center")
    fig.text(0.015, 0.012,
             "≈ = aproximare (NII = venit total - cheltuieli totale). "
             "La BDC indicatorul relevant este NII (nu AFFO care este pentru REIT-uri). Nu sunt recomandări.",
             color="#8b98a5", fontsize=7, va="bottom", wrap=True)
    fig.savefig(path, dpi=130, facecolor=bg, bbox_inches="tight")
    plt.close(fig)

def make_summary_image_bdc(results, tech, anchor, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    bg, fg, grid = "#0f1720", "#e8edf2", "#2a3644"
    header = ["Ticker", "Semnal fundamental", "Yield %", "Div/NII % (12L)", "Cov. dobânzi", "ND/EBITDA",
              "Dividend 12L vs an anterior", "Semnal tehnic"]
    body = []
    for d in results:
        t = d["ttm"]
        src = t if t.get("div_nii") is not None or t.get("cov") is not None else (d["annual"][0] if d["annual"] else {})
        chg = d.get("div_change")
        body.append([d["symbol"], d["signal"], fp(t.get("yield")), fp(src.get("div_nii"), 0), fx(src.get("cov")),
                     fx(src.get("nd_ebitda")), "n/a" if chg is None else f"{chg:+.0f}%", tech.get(d["symbol"], "n/a")])
    n = len(body)
    fig, ax = plt.subplots(figsize=(13, 1.7 + 0.5 * n), facecolor=bg)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.84, bottom=0.12)
    ax.axis("off")
    tbl = ax.table(cellText=body, colLabels=header, loc="center", cellLoc="center",
                   colWidths=[0.08, 0.19, 0.08, 0.13, 0.11, 0.10, 0.17, 0.14])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(11)
    tbl.scale(1, 1.7)
    for (i, j), cell in tbl.get_celld().items():
        cell.set_edgecolor(grid)
        cell.get_text().set_color(fg)
        if i == 0:
            cell.set_facecolor("#1d2a38")
            cell.get_text().set_fontweight("bold")
        else:
            cell.set_facecolor(bg if i % 2 else "#141e29")
            if j == 0:
                cell.get_text().set_fontweight("bold")
            if j == 1:
                cell.set_facecolor(SIGNAL_COLORS.get(body[i - 1][1], "#3b4654"))
                cell.get_text().set_fontweight("bold")
    fig.suptitle(f"BDC-uri din portofoliu - săptămâna încheiată {anchor}", color=fg, fontsize=14,
                 fontweight="bold", x=0.015, ha="left")
    fig.text(0.015, 0.012, "Semnal fundamental bazat pe NII și acoperirea dividendelor. Nu sunt recomandări.", color="#8b98a5", fontsize=8, va="bottom")
    fig.savefig(path, dpi=130, facecolor=bg, bbox_inches="tight")
    plt.close(fig)

def run_bdc(held, tech, anchor, out_dir):
    bdcs = bdc_set()
    mine = [(s, n) for s, n in held if s.upper() in bdcs]
    if not mine:
        return {"markdown": [], "images": []}
    out_dir = Path(out_dir)
    results = []
    for sym, name in mine:
        try:
            d = collect_bdc(sym, name, anchor)
        except Exception as e:
            d = {"symbol": sym, "name": name, "errors": [f"eroare: {e.__class__.__name__}"], "used": {}, "frames": {},
                 "monthly": [], "quarters": [], "annual": [], "ttm": {}, "div_change": None}
        d["signal"], d["reason"] = fundamental_signal(d)
        results.append(d)

    images = []
    try:
        summary = out_dir / "bdc_summary.png"
        make_summary_image_bdc(results, tech, anchor, summary)
        images.append(summary)
        for d in results:
            p = out_dir / f"bdc_{d['symbol']}.png"
            make_detail_image_bdc(d, d["signal"], d["reason"], tech.get(d["symbol"]), anchor, p)
            images.append(p)
    except Exception:
        pass

    lines = ["", "## 🏦 BDC-uri din portofoliu", "",
             "| Ticker | Semnal fundamental | Yield % | Div/NII % (12L) | Cov. dobânzi | ND/EBITDA | Dividend 12L vs an anterior | Semnal tehnic |",
             "|:---|:---|---:|---:|---:|---:|---:|:---|"]
    for d in results:
        t = d["ttm"]
        src = t if t.get("div_nii") is not None or t.get("cov") is not None else (d["annual"][0] if d["annual"] else {})
        chg = d.get("div_change")
        lines.append(f"| **{d['symbol']}** | **{d['signal']}** | {fp(t.get('yield'))} | {fp(src.get('div_nii'), 0)} | "
                     f"{fx(src.get('cov'))} | {fx(src.get('nd_ebitda'))} | {'n/a' if chg is None else f'{chg:+.0f}%'} | "
                     f"{tech.get(d['symbol'], 'n/a')} |")
    for d in results:
        lines += ["", f"### {d['symbol']} - {d['name']}  —  {d['signal']}", f"{d['reason']}", "",
                  "| " + " | ".join(BDC_HEADER) + " |", "|:---|" + "---:|" * (len(BDC_HEADER) - 1)]
        for kind, cells in table_rows_bdc(d):
            if kind == "section":
                lines.append(f"| **{cells[0]}** |" + " |" * (len(BDC_HEADER) - 1))
            else:
                lines.append("| " + " | ".join(cells) + " |")

    return {"markdown": lines, "images": images}

def send_album(paths, caption):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return "Telegram BDC skipped: missing credentials"
    try:
        paths = [Path(p) for p in paths]
        for start in range(0, len(paths), 10):
            chunk = paths[start:start + 10]
            if len(chunk) == 1:
                with chunk[0].open("rb") as f:
                    r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                                      data={"chat_id": chat, "caption": caption}, files={"photo": f}, timeout=(15, 90))
            else:
                files, media, handles = {}, [], []
                for i, p in enumerate(chunk):
                    fh = p.open("rb")
                    handles.append(fh)
                    files[f"photo{i}"] = (p.name, fh, "image/png")
                    item = {"type": "photo", "media": f"attach://photo{i}"}
                    if i == 0 and start == 0:
                        item["caption"] = caption
                    media.append(item)
                try:
                    r = requests.post(f"https://api.telegram.org/bot{token}/sendMediaGroup",
                                      data={"chat_id": chat, "media": json.dumps(media)}, files=files, timeout=(15, 120))
                finally:
                    for fh in handles:
                        fh.close()
            if not (r.ok and r.json().get("ok")):
                return f"Telegram BDC HTTP {r.status_code}"
        return f"BDC: {len(paths)} imagini trimise"
    except Exception:
        return "Telegram BDC failed"


# =============================================================================
# MAIN SCRIPT
# =============================================================================
def main():
    OUT.mkdir(exist_ok=True)
    path = pick_portfolio_file()

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
               "price_return_pct": None, "ret_2w_pct": None, "vwap_week": None, "vs_vwap_pct": None, "ret_1m_pct": None,
               "ret_3m_pct": None, "vs_high52_pct": None, "vol_ratio": None, "adjusted_return_pct": None, "close_end": None,
               "ma_fast": None, "ma_slow": None, "rsi14": None, "excess_spy_pp": None, "trend": None,
               "value_end_estimate": None, "unrealized_pct": None, "pnl_usd": None, "hypothetical_week_price_pnl": None, "weight_used_pct": p.weight_excel_pct,
               "div_ttm_per_share": None, "next_ex_div_est": "", "next_div_est": None,
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

            vwap = vs_vwap = vs_high = vol_ratio = None
            try:
                wk_vol = h.Volume.reindex(week)
                wk_typ = ((h.High + h.Low + h.Close) / 3).reindex(week)
                if wk_vol.notna().all() and wk_typ.notna().all() and wk_vol.sum() > 0:
                    vwap = float((wk_typ * wk_vol).sum() / wk_vol.sum())
                    vs_vwap = (float(close.loc[end]) / vwap - 1) * 100
                vol20 = float(h.Volume.loc[:end].tail(20).mean())
                if vol20 > 0 and wk_vol.notna().all():
                    vol_ratio = float(wk_vol.mean() / vol20)
                vs_high = (float(close.loc[end]) / float(close.tail(252).max()) - 1) * 100
            except Exception:
                pass

            def period_return(back):
                if len(adjusted) <= back:
                    return None
                a0 = float(adjusted.iloc[-1 - back])
                return (float(adjusted.iloc[-1]) / a0 - 1) * 100 if a0 > 0 else None
            ret1m, ret3m = period_return(21), period_return(63)
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
                nxt, amt = estimate_next_ex_dividend(divs, end)
                if nxt is not None and (nxt - end).days <= 10:
                    row["next_ex_div_est"] = str(nxt.date())
                    row["next_div_est"] = amt

            pnl = float(p.Volume * (close.loc[end] - p["Open price"])) if comparable else None
            row.update(price_return_pct=float(ret), ret_2w_pct=float(ret2), adjusted_return_pct=float(ar),
                close_end=float(close.loc[end]), ma_fast=float(fast), ma_slow=float(slow), rsi14=float(rsi),
                excess_spy_pp=excess, trend=trend_label(close.loc[end], fast, slow),
                vwap_week=vwap, vs_vwap_pct=vs_vwap, ret_1m_pct=ret1m, ret_3m_pct=ret3m,
                vs_high52_pct=vs_high, vol_ratio=vol_ratio,
                value_end_estimate=float(p.Volume * close.loc[end]) if comparable else None,
                unrealized_pct=float((close.loc[end] / p["Open price"] - 1) * 100) if comparable else None,
                pnl_usd=pnl,
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
            pos_div = r["shares_excel"] * r["next_div_est"]
            why = why.rstrip(".") + "."
            why += (f" Atenție: ex-dividend estimat ~{r['next_ex_div_est']} (~{r['next_div_est']:.2f}$/acțiune, "
                    f"~{pos_div:,.0f}$ pentru toată poziția): dacă vinzi înainte, nu îl încasezi.")
        r.update(signal_tehnic=tech, signal_final=final, motiv=why)
        if r["weight_used_pct"] > CONCENTRATION_PCT:
            r["flags"] = (r["flags"] + "; " if r["flags"] else "") + \
                f"Pondere {r['weight_used_pct']:.1f}% peste {CONCENTRATION_PCT:.0f}% (doar avertisment)"

    result = pd.DataFrame(rows)
    result.to_csv(OUT / "weekly_signals.csv", index=False)

    f = lambda x, nd=2: "n/a" if x is None or pd.isna(x) else f"{x:.{nd}f}"
    fm = lambda x: "n/a" if x is None or pd.isna(x) else ("0" if round(x) == 0 else f"{x:+,.0f}")
    fs = lambda x, nd=1: "n/a" if x is None or pd.isna(x) else f"{x:+.{nd}f}"
    fx = lambda x: "n/a" if x is None or pd.isna(x) else f"{x:.2f}x"
    lines = [
        "# 📊 Raport săptămânal portofoliu",
        "",
        f"Săptămâna completă încheiată la {anchor}; ședințe {week[0].date()} - {end.date()}.",
        f"Randamente: închidere {base.date()} -> închidere {end.date()}.",
        f"Excel: {path.name}; dată declarată: {stamp}.",
        f"Poziții cu date valide: {available}/{len(rows)}.",
    ]
    if warning:
        lines += ["", f"⚠️ {warning}"]

    lines += ["", "## Semnale (trend săptămânal + poziția ta)", "",
              "| Trend | Semnal tehnic | Semnal final | Ticker | Săpt % | 2 săpt % | 1 lună % | 3 luni % | RSI | vs VWAP % | vs max 52s % | Vol rel. |",
              "|:---|:---|:---|:---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['trend'] or 'n/a'} | {r['signal_tehnic']} | **{r['signal_final']}** | **{r['ticker']}** | "
                     f"{fs(r['price_return_pct'])} | {fs(r['ret_2w_pct'])} | {fs(r['ret_1m_pct'])} | {fs(r['ret_3m_pct'])} | "
                     f"{f(r['rsi14'], 0)} | {fs(r['vs_vwap_pct'])} | {fs(r['vs_high52_pct'])} | {fx(r['vol_ratio'])} |")

    lines += ["", "## Detalii pe companii", ""]
    for r in rows:
        div_txt = ""
        if r["div_ttm_per_share"] is not None:
            div_txt = f" Dividende ultimele 12 luni: {r['div_ttm_per_share']:.2f}$/acțiune."
        lines += [
            f"### {r['ticker']}  —  {r['signal_final']}",
            f"Poziție: {r['shares_excel']} acțiuni; cost mediu {r['average_cost_excel']:.2f} USD; preț final {f(r['close_end'])}.",
            f"Indicatori: VWAP săptămânal {f(r['vwap_week'])} (prețul e {fs(r['vs_vwap_pct'])}% față de VWAP); randament 1 lună {fs(r['ret_1m_pct'])}%, "
            f"3 luni {fs(r['ret_3m_pct'])}% (cu dividende); {fs(r['vs_high52_pct'])}% față de maximul pe 52 săptămâni; "
            f"volum săptămână {fx(r['vol_ratio'])} față de media pe 20 ședințe.",
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

    # Generare secțiune BDC direct din scriptul unificat
    bdc_images = []
    try:
        held = [(p.symbol, str(p.get("Instrument/Position", p.symbol))) for _, p in positions.iterrows()]
        tech_by_ticker = {r["ticker"]: r["signal_final"] for r in rows}
        bdc_res = run_bdc(held, tech_by_ticker, anchor, OUT)
        lines += bdc_res["markdown"]
        bdc_images = bdc_res["images"]
    except Exception as e:
        lines += ["", "## 🏦 BDC-uri din portofoliu", f"Tabelul BDC nu s-a putut genera ({e.__class__.__name__})."]

    lines += [
        "", "## Reguli și limite",
        f"- Trend CRESCĂTOR: Close > MA{FAST_MA} > MA{SLOW_MA}. DESCRESCĂTOR: Close < MA{FAST_MA} < MA{SLOW_MA}. Altfel MIXT.",
        "- Indicatorul specific pentru BDC este NII (Net Investment Income), în timp ce pentru REIT-uri se folosește AFFO.",
    ]

    for name in ["Analiza.md", "analiza.md", "docs/analiza.md", "docs/Analiza.md"]:
        ap = ROOT / name
        if ap.exists():
            text = ap.read_text(encoding="utf-8")
            m = re.search(r"Data generării:\*\*\s*`([^`]+)`", text)
            gen = f" (generat la {m.group(1)})" if m else ""
            lines += ["", f"## 📈 Context din Analiza.md{gen}", text]
            break

    report = OUT / "weekly_report.md"
    report.write_text("\n".join(lines), encoding="utf-8")

    wealth_files = export_wealthfolio(positions, anchor)

    image = OUT / "weekly_signals.png"
    statuses = []
    if make_image(rows, anchor, warning, image):
        statuses.append(send_photo(image, f"Raport săptămânal - săptămâna încheiată {anchor}"))
    else:
        statuses.append("Imagine omisă: matplotlib lipsește")
        
    if bdc_images:
        statuses.append(send_album(bdc_images, f"BDC-uri - săptămâna încheiată {anchor}"))

    if SEND_FILES:
        statuses += [send(report)] + [send(p) for p in wealth_files]
        
    (OUT / "delivery-status.txt").write_text("\n".join(statuses))
    print(f"Generated report: week ending {anchor}, valid positions {available}/{len(rows)}")

if __name__ == "__main__":
    main()
