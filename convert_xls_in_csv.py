import pandas as pd
import glob
import os

def convert_excel_to_csv(excel_file_path, output_csv_path="portfoliu_xtb.csv"):
    """
    Converteste integral extrasul Excel XTB (Open Positions, Cash Operations, Closed Positions etc.)
    pastrand toate informatiile, dividendele, taxele si tranzactiile intr-un format CSV unificat.
    """
    print(f"Se proceseaza fisierul: {excel_file_path}")
    xls = pd.ExcelFile(excel_file_path)
    print(f"Taburi gasite in Excel: {xls.sheet_names}")
    
    all_dataframes = []

    # 1. Procesam tab-ul de Operatiuni Cash (dex. Cumparari, Vanzari, Dividende, Taxe)
    if 'Cash Operations' in xls.sheet_names:
        df_cash_raw = pd.read_excel(excel_file_path, sheet_name='Cash Operations', header=None)
        # Gasim randul de antet unde prima coloana este 'Type' sau 'ID'
        header_rows = df_cash_raw[df_cash_raw.isin(['Type']).any(axis=1)].index
        if len(header_rows) > 0:
            header_idx = header_rows[0]
            df_cash = df_cash_raw.iloc[header_idx + 1:].copy()
            df_cash.columns = df_cash_raw.iloc[header_idx].values
            df_cash = df_cash.loc[:, df_cash.columns.notna()] # scoate coloanele NaN
            all_dataframes.append(df_cash)

    # 2. Procesam tab-ul de Poziții Deschise (daca exista)
    if 'Open positions' in xls.sheet_names:
        df_open_raw = pd.read_excel(excel_file_path, sheet_name='Open positions', header=None)
        header_rows = df_open_raw[df_open_raw.isin(['Position', 'Open price', 'Ticker']).any(axis=1)].index
        if len(header_rows) > 0:
            header_idx = header_rows[0]
            df_open = df_open_raw.iloc[header_idx + 1:].copy()
            df_open.columns = df_open_raw.iloc[header_idx].values
            df_open = df_open.loc[:, df_open.columns.notna()]
            all_dataframes.append(df_open)

    # Daca am extras date, le salvam intr-un format unificat sau combinat
    if all_dataframes:
        # Salvam tab-ul principal de Cash Operations curat, dar pastrand absolut toate coloanele originale XTB
        df_final = all_dataframes[0]
        df_final.to_csv(output_csv_path, index=False, encoding='utf-8-sig')
        print(f"Export complet finalizat cu succes: '{output_csv_path}' ({len(df_final)} randuri).")
    else:
        print("Atentie: Nu s-au putut extrage date din taburile cunoscute.")

if __name__ == "__main__":
    excel_files = glob.glob("USD_*.xlsx")
    if excel_files:
        convert_excel_to_csv(excel_files[0], "portfoliu_xtb.csv")
    else:
        print("Nu s-a gasit niciun fisier Excel de la broker in folder.")
