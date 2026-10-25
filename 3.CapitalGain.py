import pandas as pd

import xtb_loader


def process_capital_gain():
    # 1. Closed Positions (Capital Gain Realizat)
    df_close = xtb_loader.load("closed")
    df_close['Profit/Loss'] = pd.to_numeric(df_close['Profit/Loss'], errors='coerce')
    time_col = 'Close Time (UTC)' if 'Close Time (UTC)' in df_close.columns else 'Close Time'
    df_close['Close Time'] = xtb_loader.to_datetime_series(df_close[time_col])

    # Doar pozitiile reale: randul "Profit/loss" de la finalul exportului nu are Ticker
    closed_valid = df_close[df_close['Ticker'].notna() & df_close['Profit/Loss'].notna()].copy()
    closed_valid['Month'] = closed_valid['Close Time'].dt.to_period('M').astype(str)

    # 2. Open Positions (Capital Gain Nerealizat)
    df_open = xtb_loader.load("open")
    df_open['Net Profit'] = pd.to_numeric(df_open['Net Profit'], errors='coerce')
    # Doar randurile "parinte" (per instrument). Pozitiile individuale (Type=BUY/SELL)
    # sunt deja incluse in ele, deci nu se aduna a doua oara.
    cg_open = df_open[df_open['Type'].isna() & df_open['Ticker'].notna()].copy()

    total_realized = closed_valid['Profit/Loss'].sum()
    total_unrealized = cg_open['Net Profit'].sum()
    total_cg = total_realized + total_unrealized

    # ==========================================
    # 3. GENERARE RAPORT GITHUB (CapitalGain.md - Tabel Matrice)
    # ==========================================
    pivot_table = closed_valid.pivot_table(
        index='Ticker',
        columns='Month',
        values='Profit/Loss',
        aggfunc='sum',
        fill_value=0
    )

    pivot_table['Total'] = pivot_table.sum(axis=1)
    pivot_table = pivot_table.sort_values(by='Total', ascending=False)
    pivot_table = pivot_table.drop(columns=['Total'])

    months = sorted(pivot_table.columns)
    pivot_table = pivot_table[months]

    md_content = f"""📈 **Raport Capital Gain (Câștiguri din Capital)**

📊 **Summary General**
• **Capital Gain Realizat:** `${total_realized:,.2f}`
• **Capital Gain Nerealizat (Poziții Deschise):** `${total_unrealized:,.2f}`
• **Total Capital Gain:** `${total_cg:,.2f}`

---
📅 **Matrice Capital Gain Realizat (Companii vs. Luni)**
*(Profit/Pierdere realizată per simbol și lună)*

| Companie / Lună | """ + " | ".join(months) + " | Total Realizat |" + "\n"

    md_content += "| :--- | " + " | ".join([":---:" for _ in months]) + " | :---: |" + "\n"

    for ticker, row in pivot_table.iterrows():
        row_total = row.sum()
        row_cells = []
        for val in row:
            if val > 0:
                row_cells.append(f"+${val:,.1f}")
            elif val < 0:
                row_cells.append(f"-${abs(val):,.1f}")
            else:
                row_cells.append("-")

        total_str = f"+${row_total:,.1f}" if row_total > 0 else (f"-${abs(row_total):,.1f}" if row_total < 0 else "$0.0")
        row_str = f"| **{ticker}** | " + " | ".join(row_cells) + f" | **{total_str}** |"
        md_content += row_str + "\n"

    with open("CapitalGain.md", "w", encoding="utf-8") as f:
        f.write(md_content)

    # ==========================================
    # 4. GENERARE RAPORT TELEGRAM (CapitalGainTG.txt - Compact cu medalii)
    # ==========================================
    tg_content = f"""📈 *Raport Capital Gain*

📊 *Summary General*
• *Realizat:* `${total_realized:,.2f}`
• *Nerealizat:* `${total_unrealized:,.2f}`
• *Total:* `${total_cg:,.2f}`

━━━━━━━━━━━━━━━━━━━━━━
💼 *Top Companii (Realizat Total):*
"""
    ticker_totals = closed_valid.groupby('Ticker')['Profit/Loss'].sum().sort_values(ascending=False)

    for idx, (ticker, tot) in enumerate(ticker_totals.items()):
        if idx == 0:
            icon = "🥇"
        elif idx == 1:
            icon = "🥈"
        elif idx == 2:
            icon = "🥉"
        else:
            icon = "▪️"

        sign_str = "+" if tot >= 0 else ""
        tg_content += f"{icon} *{ticker}*: `{sign_str}${tot:,.2f}`\n"

    with open("CapitalGainTG.txt", "w", encoding="utf-8") as f:
        f.write(tg_content)

    print("Fișierele 'CapitalGain.md' și 'CapitalGainTG.txt' au fost generate cu succes.")


if __name__ == "__main__":
    process_capital_gain()
