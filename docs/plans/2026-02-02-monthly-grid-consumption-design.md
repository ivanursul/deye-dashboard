# Monthly Grid Consumption Telegram Button

## Problem

The grid operator requires monthly grid import figures. The inverter provides a daily counter (register 520) that resets each day. There is no built-in way to get monthly totals from the local Solarman V5 protocol.

## Solution

1. **Daily grid import recorder** — save `daily_grid_import` to `grid_daily_log.json` on every inverter poll cycle (overwriting current day's entry). This is resilient to app restarts.
2. **Telegram bot button** — new keyboard button that sums daily values for current and previous month, displays the totals.

## Data Format

`grid_daily_log.json`:
```json
{
  "2026-01-15": 4.2,
  "2026-01-16": 3.8
}
```

Values are in kWh (matching register 520 / 10).

## Telegram Button

Label: "📊 Спожито з мережі"

Output example:
```
📊 Споживання з мережі

Лютий 2026 (поточний):
15.3 кВт·год (1-2 лютого)

Січень 2026:
142.7 кВт·год
```

## Implementation

### app.py
- Add `GRID_DAILY_LOG_FILE` config
- In `InverterPoller._fetch()`, after reading data, save `daily_grid_import` to the log file
- Helper functions: `load_grid_daily_log()`, `save_grid_daily_log()`

### telegram_bot.py
- Add keyboard button "📊 Спожито з мережі"
- Add `/grid` command alias
- Add `_handle_grid_consumption()` handler
- Accept `grid_daily_log_file` parameter in constructor
- Helper to sum values for a given month
- Ukrainian-style message formatting
