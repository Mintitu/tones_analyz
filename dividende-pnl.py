import os
import glob
import pandas as pd
import requests

def send_telegram_message(md_content):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Token-ul sau Chat ID-ul de Telegram nu sunt setate in variabilele de mediu.")
        return

    # Telegram are o limita de 4096 caractere per mesaj, asa ca trimitem primele parti sau fisierul
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    # Putem trimite un rezumat sau textul markdown (Telegram suporta un subset de Markdown)
    payload = {
        "chat_id": chat_id,
        "text": md_content[:4000], # Telegram limit
        "parse_mode": "Markdown"
    }
    
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        print("Raportul a fost trimis cu succes pe Telegram!")
    else:
        print(f"Erore la trimiterea pe Telegram: {response.text}")

def process_portfolio():
    # 1. Căutare fișiere Excel din folder
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

    # 2. Citire și procesare Cash Operations (Dividende & Impozite)
    df_cash_raw = pd.read_excel(cash_file, skiprows=3)
    df_cash = df_cash_raw.iloc[1:].copy()
    df_cash.columns = df_cash_raw.iloc[0].values

    df_cash['Amount'] = pd.to_numeric(df_cash['Amount'], errors='coerce')
    df_cash['Time'] = pd.to_datetime(df_cash['Time'], errors='coerce')

    divs_only = df_cash[df_cash['Type'].astype(str).str.contains('Dividend', case=False, na=False)].copy()
    tax_only = df_cash[df_cash['Type'].astype(str).str.contains('Withholding tax|RO tax', case=False, na=False)].copy()

    div_comp = divs_only.groupby('Ticker')['Amount'].sum().reset_index().rename(columns={'Amount': 'Gross ($)'})
    tax_comp = tax_only.groupby('Ticker')['Amount'].sum().reset_index().rename(columns={'Amount': 'Tax ($)'})
    div_summary = pd.merge(div_comp, tax_comp, on='Ticker', how='outer').fillna(0)
    div_summary['Net ($)'] = div_summary['Gross ($)'] + div_summary['Tax ($)']
    div_summary = div_summary.sort_values(by='Net ($)', ascending=False)

    divs_only['Month'] = divs_only['Time'].dt.to_period('M')
    tax_only['Month'] = tax_only['Time'].dt.to_period('M')
    
    monthly_gross = divs_only.groupby('Month')['Amount'].sum().reset_index().rename(columns={'Amount': 'Gross ($)'})
    monthly_tax = tax_only.groupby('Month')['Amount'].sum().reset_index().rename(columns={'Amount': 'Tax ($)'})
    
    monthly_divs = pd.merge(monthly_gross, monthly_tax, on='Month', how='outer').fillna(0)
    monthly_divs['Net ($)'] = monthly_divs['Gross ($)'] + monthly_divs['Tax ($)']
    monthly_divs = monthly_divs.sort_values(by='Month')

    # 3. Closed Positions
    df_close_raw = pd.read_excel(close_file, skiprows=3)
    df_close = df_close_raw.iloc[1:].copy()
    df_close.columns = df_close_raw.iloc[0].values

    df_close['Profit/Loss'] = pd.to_numeric(df_close['Profit/Loss'], errors='coerce')
    cg_realized = df_close.groupby(['Ticker', 'Instrument'])['Profit/Loss'].sum().reset_index()
    cg_realized = cg_realized.rename(columns={'Profit/Loss': 'Realized CG ($)'}).sort_values(by='Realized CG ($)', ascending=False)

    # 4. Open Positions
    df_open_raw = pd.read_excel(open_file, skiprows=9)
    df_open = df_open_raw.iloc[1:].copy()
    df_open.columns = df_open_raw.iloc[0].values

    df_open['Net Profit'] = pd.to_numeric(df_open['Net Profit'], errors='coerce')
    cg_open = df_open[df_open['Type'].isna() & df_open['Ticker'].notna()].copy()
    cg_unrealized = cg_open.groupby('Ticker')['Net Profit'].sum().reset_index().rename(columns={'Net Profit': 'Unrealized CG ($)'})

    cg_total = pd.merge(cg_realized, cg_unrealized, on='Ticker', how='outer').fillna(0)
    cg_total['Total CG ($)'] = cg_total['Realized CG ($)'] + cg_total['Unrealized CG ($)']
    cg_total = cg_total.sort_values(by='Total CG ($)', ascending=False)

    # 5. Generare raport Markdown
    md_content = f"""# 📈 Raport Portofoliu & Dividende

## 📊 Summary General
* **Total Dividende Brute:** `${divs_only['Amount'].sum():,.2f}`
* **Total Impozite Reținute:** `${tax_only['Amount'].sum():,.2f}`
* **Total Dividende Nete Încasate:** `${divs_only['Amount'].sum() + tax_only['Amount'].sum():,.2f}`
* **Capital Gain Realizat (Poziții Închise):** `${df_close['Profit/Loss'].sum():,.2f}`
* **Capital Gain Nerealizat (Poziții Deschise):** `${cg_open['Net Profit'].sum():,.2f}`

---

## 📅 Statistica Lunară a Dividențelor

| Luna | Brute ($) | Impozit ($) | Nete ($) |
| :--- | :---: | :---: | :---: |
"""
    for _, row in monthly_divs.iterrows():
        md_content += f"| {row['Month']} | {row['Gross ($)']:,.2f} | {row['Tax ($)']:,.2f} | **{row['Net ($)']:,.2f}** |\n"

    md_content += """
---
## 🏢 Top Dividende per Companie (Net)
"""
    for _, row in div_summary.head(5).iterrows():
        md_content += f"- **{row['Ticker']}**: ${row['Net ($)']:,.2f} net\n"

    # Salvare în fișier local .md
    with open("raport-portofoliu.md", "w", encoding="utf-8") as f:
        f.write(md_content)

    print("Raportul 'Raport Portofoliu.md' a fost generat cu succes!")

    # Trimite pe Telegram
    send_telegram_message(md_content)

if __name__ == "__main__":
    process_portfolio()
