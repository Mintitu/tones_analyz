import pandas as pd
import glob
import os

def convert_excel_to_csv(excel_file_path, output_csv_path="portfoliu_xtb.csv"):
    """
    Converteste extrasul Excel al brokerului (Cash Operations)
    in formatul standard CSV 'portfoliu' pastrand toate tranzacitile,
    dividendele, taxele si extragand corect numarul de actiuni si valorile.
    """
    print(f"Se proceseaza fisierul: {excel_file_path}")
    
    # 1. Citim tab-ul Cash Operations
    df_cash_raw = pd.read_excel(excel_file_path, sheet_name='Cash Operations', header=None)
    
    # Gasim randul de antet (unde coloana este 'Type')
    header_idx = None
    for idx, row in df_cash_raw.iterrows():
        if 'Type' in row.values and 'Instrument' in row.values:
            header_idx = idx
            break
            
    if header_idx is None:
        print("Eroare: Nu s-a gasit antetul in Cash Operations.")
        return

    df_cash = df_cash_raw.iloc[header_idx + 1:].copy()
    df_cash.columns = df_cash_raw.iloc[header_idx].values
    
    # Curatare coloane goale sau NaN
    df_cash = df_cash.loc[:, df_cash.columns.notna()]
    df_cash = df_cash[df_cash['Type'].notna() & (df_cash['Type'] != 'Total')]
    
    formatted_rows = []
    
    for _, row in df_cash.iterrows():
        op_type = str(row['Type']).strip()
        time_val = pd.to_datetime(row['Time']) if pd.notna(row['Time']) else None
        date_str = time_val.strftime('%Y-%m-%d') if time_val else ''
        
        instrument = str(row['Instrument']) if pd.notna(row['Instrument']) else ''
        ticker_raw = str(row['Ticker']) if pd.notna(row['Ticker']) else ''
        ticker = ticker_raw.replace('.US', '') if ticker_raw != 'nan' else ''
        
        amount = abs(float(row['Amount'])) if pd.notna(row['Amount']) else 0.0
        comment = str(row['Comment']) if pd.notna(row['Comment']) else ''
        
        # Extragem numarul de actiuni din comentariu daca este disponibil
        shares = 0.0
        if 'BUY' in comment or 'SELL' in comment:
            parts = comment.split()
            for idx, p in enumerate(parts):
                if p in ['BUY', 'SELL'] and idx + 2 < len(parts):
                    try:
                        sh_str = parts[idx + 2].split('/')[0]
                        shares = float(sh_str)
                    except ValueError:
                        shares = 0.0
        
        # --- Tranzactii de Cumparare (Buy) ---
        if op_type == 'Stock purchase':
            formatted_rows.append({
                'Date': date_str,
                'Type': 'Buy',
                'Security Name': instrument,
                'Ticker': ticker,
                'Shares': shares,
                'Value': round(amount, 2),
                'Fees': 0,
                'Taxes': 0,
                'Currency': 'USD',
                'Note': comment
            })
            
        # --- Tranzactii de Vanzare (Sell) ---
        elif op_type == 'Stock sell':
            formatted_rows.append({
                'Date': date_str,
                'Type': 'Sell',
                'Security Name': instrument,
                'Ticker': ticker,
                'Shares': shares,
                'Value': round(amount, 2),
                'Fees': 0,
                'Taxes': 0,
                'Currency': 'USD',
                'Note': comment
            })
            
        # --- Dividende Primite (Dividend) ---
        elif op_type == 'Dividend':
            formatted_rows.append({
                'Date': date_str,
                'Type': 'Dividend',
                'Security Name': instrument,
                'Ticker': ticker,
                'Shares': 0.0,
                'Value': round(amount, 2),
                'Fees': 0,
                'Taxes': 0,
                'Currency': 'USD',
                'Note': comment
            })
            
        # --- Impozite / Taxe ---
        elif op_type in ['Withholding tax', 'RO tax']:
            formatted_rows.append({
                'Date': date_str,
                'Type': 'Tax',
                'Security Name': instrument,
                'Ticker': ticker,
                'Shares': 0.0,
                'Value': 0.0,
                'Fees': 0,
                'Taxes': round(amount, 2),
                'Currency': 'USD',
                'Note': f"{op_type}: {comment}"
            })

    # Creăm DataFrame-ul final și sortăm cronologic
    df_final = pd.DataFrame(formatted_rows)
    if not df_final.empty:
        df_final['Date_dt'] = pd.to_datetime(df_final['Date'])
        df_final = df_final.sort_values(by='Date_dt').drop(columns=['Date_dt'])
        
    df_final.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    print(f"Export complet finalizat cu succes: '{output_csv_path}' ({len(df_final)} rânduri procesate).")

if __name__ == "__main__":
    excel_files = glob.glob("USD_*.xlsx")
    if excel_files:
        convert_excel_to_csv(excel_files[0], "portfoliu_xtb.csv")
    else:
        print("Nu s-a găsit niciun fişier Excel de la broker în folder.")
