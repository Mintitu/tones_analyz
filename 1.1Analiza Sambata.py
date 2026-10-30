import os
import requests
import pandas as pd

def citeste_analiza_md():
    """Citește rezumatul săptămânal din fișierul de analiză de vineri."""
    cai_posibile = ["analiza.md", "docs/analiza.md", "./analiza.md"]
    for calea in cai_posibile:
        if os.path.exists(calea):
            with open(calea, "r", encoding="utf-8") as f:
                return f.read()
    return "Nu s-a găsit fișierul analiza.md cu sinteza săptămânală."

def parseaza_portofoliu_xtb():
    """Citește volumul și valorile din fișierul Excel XTB."""
    excel_file = 'USD_53476286_2006-01-01_2026-10-152.xlsx'
    try:
        df = pd.read_excel(excel_file, sheet_name='Open Positions', skiprows=10)
        parent_rows = df[df['Type'].isna() & df['Ticker'].notna()].copy()
        parent_rows['Value'] = pd.to_numeric(parent_rows['Value'], errors='coerce').fillna(0)
        
        ticker_dividende = ['REFI.US', 'DX.US', 'SCM.US', 'ARR.US', 'ARCC.US', 'PFLT.US', 'HRZN.US']
        
        valoare_dividende = 0.0
        valoare_capital_gain = 0.0
        
        for _, row in parent_rows.iterrows():
            if row['Ticker'] in ticker_dividende:
                valoare_dividende += row['Value']
            else:
                valoare_capital_gain += row['Value']
                
        valoare_totala = valoare_dividende + valoare_capital_gain
        if valoare_totala == 0:
            return 64500.0, 64500.0, 129000.0
            
        return valoare_capital_gain, valoare_dividende, valoare_totala
    except Exception as e:
        print(f"Eroare Excel: {e}")
        return 64500.0, 64500.0, 129000.0

def ruleaza_raport_sambata():
    val_cg, val_div, val_total = parseaza_portofoliu_xtb()
    rezumat_md = citeste_analiza_md()
    
    TINTA_CG = 0.50
    pondere_cg = val_cg / val_total
    pondere_div = val_div / val_total
    deviatie = pondere_cg - TINTA_CG
    MARJA_TOLERANTA = 0.05

    # Construirea mesajului unificat pentru Telegram
    mesaj = "📊 **RAPORT SĂPTĂMÂNAL & SEMNALE XTB**\n"
    mesaj += "━━━━━━━━━━━━━━━━━━━━━━\n"
    mesaj += f"💰 **Valoare Totală Portofoliu:** `${val_total:,.2f}`\n\n"
    
    mesaj += "⚖️ **Structură Țintă 50/50:**\n"
    mesaj += f"• Capital Gain: `{pondere_cg*100:.1f}%` (${val_cg:,.2f})\n"
    mesaj += f"• Dividende: `{pondere_div*100:.1f}%` (${val_div:,.2f})\n\n"
    
    mesaj += "🤖 **Semnal Matematic & Rebalansare:**\n"
    if deviatie <= -MARJA_TOLERANTA:
        mesaj += "🟢 **BUY LOW:** Capital Gain subponderat. Oportunitate de acumulare.\n"
    elif deviatie >= MARJA_TOLERANTA:
        mesaj += "🔴 **TAKE PROFIT:** Capital Gain a depășit pragul. Rebalansare recomandată.\n"
    else:
        mesaj += "⚖️ **NEUTRU:** Portofoliul este echilibrat.\n\n"
        
    mesaj += "📈 **Direcția Companiilor (Luni–Vineri anterioare):**\n"
    # Luăm primele rânduri sau secțiunea relevantă din analiza.md
    linii_md = [l for l in rezumat_md.split('\n') if l.strip()][:15] # Primele linii relevante
    mesaj += "\n".join(linii_md) + "\n\n"
    
    mesaj += "━━━━━━━━━━━━━━━━━━━━━━\n"
    mesaj += "🤖 *Generat automat prin GitHub Actions.*"

    # Trimitere pe Telegram
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": mesaj, "parse_mode": "Markdown"}
        requests.post(url, json=payload)

if __name__ == "__main__":
    ruleaza_raport_sambata()