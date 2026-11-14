"""
Tabel separat pentru BDC-urile din portofoliu (Business Development Companies).

Sursa: Yahoo Finance (yfinance). Ce se poate si ce nu se poate:
- Dividendele, pretul si randamentul (dividend anual / pret) sunt LUNARE (ultimele 12 luni).
- Situatiile financiare (NII, dividende platite, flux de numerar, datorie, dobanzi) apar la BDC DOAR trimestrial
  si anual; nu exista date financiare lunare. Randul "12L (TTM)" aduna ultimele 4 trimestre.
- AFFO este un indicator de REIT; la BDC echivalentul este NII (venitul net din investitii).
- NII exact lipseste adesea la Yahoo: atunci se aproximeaza ca venit total - cheltuieli totale (marcat cu ≈).
- FCF si Net debt/EBITDA nu sunt indicatori standard la BDC (fluxul operational include achizitiile de credite,
  iar dobanda e cost de baza al afacerii). Se afiseaza fiindca au fost ceruti; indicatorul relevant este Div/NII.
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

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


# ----------------------------------------------------------------------------- date de la Yahoo
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
    """Valoarea primei etichete gasite pentru 'key' in coloana 'col'; None daca lipseste."""
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
    """Coloana din 'df' cea mai apropiata de data 'col' (situatiile pot avea date usor diferite)."""
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
    """Valorile unei perioade (trimestru sau an). Toate pot fi None."""
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
    """Indicatorii derivati dintr-o perioada (annualize=4 pentru EBITDA trimestrial)."""
    nii, dp, fcf, ie = m.get("nii"), m.get("div_paid"), m.get("fcf"), m.get("interest")
    out = {}
    out["div_nii"] = dp / nii * 100 if (dp is not None and nii is not None and nii > 0) else None
    out["div_fcf"] = dp / fcf * 100 if (dp is not None and fcf is not None and fcf > 0) else None
    out["fcf_neg"] = fcf is not None and fcf <= 0
    if nii is not None and ie and ie > 0:
        out["cov"] = (nii + ie) / ie                     # (NII inainte de dobanzi) / dobanzi
    elif m.get("ebit") is not None and ie and ie > 0:
        out["cov"] = m["ebit"] / ie
    else:
        out["cov"] = None
    eb, nd = m.get("ebitda"), m.get("net_debt")
    out["nd_ebitda"] = nd / (eb * annualize) if (eb is not None and eb > 0 and nd is not None) else None
    return out


def ssum(values):
    return None if any(v is None for v in values) else float(sum(values))


def collect(sym, name, anchor):
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

    # ---- lunar (ultimele 12 luni): pret, dividend, randament = dividend ultimele 12 luni / pret
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

    # ---- trimestrial
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

    # ---- TTM = ultimele 4 trimestre
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

    # modificarea dividendului: ultimele 12 luni fata de cele dinainte (necesita 24 luni de istoric)
    prev = div_sum(divs, last - pd.DateOffset(months=24), last - pd.DateOffset(months=12))
    has_hist = len(px) and px.index[0] <= last - pd.DateOffset(months=23)
    d["div_change"] = (ttm_div / prev - 1) * 100 if (has_hist and prev > 0) else None

    # ---- anual
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


# ----------------------------------------------------------------------------- semnal fundamental
def fundamental_signal(d):
    """SOLID / ATENȚIE / RISC din acoperirea dividendului de NII, acoperirea dobanzilor, evolutia dividendului."""
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


# ----------------------------------------------------------------------------- formatare
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


def table_rows(d):
    """Randurile tabelului: (tip, [celule]); tip = 'section' | 'row' | 'ttm'."""
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


HEADER = ["Perioadă", "Preț $", "Div/acț $", "Yield %", "NII $M", "Div. plătite $M", "Div/NII %", "Div/FCF %",
          "ND/EBITDA", "Cov. dobânzi"]
SIGNAL_COLORS = {"SOLID": "#1f7a4d", "ATENȚIE": "#b58a1f", "RISC": "#a8322d", "DATE INSUFICIENTE": "#3b4654"}


# ----------------------------------------------------------------------------- imagini
def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def make_detail_image(d, label, why, tech, anchor, path):
    plt = _plt()
    rows = table_rows(d)
    bg, fg, grid = "#0f1720", "#e8edf2", "#2a3644"
    n = len(rows)
    fig, ax = plt.subplots(figsize=(13, 1.9 + 0.285 * n), facecolor=bg)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.86, bottom=0.09)
    ax.axis("off")
    tbl = ax.table(cellText=[r[1] for r in rows], colLabels=HEADER, loc="upper center", cellLoc="center",
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
        if j == 6 and text not in ("n/a", "·", "-"):          # Div/NII
            try:
                v = float(text.replace("≈", ""))
                cell.get_text().set_color("#4cc38a" if v <= 100 else "#ff7b72" if v > 110 else "#e3b341")
            except ValueError:
                pass
        if j == 9 and text not in ("n/a", "·"):                 # acoperire dobanzi
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
             "≈ = aproximare (NII = venit total - cheltuieli totale; dividende = dividend/acțiune x nr. acțiuni). "
             "Lunar: doar preț/dividend/randament (BDC raportează trimestrial). ND/EBITDA trimestrial cu EBITDA x4. Dividende = data ex-dividend. "
             "FCF și ND/EBITDA nu sunt standard la BDC. AFFO nu se aplică (la BDC: NII). Nu sunt recomandări.",
             color="#8b98a5", fontsize=7, va="bottom", wrap=True)
    fig.savefig(path, dpi=130, facecolor=bg, bbox_inches="tight")
    plt.close(fig)


def make_summary_image(results, tech, anchor, path):
    plt = _plt()
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
    fig.text(0.015, 0.012,
             "Semnal fundamental din: dividende/NII, acoperirea dobânzilor, evoluția dividendului (reguli în raportul .md). "
             "Datele financiare vin de la Yahoo Finance și pot lipsi sau fi aproximative. Nu sunt recomandări de investiții.",
             color="#8b98a5", fontsize=8, va="bottom")
    fig.savefig(path, dpi=130, facecolor=bg, bbox_inches="tight")
    plt.close(fig)


# ----------------------------------------------------------------------------- markdown, diagnostic, Telegram
def markdown(results, tech, anchor):
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
                  "| " + " | ".join(HEADER) + " |", "|:---|" + "---:|" * (len(HEADER) - 1)]
        for kind, cells in table_rows(d):
            if kind == "section":
                lines.append(f"| **{cells[0]}** |" + " |" * (len(HEADER) - 1))
            else:
                lines.append("| " + " | ".join(cells) + " |")
        if d["errors"]:
            lines.append("")
            lines.append("_Date indisponibile la Yahoo: " + "; ".join(d["errors"]) + "._")
    lines += ["", "**Reguli semnal fundamental:** dividende/NII ≤95% = +2, ≤105% = +1, ≤115% = 0, peste = -2; "
              "acoperirea dobânzilor ≥2.5x = +1, ≥1.8x = 0, ≥1.3x = -1, sub = -2; dividendul pe 12 luni față de anul anterior "
              "≤-10% = -2, ≤-3% = -1, ≥+3% = +1; randament peste 15% = -1. Total ≥2 = SOLID, între -1 și 1 = ATENȚIE, "
              "≤-2 = RISC; sub 2 indicatori disponibili = DATE INSUFICIENTE.",
              "**Limite:** NII exact lipsește adesea la Yahoo (≈ = venit total - cheltuieli totale). Datele financiare sunt "
              "trimestriale/anuale, nu lunare. FCF și ND/EBITDA nu sunt standard la BDC. AFFO este un indicator de REIT; "
              "la BDC echivalentul este NII. Dividendele sunt la data ex-dividend; un dividend special poate distorsiona "
              "modificarea pe 12 luni."]
    return lines


def write_diagnostics(results, path):
    out = []
    for d in results:
        out.append(f"=== {d['symbol']} ===")
        out.append("erori: " + ("; ".join(d["errors"]) or "niciuna"))
        out.append("etichete folosite (ultimul trimestru): " + json.dumps(d["used"], ensure_ascii=False))
        for k, v in d["frames"].items():
            out.append(f"{k}: " + ("indisponibil" if v is None else ", ".join(v)))
        out.append("")
    Path(path).write_text("\n".join(out), encoding="utf-8")


def send_album(paths, caption):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return "Telegram BDC skipped: missing credentials"
    try:
        paths = [Path(p) for p in paths]
        for start in range(0, len(paths), 10):                       # albumele au maximum 10 imagini
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
        return "Telegram BDC failed; imaginile raman salvate"


# ----------------------------------------------------------------------------- punct de intrare
def run(held, tech, anchor, out_dir):
    """held = [(ticker, nume)] pozitiile din portofoliu; tech = {ticker: semnal tehnic}.
    Intoarce {'markdown': [...], 'images': [Path, ...]} (gol daca nu ai BDC-uri)."""
    bdcs = bdc_set()
    mine = [(s, n) for s, n in held if s.upper() in bdcs]
    if not mine:
        return {"markdown": [], "images": []}
    out_dir = Path(out_dir)
    results = []
    for sym, name in mine:
        try:
            d = collect(sym, name, anchor)
        except Exception as e:
            d = {"symbol": sym, "name": name, "errors": [f"eroare: {e.__class__.__name__}"], "used": {}, "frames": {},
                 "monthly": [], "quarters": [], "annual": [], "ttm": {}, "div_change": None}
        d["signal"], d["reason"] = fundamental_signal(d)
        results.append(d)
    write_diagnostics(results, out_dir / "bdc_diagnostics.txt")

    images = []
    try:
        summary = out_dir / "bdc_summary.png"
        make_summary_image(results, tech, anchor, summary)
        images.append(summary)
        for d in results:
            p = out_dir / f"bdc_{d['symbol']}.png"
            make_detail_image(d, d["signal"], d["reason"], tech.get(d["symbol"]), anchor, p)
            images.append(p)
    except Exception:
        pass            # fara matplotlib raman doar sectiunea din raportul .md
    return {"markdown": markdown(results, tech, anchor), "images": images}
