# Telegram Bot for Battery & Grid Monitoring

## Overview

Telegram bot integrated into the Deye dashboard server that monitors battery SOC and grid status, sending notifications in 1800s literary Ukrainian style.

## Configuration

Environment variables:
- `TELEGRAM_BOT_TOKEN` — bot token from BotFather
- `TELEGRAM_ALLOWED_USERS` — comma-separated numeric user IDs

## Architecture

- `telegram_bot.py` — `TelegramBot` class with monitoring loop, message sending, command handling
- Background thread in `app.py` polling every 2 minutes
- Uses raw `requests` library to call Telegram HTTP API (no bot framework)

## Monitoring Logic

### Battery (SOC < 30%)
- Notify once when SOC drops below 30%
- Reset when SOC goes back above 30%
- No repeat notifications while low

### Grid Restore (voltage debounce)
- Grid "down" when `grid_voltage` < 50V
- Grid "restored" when voltage returns above 50V
- 1-minute debounce: state must be consistent across two consecutive polls (2-min interval)
- Only notify on grid restore, not on grid loss

## Bot Commands

- `/start` — replies with user's numeric Telegram ID
- `/test` — sends both sample messages (battery low + grid restored)

## Message Style

1800s literary Ukrainian (Kotlyarevsky/Shevchenko era), humorous.

## Deployment

- Add `telegram_bot.py` to `deploy.sh` FILES array
- Add `requests` to `requirements.txt`
- Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS` to remote `.env`
