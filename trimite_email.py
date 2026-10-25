import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

def trimite_raport_email(subiect, corp_mesaj, cale_fisier_atasament=None):
    sender = os.environ.get("EMAIL_SENDER")
    password = os.environ.get("EMAIL_PASSWORD")
    receiver = os.environ.get("EMAIL_RECEIVER")

    if not all([sender, password, receiver]):
        print("❌ Lipsesc variabilele de mediu pentru email!")
        return

    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = subiect

    msg.attach(MIMEText(corp_mesaj, 'html'))

    # Daca exista un fisier de atasat (ex: raport PDF sau Excel)
    if cale_fisier_atasament and os.path.exists(cale_fisier_atasament):
        filename = os.path.basename(cale_fisier_atasament)
        with open(cale_fisier_atasament, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {filename}")
        msg.attach(part)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())
        server.quit()
        print("✅ Emailul cu raportul a fost trimis cu succes!")
    except Exception as e:
        print(f"❌ Eroare la trimiterea emailului: {e}")

if __name__ == "__main__":
    # Test sau apelare directa
    raport_demo = "<h1>Raport Lunar Analiza Portfolio</h1><p>Analiza lunara a fost finalizata cu succes!</p>"
    trimite_raport_email("📊 Raport Lunar Analiza StockSage", raport_demo)