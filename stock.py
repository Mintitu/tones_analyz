import os
import requests
import yfinance as yf
# Preluare automată din secretele de pe GitHub
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
