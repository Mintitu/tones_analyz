# 📈 Analiza Portfoliu Tones pe XTB

A simple python script that reads your stock holdings from a csv file downloaded from Yahoo Finance, fetches **live market data** from Yahoo Finance, and prints a color-coded summary table with prices, performance, dividends, and actionable signals. Everything is displayed in your terminal. 

---

## 🖥️ Sample Output

```
Portfolio Analysis  —  2026-05-17 22:52  |  Period: 6 Months

╭───────────┬──────────────────────────┬─────────┬────────┬───────────┬─────────┬─────────┬───────┬────────────┬─────────────┬─────────────┬─────────────┬────────────┬──────────╮
│    Symbol │                     Name │   Price │   Day% │   Pd Ret% │   Pd Hi │   Pd Lo │   Qty │   Avg Cost │   Cur Value │   Gain/Loss │   Div Yield │   Strength │   Signal │
├───────────┼──────────────────────────┼─────────┼────────┼───────────┼─────────┼─────────┼───────┼────────────┼─────────────┼─────────────┼─────────────┼────────────┼──────────┤
│    ATH.TO │       ATHABASCA OIL CORP │  12.41  │ +1.89% │   +66.35% │  12.45  │   6.22  │     9 │       1.36 │      111.69 │       99.45 │           — │     Strong │ Buy More │
│    MFC.TO │             MANULIFE FIN │  51.72  │ +0.43% │   +11.00% │  55.34  │  44.23  │     2 │      27.47 │      103.44 │       48.50 │       3.58% │     Strong │     Keep │
│    AQN.TO │ ALGONQUIN POWER AND UTI… │   7.94  │ -1.61% │    -3.81% │   9.59  │   7.77  │     2 │      19.52 │       15.88 │      -23.16 │       4.46% │       Weak │     Sell │
╰───────────┴──────────────────────────┴─────────┴────────┴───────────┴─────────┴─────────┴───────┴────────────┴─────────────┴─────────────┴─────────────┴────────────┴──────────╯

  Total Cost Basis :  $   393.64
  Total Value      :  $   752.03
  Total Gain/Loss  :  +$  358.39  (+91.04%)
```

> The **Signal** column is color-coded in the terminal: 🔴 Sell · 🟢 Buy More · 🟡 Keep

---

## ✅ Requirements and Libraries to run this script

- Python 3.10 or higher
- The following libraries:

```bash
pip3 install yfinance pandas tabulate
```

---

## 📂 Input File

The script reads a csv which I downloaded from Yahoo FInance, and named `paco_portfolio_20260517.csv`. The file is placed in the **same folder** as the script. At minimum, the file must have these three columns:

| Column | Description |
|---|---|
| `Symbol` | Stock ticker as listed on Yahoo Finance (e.g. `MFC.TO`, `XIU.TO`) |
| `Purchase Price` | The price per share I originally paid |
| `Quantity` | Number of shares I own |

> If the file has any additional columns, they are ignored.

---

## 🚀 How to use the script

```bash
# Default perdio fro the analysis: 6-month historiacl period
python3 paco_portfolio_analysis.py

# If you want to use a custom period
python3 paco_portfolio_analysis.py -p 1mo
python3 paco_portfolio_analysis.py -p 3mo
python3 paco_portfolio_analysis.py -p 6mo    # default
python3 paco_portfolio_analysis.py -p 1y
python3 paco_portfolio_analysis.py -p 2y
python3 paco_portfolio_analysis.py -p 5y
python3 paco_portfolio_analysis.py -p ytd

# Show all options
python3 paco_portfolio_analysis.py --help
```

---

## 📊 DEscription of each column in the Output Table

| Column | Description |
|---|---|
| **Symbol** | Stock ticker symbol |
| **Name** | Company name |
| **Price** | Latest market price |
| **Day%** | Price change since yesterday's close |
| **Pd Ret%** | Return over the chosen period (from the first day of the period to today) |
| **Pd Hi** | Highest price reached during the period |
| **Pd Lo** | Lowest price reached during the period |
| **Qty** | Number of shares held |
| **Avg Cost** | My original purchase price per share |
| **Cur Value** | Current market value of my position (Price × Qty) |
| **Gain/Loss** | Dollar difference between current value and what I paid |
| **Div Yield** | Annual dividend as a % of current price — a dash (—) means no dividend |
| **Strength** | How the current price sits within the period's range (see below) |
| **Signal** | Suggested action based on my portfolio performance and market status |

---

## 🔍 How Strength & signal Are Calculated

### 💪 Strength
Classify where the current price sits within its period high/low range — from 0 (at the lowest) to 1 (at the highest):

| Label | Meaning |
|---|---|
| **Strong** | Price is in the top 40% of the period range (≥ 60th percentile) |
| **Neutral** | Price is in the middle of the range |
| **Weak** | Price is in the bottom 35% of the period range |

### 📡 Signal
Combines your personal gains and losses (vs. purchase price) with the stock's market strength:

| Signal | Color | Condition |
|---|---|---|
| 🔴 **Sell** | Red | Down more than 20% from your initial cost, or losing money while the stock is near its period low |
| 🟢 **Buy More** | Green | Up more than 30% from your inmitial cost and price is near the period high |
| 🟡 **Keep** | Yellow | Everything else — hold and monitor over time |

> ⚠️ As usual, a very important note: my script was created as a practice for python, based on my own knowledge on stocks investment done by myself, and should be considered for informational and educational purposes only. This is not intended to be financial advice. These analysis and signals here are informational only and are not financial advice. I am sure there is more people whith much more knowledge on this topic.

---

## 🗂️ Structure of the script

| Section | Function | What it does |
|---|---|---|
| ⚙️ **Configuration** | Constants at the top | Sets the csv file path, supported periods, and terminal color codes. |
| 🖊️ **Argument parsing** | `parse_args()` | Reads the `-p` / `--period` flag from the command line |
| 📥 **CSV loading** | `load_holdings()` | Reads symbol, purchase price and quantity from the input file |
| 🌐 **Data fetching** | `fetch_quote()` | Downloads live quote and historical OHLCV data from Yahoo Finance for each ticker in the file |
| 📐 **Period position** | `week52_position()` | Calculates where the current price sits within the period's high/low range (0–1 score) |
| 💬 **Strength label** | `strength_label()` | Converts the 0–1 score into Strong / Neutral / Weak |
| 🚦 **Signal label** | `signal_label()` | Combines gains and losses (Profit & Losses) and strength score into a Sell / Keep / Buy More recommendation |
| 🏗️ **Table builder** | `build_table()` | Loops through all holdings, runs the calculations, and assembles the display rows |
| 🖨️ **Entry point** | `main()` | Orchestrates everything: loads data, builds the table, injects colors, and prints the report |

---

## 📦 Dependencies

| Library | Purpose |
|---|---|
| [`yfinance`](https://github.com/ranaroussi/yfinance) | Downloads live and historical stock data from Yahoo Finance |
| [`pandas`](https://pandas.pydata.org/) | Reads the CSV file and handles tabular data |
| [`tabulate`](https://github.com/astanin/python-tabulate) | Formats the terminal output as an aligned table |

---

## ⚠️ Another Disclaimer

This script is for **personal informational purposes only**. The signals and analysis it produces are based on simple heuristics and do **not** constitute financial advice at all (I am not FInancial Advisor). Always do your own due dulligence before making any investment decisions.
