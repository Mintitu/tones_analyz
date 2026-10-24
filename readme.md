# 📈 XTB Portfolio Analyzer & Telegram Bot

Sistem automatizat de analiză a portofoliului XTB bazat pe indicatori tehnici (RSI, Gap față de Maxim) și fundamentali (ROIC, Forward PE, EV/EBITDA, Target Price), integrat cu GitHub Actions și notificări pe Telegram.

---

## 🛠️ Mod de Funcționare & Arhitectură

1. **Citire Date (Excel XTB):** Scriptul identifică și citește automat fișierele `.xlsx` de export oferite de platforma XTB (`USD_*.xlsx`), procesând tab-ul de poziții deschise (`*open*`).
2. **Preluare Date Financiare (yFinance):** Extrage în timp real date actualizate pentru fiecare ticker: preț curent, istoric pe 1 an, RSI(14), EV/EBITDA, ROIC, P/E, Forward P/E și Target Price mediu stabilit de analiști.
3. **Generare Semnale & Scor:** Fiecare instrument este evaluat printr-un algoritm de scoring (0-99) și încadrat într-o categorie vizuală de risc/oportunitate.
4. **Notificare pe Telegram:** Trmite un raport condensat, formatat în Markdown, direct pe canalul/chat-ul tău de Telegram.

---

## 📊 Sistemul de Scoring & Recomandări (0 - 99)

Analiza calculează un punctaj unic pentru fiecare companie și atribuie un indicator vizual în funcție de nivelul de risc și oportunitate:

### 🟢 Oportunitate / Profit (Verde)
* **Supravândut Mare / Mediu:** `RSI < 25` sau `RSI < 35` cu poziția pe minus.
* **Discount Mare / Mediu:** Prețul este la un nivel de discount de peste `20%` – `35%` față de maximul pe 1 an.
* **Profit Mare / Solid / Stabil:** Poziții pe plus cu indicatori de momentum sănătoși.

### 🟧 Atenție / Corecție (Portocaliu)
* **Corecție Mică / Medie:** Scăderi moderate de preț (`-3%` până la `-20%`).
* **Supracumpărat Mediu:** `RSI > 70` (posibilă marcare de profit).

### 🔴 Risc / Scădere Critică (Roșu)
* **Scădere Mare / Critică:** Scăderi peste `25%` sau `35%` din valoarea de achiziție.
* **Supracumpărat Mare:** `RSI > 78` (zona de vârf).

### ⚠️ Poziție Neutră (Triunghi Galben)
* Se aplică pozițiilor fără un semnal extrem clar, menținând atenția pe evoluția pieței.

---

## 📲 Structura Raportului pe Telegram

Fiecare companie este afișată pe 2 rânduri ultra-compacte:

```text
🟢78 REFI 12.15$ +4.2% (Profit Solid)
TP14.5$ Gap-12% EV8.2x ROIC14.5% RSI42 PE9.1 FwdPE8.4
```

1. **Rândul 1 (Bold):** `[Status]` `[Scor]` `[Ticker]` `[Preț Curent]` `[P&L %]` `[Motiv Signal]`
2. **Rândul 2 (Code Block):** `[Target Price]` `[Gap Maxim]` `[EV/EBITDA]` `[ROIC]` `[RSI]` `[P/E]` `[Forward P/E]`

---

## ⚙️ Configurare GitHub Actions & Secrets

Pentru ca scriptul să poată trimite rapoartele pe Telegram, adaugă următoarele secrete în repo-ul tău (**Settings** > **Secrets and variables** > **Actions**):

* `TELEGRAM_BOT_TOKEN`: Token-ul obținut de la `@BotFather`.
* `TELEGRAM_CHAT_ID`: ID-ul chat-ului sau canalului tău de Telegram.

---

## 🚀 Rulare Automată

Pipeline-ul este configurat să ruleze automat de luni până vineri la ora **20:00 UTC** prin **GitHub Actions** sau poate fi declanșat manual direct din tab-ul **Actions** (`workflow_dispatch`).