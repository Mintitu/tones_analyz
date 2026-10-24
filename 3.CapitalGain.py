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
    
    # Debug: afișăm coloanele disponibile în fișierul Close
    print("Coloane disponibile în Close:", list(df_close.columns))

    df_close['Profit/Loss'] = pd.to_numeric(df_close['Profit/Loss'], errors='coerce')
    
    # Căutăm dinamic coloana de timp (Close Time, Time, etc.)
    time_col = None
    for col in df_close.columns:
        if col and ('time' in str(col).lower() or 'data' in str(col).lower()):
            time_col = col
            break
    
    if not time_col:
        # Fallback pe prima coloană sau 'Time' dacă există
        time_col = 'Close Time' if 'Close Time' in df_close.columns else df_close.columns[0]

    print(using f"Folosim coloana de timp pentru Close: '{time_col}'")
    df_close['Close Time'] = pd.to_datetime(df_close[time_col], errors='coerce')

    # Filtrăm doar pozițiile închise valide cu Ticker și Profit/Loss
    closed_valid = df_close[df_close['Ticker'].notna() & df_close['Profit/Loss'].notna()].copy()
    closed_valid['Month'] = closed_valid['Close Time'].dt.to_period('M').astype(str)

    # 2. Open Positions (Unrealized Capital Gain)
    df_open_raw = pd.read_excel(open_file, skiprows=9)
    df_open = df_open_raw.iloc[1:].copy()
    df_open.columns = df_open_raw.iloc[0].values
    
    df_open['Net Profit'] = pd.to_numeric(df_open['Net Profit'], errors='coerce')
    cg_open = df_open[df_open['Type'].isna() & df_open['Ticker'].notna()].copy()

    # 3. Creare Tabel Matrice (Companii vs Luni) pentru Capital Gain Realizat
    pivot_table = closed_valid.pivot_table(
        index='Ticker', 
        columns='Month', 
        values='Profit/Loss', 
        aggfunc='sum', 
        fill_value=0
    )

    # Adăugăm total pe companie și sortăm companiile descrescător după profitul realizat
    pivot_table['Total'] = pivot_table.sum(axis=1)
    pivot_table = pivot_table.sort_values(by='Total', ascending=False)
    pivot_table = pivot_table.drop(columns=['Total'])

    # Lunile sortate cronologic
    months = sorted(pivot_table.columns)
    pivot_table = pivot_table[months]

    # Structurare raport Markdown
    total_realized = closed_valid['Profit/Loss'].sum()
    total_unrealized = cg_open['Net Profit'].sum()
    total_cg = total_realized + total_unrealized

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

    # Salvare fișier
    with open("CapitalGain.md", "w", encoding="utf-8") as f:
        f.write(md_content)

    print("Fișierul 'CapitalGain.md' a fost creat cu succes.")

if __name__ == "__main__":
    process_capital_gain()
