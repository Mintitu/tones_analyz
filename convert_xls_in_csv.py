import pandas as pd
import glob
import os

def convert_excel_to_paco_csv(excel_file_path, output_csv_path="paco_portfolio.csv"):
    """
    Converteste extrasul Excel al brokerului (Cash Operations + Closed Positions)
    in formatul standard CSV 'paco_portfolio' pentru analiza pe GitHub.
    """
    print(f"Se proceseaza fisierul: {excel_file_path}")
    
    # 1. Citim tab-ul Cash Operations
    df_cash_raw = pd.read_excel(excel_file_path, sheet_name='Cash Operations')
    
    # Gasim randul de antet (unde coloana 0 este 'Type')
    header_idx = df_cash_raw[df_cash_raw.iloc[:, 0] == 'Type'].index[0]
    
    df_cash = df_cash_raw.iloc[header_idx + 1:].copy()
    df_cash.columns = df_cash_raw.iloc[header_idx].values
    
    # Filtram randul de sumar/total daca exista
    df_cash = df_cash[df_cash['Type'] != 'Total'].dropna(how='all')
    
    formatted_rows = []
    
    for _, row in df_cash.iterrows():
        op_type = str(row['Type']).strip()
        time_val = pd.to_datetime(row['Time']) if pd.notna(row['Time']) else None
        date_str = time_val.strftime('%Y-%m-%d') if time_val else ''
        
        instrument = str(row['Instrument']) if pd.notna(row['Instrument']) else ''
        ticker_raw = str(row['Ticker']) if pd.notna(row['Ticker']) else ''
        # Curatam sufixul .US sau .UK din ticker daca este cazul
        ticker = ticker_raw.replace('.US', '') if ticker_raw != 'nan' else ''
        
        amount = abs(float(row['Amount'])) if pd.notna(row['Amount']) else 0.0
        comment = str(row['Comment']) if pd.notna(row['Comment']) else ''
        
        # Extragem numarul de actiuni din comentariu daca este disponibil (ex: OPEN BUY APLE 300 @ 11.71)
        shares = 0.0
        if 'BUY' in comment or 'SELL' in comment:
            parts = comment.split()
            for idx, p in enumerate(parts):
                if p in ['BUY', 'SELL'] and idx + 2 < len(parts):
                    try:
                        # Daca numarul de actiuni este format ca "300/4000", luam prima parte
                        sh_str = parts[idx + 2].split('/')[0]
                        shares = float(sh_str)
                    except ValueError:
                        shares = 0.0
        
        # --- 1. Tranzactii de Cumparare (Buy) ---
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
            
        # --- 2. Tranzactii de Vanzare (Sell) ---
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
            
        # --- 3. Dividende Primite (Dividend) ---
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
            
        # --- 4. Impozit pe Dividende (Withholding tax / RO tax) ---
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

    # Cream DataFrame-ul final si sortam cronologic
    df_final = pd.DataFrame(formatted_rows)
    df_final['Date_dt'] = pd.to_datetime(df_final['Date'])
    df_final = df_final.sort_values(by='Date_dt').drop(columns=['Date_dt'])
    
    # Salvam in fisierul CSV dorit
    df_final.to_csv(output_csv_path, index=False)
    print(f"Export finalizat cu succes: '{output_csv_path}' ({len(df_final)} randuri procesate).")

if __name__ == "__main__":
    # Cauta automat ultimul fisier Excel din folderul curent
    excel_files = glob.glob("USD_*.xlsx")
    if excel_files:
        convert_excel_to_paco_csv(excel_files[0], "paco_portfolio_updated.csv")
    else:
        print("Nu s-a gasit niciun fisier Excel de la broker in folder.")