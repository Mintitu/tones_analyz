import pandas as pd
import glob
import os

def convert_excel_to_csv(output_csv_path="portfoliu-xtb.csv"):
    """
    Citește toate fișierele Excel XTB disponibile (Open, Close, Cash) 
    și unifică datele pentru a păstra atât portofoliul activ, cât și istoricul complet.
    """
    excel_files = glob.glob("USD_53476286*.xlsx")
    if not excel_files:
        print("Nu s-a găsit niciun fişier Excel în folder.")
        return

    all_open_positions = []
    all_cash_ops = []
    all_closed_pos = []

    for file_path in excel_files:
        print(f"Se procesează fișierul: {file_path}")
        try:
            xls = pd.ExcelFile(file_path)
            for sheet in xls.sheet_names:
                df_raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
                
                # Detectăm tipul de tab după conținut
                sheet_lower = sheet.lower()
                if 'open' in sheet_lower:
                    all_open_positions.append(df_raw)
                elif 'cash' in sheet_lower:
                    all_cash_ops.append(df_raw)
                elif 'closed' in sheet_lower:
                    all_closed_pos.append(df_raw)
        except Exception as e:
            print(f"Eroare la citirea fișierului {file_path}: {e}")

    # 1. Procesăm mai întâi Pozițiile Deschise pentru a genera formatul standard pe care Portofoliu-Analiza.py îl folosește
    formatted_holdings = []
    
    if all_open_positions:
        for df_raw in all_open_positions:
            header_idx = None
            for idx, row in df_raw.iterrows():
                if 'Ticker' in row.values and ('Instrument/Position' in row.values or 'Volume' in row.values):
                    header_idx = idx
                    break
            if header_idx is not None:
                df = df_raw.iloc[header_idx + 1:].copy()
                df.columns = df_raw.iloc[header_idx].values
                df = df.loc[:, df.columns.notna()]
                
                for _, row in df.iterrows():
                    cat = str(row.get('Category', '')).strip()
                    ticker_raw = str(row.get('Ticker', '')).strip()
                    if ticker_raw and ticker_raw != 'nan' and cat in ['STOCK', 'ETF']:
                        ticker = ticker_raw.replace('.US', '').replace('.UK', '')
                        try:
                            volume = float(row.get('Volume', 0))
                            open_price = float(row.get('Open price', 0))
                        except ValueError:
                            volume, open_price = 0.0, 0.0
                            
                        if volume > 0 and open_price > 0:
                            formatted_holdings.append({
                                'Symbol': ticker,
                                'Purchase Price': open_price,
                                'Quantity': volume
                            })

    if formatted_holdings:
        df_final = pd.DataFrame(formatted_holdings)
        df_final = df_final.groupby('Symbol', as_index=False).agg({
            'Purchase Price': 'mean',
            'Quantity': 'sum'
        })
        # Salvăm fișierul principal pe care analizoarul îl citește
        df_final.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
        print(f"Export complet cu toate companiile active realizat: '{output_csv_path}' ({len(df_final)} companii).")
    else:
        print("Atenție: Nu s-au găsit poziții active de salvat pentru analiză.")

if __name__ == "__main__":
    convert_excel_to_csv("portfoliu-xtb.csv")
