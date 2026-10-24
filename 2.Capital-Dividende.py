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

    # 4. Creare Tabel Matrice (Companii în stânga, Luni sus) pentru Dividende Nete
    # Pentru a calcula NET pe lună și companie, combinăm sumele brute și taxele per tranzacție sau facem pivot simplu pe Brut/Net
    # Aici calculam direct dividendele brute pe companie si luna (sau putem face net scăzând taxele aferente)
    divs_only['Month'] = divs_only['Time'].dt.to_period('M').astype(str)
    
    # Facem un tabel pivot: Linii = Ticker, Coloane = Month, Valoare = Suma Amount (Net sau Brut)
    # Pentru a fi siguri de net, calculam net per inregistrare daca este posibil sau folosim brutul incasat
    pivot_table = divs_only.pivot_table(index='Ticker', columns='Month', values='Amount', aggfunc='sum', fill_value=0)
    
    # Sortam companiile după totalul încasat (cele mai mari sus)
    pivot_table['Total'] = pivot_table.sum(axis=1)
    pivot_table = pivot_table.sort_values(by='Total', ascending=False)
    pivot_table = pivot_table.drop(columns=['Total'])

    # Sortam lunile cronologic de la stanga la dreapta (cele mai vechi spre cele mai noi sau invers)
    months = sorted(pivot_table.columns)
    pivot_table = pivot_table[months]

    # Generare text raport Markdown structurat frumos în tabel
    md_content = f"""📈 **Raport Portofoliu & Dividende**

📊 **Summary General**
• **Total Dividende Brute:** `${divs_only['Amount'].sum():,.2f}`
• **Total Impozite Reținute:** `${tax_only['Amount'].sum():,.2f}`
• **Total Dividende Nete:** `${divs_only['Amount'].sum() + tax_only['Amount'].sum():,.2f}`
• **Capital Gain Realizat:** `${df_close['Profit/Loss'].sum():,.2f}`
• **Capital Gain Nerealizat:** `${cg_open['Net Profit'].sum():,.2f}`

---
📅 **Matrice Dividende (Companii vs. Luni)**
*(Companiile în stânga, Lunile în partea de sus)*

| Companie / Lună | """ + " | ".join(months) + " | Total Anual |" + "\n"
    
    md_content += "| :--- | " + " | ".join([":---:" for _ in months]) + " | :---: |" + "\n"

    for ticker, row in pivot_table.iterrows():
        row_total = row.sum()
        row_str = f"| **{ticker}** | " + " | ".join([f"${val:,.1f}" if val > 0 else "-" for val in row]) + f" | **${row_total:,.1f}** |"
        md_content += row_str + "\n"

    # Salvare fisier local
    with open("Capital-Dividende.md", "w", encoding="utf-8") as f:
        f.write(md_content)

    print("Fișierul 'Capital-Dividende.md' a fost creat cu succes sub formă de tabel matrice.")

if __name__ == "__main__":
    process_portfolio()