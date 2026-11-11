INSTALL
Replace 1.sp500-drop.py at repository root.
Replace existing workflow with .github/workflows/1.sp500-drop.yaml; do not duplicate schedules.
Add requirements-sp500.txt at root.
Keep TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as repository Actions secrets.
Run Actions > 1 Daily SP500 Adjusted Moves > Run workflow.
Manual run first sends Telegram connection test; missing messages leave error in Actions.
Schedule weekdays 21:30 UTC. End-of-day scanner, NOT an immediate intraday alert.
Universe: external S&P500 list, not all US stocks or Excel portfolio.
Thresholds: adjusted daily >=+7%, <=-7%, or two-session <=-14%.
Adj Close includes Yahoo corporate-action adjustments; do not add dividends again.
Close dollar quote and raw price variations are displayed separately.
repair=True attempts fixes, not a guarantee: missing special dividends may still cause false signals.
No-hit summaries enabled. Insufficient coverage (<90%) raises an error and attempts notification.
CSV diagnostics are saved as Actions artifacts when the scan reaches calculation.
Manual runs can include current unfinished session: use after close for final daily alerts.
Full downloaded history is 3 months; provider requests may be throttled.
Dependencies have version ranges, not a tested lockfile.
Syntax and synthetic decision checks tested; no live Yahoo or Telegram validation performed.
Never paste tokens in code, chat, or logs.
