import os
import glob
import pandas as pd

def process_portfolio():
    cash_files = glob.glob("*Cash*.xlsx") + glob.glob("USD_*_Cash.xlsx")
    close_files = glob.glob("*Close*.xlsx") + glob.glob("USD_*_Close.xlsx")
    open_files = glob.glob("*Open*.xlsx") + glob.glob("USD_*_Open.xlsx")

    all_xlsx = glob.glob("*.xlsx")
    if not all_xlsx:
        print("Nu s-au găsit fișiere Excel (.xlsx) în director.")
        return

    cash_file = cash_files[0] if cash_files else all_xlsx[0]
    close_file = close_files[0] if close_files else (all_xlsx[1] if len(all_xlsx) > 1 else all_xlsx[0])
    open_file = open_files[0] if open_files else (all_xlsx[2] if len(all_xlsx) > 2 else all_xlsx[0])

    # 1. Cash Operations (Dividende & Impozite)
    df_cash_raw = pd.read_excel(cash_file, skiprows=3)
    df_cash = df_cash_raw.iloc[1:].copy()
    df_cash.columns = df_cash_raw.iloc[0].values

    df_cash['Amount'] = pd.to_numeric(df_cash['Amount'], errors='coerce')
    df_cash['Time'] = pd.to_datetime(df_cash['Time'], errors='coerce')

    divs_only = df_cash[df_cash['Type'].astype(str).str.contains('Dividend', case=False, na=False)].copy()
    tax_only = df_cash[df_cash['Type'].astype(str).str.contains('Withholding tax|RO tax', case=False, na=False)].copy()

    # 2. Closed Positions (Realized CG)
    df_close_raw = pd.read_excel(close_file, skiprows=3)
    df_close = df_close_raw.iloc[1:].copy()
    df_close.columns = df_close_raw.iloc[0].values
    df_close['Profit/Loss'] = pd.to_numeric(df_close['Profit/Loss'], errors='coerce')

    # 3. Open Positions (Unrealized CG)
    df_open_raw = pd.read_excel(open_file, skiprows=9)
    df_open = df_open_raw.iloc[1:].copy()
    df_open.columns = df_open_raw.iloc[0].values
    df_open['Net Profit'] = pd.to_numeric(df_open['Net Profit'], errors='coerce')
    cg_open = df_open[df_open['Type'].isna() & df_open['Ticker'].notna()].copy()

    # 4. Creare Tabel Matrice pentru Dividende
    divs_only['Month'] = divs_only['Time'].dt.to_period('M').astype(str)
    pivot_table = divs_only.pivot_table(index='Ticker', columns='Month', values='Amount', aggfunc='sum', fill_value=0)
    
    pivot_table['Total'] = pivot_table.sum(axis=1)
    pivot_table = pivot_table.sort_values(by='Total', ascending=False)
    
    # Top companii pentru Telegram (fara coloana Total din matricea de export)
    top_companies = pivot_table['Total'].copy()
    pivot_table = pivot_table.drop(columns=['Total'])

    months = sorted(pivot_table.columns)
    pivot_table = pivot_table[months]

    # --- 1. Versiunea Markdown completă (pentru GitHub - tabel matrice frumos) ---
    md_content = f"""📈 **Dividende aferente anului 2026**

📊 **Summary General**
• **Total Dividende Brute:** `${divs_only['Amount'].sum():,.2f}`
• **Total Impozite Reținute:** `${tax_only['Amount'].sum():,.2f}`
• **Total Dividende Nete:** `${divs_only['Amount'].sum() + tax_only['Amount'].sum():,.2f}`
• **Capital Gain Realizat:** `${df_close['Profit/Loss'].sum():,.2f}`
• **Capital Gain Nerealizat:** `${cg_open['Net Profit'].sum():,.2f}`

---
📅 **Matrice Detaliată pe Luni și Companii**

| Companie / Lună | """ + " | ".join(months) + " | Total Anual |" + "\n"
    md_content += "| :--- | " + " | ".join([":---:" for _ in months]) + " | :---: |" + "\n"

    for ticker, row in pivot_table.iterrows():
        row_total = row.sum()
        row_str = f"| **{ticker}** | " + " | ".join([f"${val:,.1f}" if val > 0 else "-" for val in row]) + f" | **${row_total:,.1f}** |"
        md_content += row_str + "\n"

    with open("Dividende.md", "w", encoding="utf-8") as f:
        f.write(md_content)

    # --- 2. Versiunea Curată pentru Telegram (cu iconițe și doar totalul pe companie) ---
    txt_content = f"""📊 **Dividende aferente anului 2026**

💰 **Summary General:**
• **Brute:** `${divs_only['Amount'].sum():,.2f}`
• **Impozite:** `${tax_only['Amount'].sum():,.2f}`
• **Nete:** `${divs_only['Amount'].sum() + tax_only['Amount'].sum():,.2f}`
• **Capital Realizat:** `${df_close['Profit/Loss'].sum():,.2f}`

🏢 **Top Încasări per Companie:**
"""
    icons = ["🥇", "🥈", "🥉", "🏅", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹"]
    for idx, (ticker, total_val) in enumerate(top_companies.items()):
        icon = icons[idx] if idx < len(icons) else "🔹"
        txt_content += f"{icon} **{ticker}**: `${total_val:,.2f}`\n"

    with open("DividendeTG.txt", "w", encoding="utf-8") as f:
        f.write(txt_content)

    print("Fișierele 'Dividende.md' și 'DividendeTG.txt' au fost generate cu succes.")

if __name__ == "__main__":
    process_portfolio()
