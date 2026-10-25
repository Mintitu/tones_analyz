"""
Incarcare comuna pentru exporturile XTB (Closed Positions, Cash Operations, Open Positions).

- Gaseste foile dupa titlu (nu dupa numele fisierului sau pozitia lor).
- Merge si cu un singur fisier cu 3 foi, si cu 3 fisiere separate.
- Daca acelasi cont apare in mai multe exporturi (re-exportari), il pastreaza doar pe cel mai nou,
  ca sa nu se numere de doua ori.
"""
import glob
import os

import pandas as pd

KINDS = {
    "closed": ("closed positions", {"Ticker", "Profit/Loss"}),
    "cash": ("cash operations", {"Type", "Amount"}),
    "open": ("open positions", {"Ticker", "Net Profit"}),
}
STAMP_LABELS = ("data as of", "date to")   # randul cu data raportului


def excel_to_datetime(value):
    """Valoare din Excel (data reala sau numar serial) -> Timestamp."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NaT
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return pd.to_datetime(value, unit="D", origin="1899-12-30", errors="coerce")
    return pd.to_datetime(value, errors="coerce")


def to_datetime_series(series):
    return pd.to_datetime(series.map(excel_to_datetime), errors="coerce")


def _detect_kind(title, sheet_name, raw):
    name = sheet_name.strip().lower()
    for kind, (label, cols) in KINDS.items():
        if label in (title, name):
            return kind
    for kind, key in (("closed", "closed"), ("cash", "cash"), ("open", "open")):
        if key in name:
            return kind
    return None


def _find_header(raw, needed):
    for idx in range(min(len(raw), 30)):
        values = {str(v).strip() for v in raw.iloc[idx].values if pd.notna(v)}
        if needed <= values:
            return idx
    return None


def _scan():
    found = {k: [] for k in KINDS}
    for path in sorted(set(glob.glob("*.xlsx"))):
        try:
            xls = pd.ExcelFile(path)
        except Exception as e:
            print(f"Nu pot deschide {path}: {e.__class__.__name__}")
            continue
        for sheet in xls.sheet_names:
            raw = pd.read_excel(xls, sheet_name=sheet, header=None)
            if raw.empty:
                continue
            title = str(raw.iloc[1, 0]).strip().lower() if len(raw) > 1 else ""
            kind = _detect_kind(title, sheet, raw)
            if not kind:
                continue
            h = _find_header(raw, KINDS[kind][1])
            if h is None:
                continue

            account = str(raw.iloc[0, 1]).strip() if raw.shape[1] > 1 else path
            stamp = pd.NaT
            for i in range(min(h, 8)):
                first = str(raw.iloc[i, 0]).strip().lower()
                if first.startswith(STAMP_LABELS) and raw.shape[1] > 1:
                    stamp = excel_to_datetime(raw.iloc[i, 1])

            df = raw.iloc[h + 1:].copy()
            df.columns = raw.iloc[h].values
            df = df.loc[:, df.columns.notna()].reset_index(drop=True)
            found[kind].append({
                "path": path, "sheet": sheet, "account": account,
                "stamp": stamp, "mtime": os.path.getmtime(path), "df": df,
            })
    return found


_CACHE = None


def load(kind):
    """Returneaza un DataFrame pentru 'closed', 'cash' sau 'open' (cel mai nou export per cont)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = _scan()
    best = {}
    for c in _CACHE[kind]:
        key = c["account"]
        rank = (c["stamp"] if pd.notna(c["stamp"]) else pd.Timestamp.min, c["mtime"])
        if key not in best or rank > best[key][0]:
            best[key] = (rank, c)
    if not best:
        raise SystemExit(f"Eroare: nu am gasit in fisierele .xlsx foaia '{KINDS[kind][0]}'.")
    for _, c in best.values():
        print(f"[{kind}] folosesc {c['path']} (foaia '{c['sheet']}', cont {c['account']})")
    return pd.concat([c["df"] for _, c in best.values()], ignore_index=True)
