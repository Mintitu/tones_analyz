WEEKLY PORTFOLIO REPORT
Install weekly_portfolio.py and requirements-weekly.txt at root.
Install workflow as .github/workflows/weekly-portfolio.yaml.
Disable old weekly analysis workflow if it produces duplicate reports; other stock-watch workflows are separate.
Keep the Excel at root; set PORTFOLIO_FILE in YAML to its actual filename when updated.
Add analiza.md at root or docs/analiza.md. It is included verbatim as context, NOT auto-interpreted.
Keep Telegram secrets if delivery required. No tokens in code.
Schedule Saturday 06:00 UTC; run manually in Actions.
Default: latest completed calendar trading week, ending on a past Friday.
Friday manual runs use previous Friday to avoid an incomplete current week.
Optional WEEK_END environment variable: past Friday YYYY-MM-DD.
Uses NYSE calendar and exact period dates; no silently shortened windows.
Market price data uses Yahoo only in this weekly extension, not the previous hybrid fetcher.
No Excel holdings/history data are invented if unavailable.
Raw history, CSV, Excel report and Markdown report are saved as workflow artifacts.
Do not treat this as verified live analysis or automatic investment orders.
SPCX.US is mapped mechanically to SPCX; identity/listing must be checked. No substitute security is guessed.
Old portfolio snapshots imply unchanged quantities and cost; estimates are not actual account returns.
Syntax checked and Excel parser tested locally; live Yahoo and Telegram NOT tested.
