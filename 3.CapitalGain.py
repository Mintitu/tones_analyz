import os
import glob
import pandas as pd

def process_capital_gain():
    close_files = glob.glob("*Close*.xlsx") + glob.glob("USD_*_Close.xlsx")
    open_files = glob.glob("*Open*.xlsx") + glob.glob("USD_*_Open.xlsx")

    all_xlsx = glob.glob("*.xlsx")
    if not all_xlsx:
        print("Nu s-au găsit fișiere Excel (.xlsx) în director.")
        return

    close_file = close_files[0] if close_files else (all_xlsx[1] if len(all_xlsx) > 1 else all_xlsx[0])
    open_file = open_files[0] if open_files else (all_xlsx[2] if len(all_xlsx) > 2 else all_xlsx[0])

    # 1. Closed Positions (Realized Capital Gain)
    df_close_raw = pd.read_excel(close_file, skiprows=3)
    df_close = df_close_raw.iloc[1:].copy()
    df_close.columns = df_close_raw.iloc[0].values
    
    df_close['Profit/Loss'] = pd.to_numeric(df_close['Profit/Loss'], errors='coerce')
    time_col = 'Close Time (UTC)' if 'Close Time (UTC)' in df_close.columns else 'Close Time'
    df_close['Close Time'] = pd.to_datetime(df_close[time_col], errors='coerce')

    closed_valid = df_close[df_close['Ticker'].notna() & df_close['Profit/Loss'].notna()].copy()
    closed_valid['Month'] = closed_valid['Close Time'].dt.to_period('M').astype(str)

    # 2. Open Positions (Unrealized Capital Gain)
    df_open_raw = pd.read_excel(open_file, skiprows=9)
    df_open = df_open_raw.iloc[1:].copy()
    df_open.columns = df_open_raw.iloc[0].values
    
    df_open['Net Profit'] = pd.to_numeric(df_open['Net Profit'], errors='coerce')
    cg_open = df_open[df_open['Ticker'].notna()].copy()

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
    # 4. GENERARE RAPORT TELEGRAM (CapitalGainTG.txt - Compact cu iconițe)
    # ==========================================
    tg_content = f"""🚀 *RAPORT CAPITAL GAIN* 🚀

💼 *Summary General*
• 🟢 *Realizat:* `${total_realized:,.2f}`
• 🟠 *Nerealizat:* `${total_unrealized:,.2f}`
• 💰 *Total Capital:* `${total_cg:,.2f}`

━━━━━━━━━━━━━━━━━━━━━━
📊 *Top Companii (Realizat Total):*
"""
    ticker_totals = closed_valid.groupby('Ticker')['Profit/Loss'].sum().sort_values(ascending=False)
    for ticker, tot in ticker_totals.items():
        icon = "🟢" if tot >= 0 else "🔴"
        sign_str = "+" if tot >= 0 else ""
        tg_content += f"{icon} *{ticker}*: `{sign_str}${tot:,.2f}`\n"

    with open("CapitalGainTG.txt", "w", encoding="utf-8") as f:
        f.write(tg_content)

    print("Fișierele 'CapitalGain.md' și 'CapitalGainTG.txt' au fost generate cu succes.")

if __name__ == "__main__":
    process_capital_gain()
