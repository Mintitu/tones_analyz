import pandas as pd
import glob
import os

def convert_excel_to_csv(excel_file_path, output_csv_path="portfoliu_xtb.csv"):
    """
    Extrage toate pozitiile deschise active direct din tab-ul 'Open positions' 
    al fișierului XTB și le salvează în formatul standard CSV pentru analiză.
    """
    print(f"Se proceseaza fisierul: {excel_file_path}")
    xls = pd.ExcelFile(excel_file_path)
    
    # Cautam tab-ul de pozitii deschise (poate fi 'Open Positions' sau 'Open positions')
    open_sheet = None
    for s in xls.sheet_names:
        if 'open' in s.lower():
            open_sheet = s
            break
            
    if not open_sheet:
        print("Eroare: Nu s-a gasit tab-ul de pozitii deschise in Excel.")
        return

    df_raw = pd.read_excel(excel_file_path, sheet_name=open_sheet, header=None)
    
    # Gasim randul de antet unde sunt coloanele 'Ticker' sau 'Instrument/Position'
    header_idx = None
    for idx, row in df_raw.iterrows():
        if 'Ticker' in row.values and ('Instrument/Position' in row.values or 'Volume' in row.values):
            header_idx = idx
            break
            
    if header_idx is None:
        # Fallback pe un index standard in functie de structura XTB
        header_idx = 10 

    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = df_raw.iloc[header_idx].values
    df = df.loc[:, df.columns.notna()]
    
    formatted_rows = []
    
    for _, row in df.iterrows():
        # In XTB, randurile de actiuni active au categorie STOCK sau ETF
        cat = str(row.get('Category', '')).strip()
        ticker_raw = str(row.get('Ticker', '')).strip()
        
        if ticker_raw and ticker_raw != 'nan' and cat in ['STOCK', 'ETF']:
            ticker = ticker_raw.replace('.US', '').replace('.UK', '')
            
            # Preluam volumul (numarul de actiuni) si pretul de deschidere sau valoarea
            try:
                volume = float(row.get('Volume', 0))
            except ValueError:
                volume = 0.0
                
            try:
                # Cautam pretul de achizitie (Open price)
                open_price = float(row.get('Open price', 0))
            except ValueError:
                open_price = 0.0
                
            # Dاگر volumul sau pretul sunt lipsa pe randul principal, cautam subrandurile
            if volume == 0 or open_price == 0:
                continue

            formatted_rows.append({
                'Symbol': ticker,
                'Purchase Price': open_price,
                'Quantity': volume
            })

    # Daca am gasit pozitii, le salvam in formatul simplificat pe care Portofoliu-Analiza.py le citeste instant
    df_final = pd.DataFrame(formatted_rows)
    if not df_final.empty:
        # Eliminam duplicatele sau insumam cantitatile daca sunt multiple loturi pe acelasi ticker
        df_final = df_final.groupby('Symbol', as_index=False).agg({
            'Purchase Price': 'mean',
            'Quantity': 'sum'
        })
        
    df_final.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
    print(f"Export complet cu toate companiile finalizat: '{output_csv_path}' ({len(df_final)} companii gasite).")

if __name__ == "__main__":
    excel_files = glob.glob("USD_*.xlsx")
    if excel_files:
        convert_excel_to_csv(excel_files[0], "portfoliu_xtb.csv")
    else:
        print("Nu s-a gasit niciun fisier Excel de la broker in folder.")
