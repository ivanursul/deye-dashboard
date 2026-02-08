#!/bin/bash
set -e

# Load .env but disable Telegram bot for local development
set -a
source .env
set +a

export TELEGRAM_ENABLED=false

# Activate virtual environment
source venv/bin/activate

echo "Starting Deye Dashboard locally (Telegram bot disabled)..."
python3 app.py
