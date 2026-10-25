import pandas as pd

import xtb_loader


def process_portfolio():
    # 1. Cash Operations (Dividende & Impozite)
    df_cash = xtb_loader.load("cash")
    df_cash['Amount'] = pd.to_numeric(df_cash['Amount'], errors='coerce')
    df_cash['Time'] = xtb_loader.to_datetime_series(df_cash['Time'])

    type_col = df_cash['Type'].astype(str)
    divs_only = df_cash[type_col.str.contains('Dividend', case=False, na=False)].copy()
    wht_only = df_cash[type_col.str.contains('Withholding tax', case=False, na=False)].copy()
    ro_only = df_cash[type_col.str.contains('RO tax', case=False, na=False)].copy()
    tax_only = df_cash[type_col.str.contains('Withholding tax|RO tax', case=False, na=False)].copy()

    # 2. Closed Positions (Realized CG)
    df_close = xtb_loader.load("closed")
    df_close['Profit/Loss'] = pd.to_numeric(df_close['Profit/Loss'], errors='coerce')
    # Fara randul "Profit/loss" de total de la finalul exportului (altfel suma iese dublata)
    close_valid = df_close[df_close['Ticker'].notna() & df_close['Profit/Loss'].notna()]

    # 3. Open Positions (Unrealized CG) - doar randurile "parinte" per instrument
    df_open = xtb_loader.load("open")
    df_open['Net Profit'] = pd.to_numeric(df_open['Net Profit'], errors='coerce')
    cg_open = df_open[df_open['Type'].isna() & df_open['Ticker'].notna()].copy()

    gross = divs_only['Amount'].sum()
    taxes = tax_only['Amount'].sum()
    realized = close_valid['Profit/Loss'].sum()
    unrealized = cg_open['Net Profit'].sum()

    years = sorted(divs_only['Time'].dt.year.dropna().astype(int).unique())
    year_label = str(years[0]) if len(years) == 1 else (f"{years[0]}-{years[-1]}" if years else "")

    # 4. Creare Tabel Matrice pentru Dividende
    divs_only['Month'] = divs_only['Time'].dt.to_period('M').astype(str)
    pivot_table = divs_only.pivot_table(index='Ticker', columns='Month', values='Amount', aggfunc='sum', fill_value=0)

    pivot_table['Total'] = pivot_table.sum(axis=1)
    pivot_table = pivot_table.sort_values(by='Total', ascending=False)

    top_companies = pivot_table['Total'].copy()
    pivot_table = pivot_table.drop(columns=['Total'])

    months = sorted(pivot_table.columns)
    pivot_table = pivot_table[months]

    # --- 1. Versiunea Markdown (Dividende.md) ---
    md_content = f"""📈 **Dividende aferente anului {year_label}**

📊 **Summary General**
• **Total Dividende Brute:** `${gross:,.2f}`
• **Total Impozite Reținute:** `${taxes:,.2f}`  (din care impozit la dividende: `${wht_only['Amount'].sum():,.2f}`, impozit RO pe tranzacții: `${ro_only['Amount'].sum():,.2f}`)
• **Total Dividende Nete:** `${gross + taxes:,.2f}`
• **Capital Gain Realizat:** `${realized:,.2f}`
• **Capital Gain Nerealizat:** `${unrealized:,.2f}`

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

    # --- 2. Versiunea Text pentru Telegram (DividendeTG.txt) ---
    txt_content = f"""📊 Dividende aferente anului {year_label}

💰 Summary General:
• Brute: ${gross:,.2f}
• Impozite: ${taxes:,.2f}
• Nete: ${gross + taxes:,.2f}
• Capital Realizat: ${realized:,.2f}

🏢 Top Încasări per Companie:
"""
    icons = ["🥇", "🥈", "🥉", "🏅", "🔹", "🔹", "🔹", "🔹", "🔹", "🔹"]
    for idx, (ticker, total_val) in enumerate(top_companies.items()):
        icon = icons[idx] if idx < len(icons) else "🔹"
        txt_content += f"{icon} {ticker}: ${total_val:,.2f}\n"

    with open("DividendeTG.txt", "w", encoding="utf-8") as f:
        f.write(txt_content)

    print("Fișierele 'Dividende.md' și 'DividendeTG.txt' au fost generate cu succes.")


if __name__ == "__main__":
    process_portfolio()
