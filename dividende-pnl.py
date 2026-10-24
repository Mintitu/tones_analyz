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

    # Dividende pe companie
    div_comp = divs_only.groupby('Ticker')['Amount'].sum().reset_index().rename(columns={'Amount': 'Gross ($)'})
    tax_comp = tax_only.groupby('Ticker')['Amount'].sum().reset_index().rename(columns={'Amount': 'Tax ($)'})
    div_summary = pd.merge(div_comp, tax_comp, on='Ticker', how='outer').fillna(0)
    div_summary['Net ($)'] = div_summary['Gross ($)'] + div_summary['Tax ($)']
    div_summary = div_summary.sort_values(by='Net ($)', ascending=False)

    # Statistica lunara a incasarilor
    divs_only['Month'] = divs_only['Time'].dt.to_period('M').astype(str)
    tax_only['Month'] = tax_only['Time'].dt.to_period('M').astype(str)
    
    monthly_gross = divs_only.groupby('Month')['Amount'].sum().reset_index().rename(columns={'Amount': 'Gross ($)'})
    monthly_tax = tax_only.groupby('Month')['Amount'].sum().reset_index().rename(columns={'Amount': 'Tax ($)'})
    
    monthly_divs = pd.merge(monthly_gross, monthly_tax, on='Month', how='outer').fillna(0)
    monthly_divs['Net ($)'] = monthly_divs['Gross ($)'] + monthly_divs['Tax ($)']
    monthly_divs = monthly_divs.sort_values(by='Month', ascending=False)

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

    # Generare text raport
    md_content = f"""📈 *Raport Capital Gain & Dividende*

📊 *Summary General*
• *Total Dividende Brute:* ${divs_only['Amount'].sum():,.2f}
• *Total Impozite Reținute:* ${tax_only['Amount'].sum():,.2f}
• *Total Dividende Nete:* ${divs_only['Amount'].sum() + tax_only['Amount'].sum():,.2f}
• *Capital Gain Realizat:* ${df_close['Profit/Loss'].sum():,.2f}
• *Capital Gain Nerealizat:* ${cg_open['Net Profit'].sum():,.2f}

📅 *Încasări Lunare Dividende*
"""
    for _, row in monthly_divs.iterrows():
        md_content += f"• *{row['Month']}*: ${row['Net ($)']:,.2f} net (Brut: ${row['Gross ($)']:,.2f})\n"

    md_content += "\n🏢 *Top Dividende per Companie (Net)*\n"
    for _, row in div_summary.head(5).iterrows():
        md_content += f"• *{row['Ticker']}*: ${row['Net ($)']:,.2f}\n"

    # Salvare fisier local
    with open("Raport_Dividende.md", "w", encoding="utf-8") as f:
        f.write(md_content)

    print("Fișierul 'Raport_Dividende.md' a fost creat cu succes.")

if __name__ == "__main__":
    process_portfolio()
