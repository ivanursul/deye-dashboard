# "Коли включать світло?" Button Design

## Overview

A Telegram bot button that answers "when will the power come back?" by combining Lvivoblenergo's outage schedule with real-time battery status to give smart, actionable responses in 1800s literary Ukrainian.

## Data Source

**API**: `https://api.loe.lviv.ua/api/menus?page=1&type=photo-grafic`

- Public JSON API, no auth, no Cloudflare
- Returns `hydra:member[0].menuItems[]` — find item with `name == "Today"`
- Parse `rawHtml` field: each `<p>` contains a group's schedule
- Format: `Група 4.1. Електроенергії немає з HH:MM до HH:MM.`
- Multiple windows: `з HH:MM до HH:MM, з HH:MM до HH:MM`

## Architecture

### OutageSchedulePoller (new file: `outage_schedule.py`)

- Background thread polls the API every 60 seconds
- Parses HTML for configurable group (env var `OUTAGE_GROUP`, default `4.1`)
- Stores parsed outage windows in memory: list of `(start_time, end_time)` tuples
- Thread-safe via `threading.Lock`
- `get_outage_status()` returns:
  - `("active", end_time, remaining_minutes)` — currently in outage
  - `("upcoming", [(start, end), ...])` — no outage now but scheduled later today
  - `("clear", None)` — no outages today
  - `("unknown", None)` — API unreachable / no data

### Integration

- **`app.py`**: Create `OutageSchedulePoller` at startup, pass to `TelegramBot`
- **`telegram_bot.py`**: Add "Коли включать світло?" button to keyboard, handle presses
- **Battery estimation**: Use `battery_sampler.get_soc()`, current `load_power` from inverter, and 15kWh total capacity to estimate if battery survives the outage

### Battery Survival Calculation

```
available_kwh = 15.0 * (soc / 100)
outage_hours = (end - start) in hours
needed_kwh = load_power_w / 1000 * outage_hours
can_survive = available_kwh >= needed_kwh * 1.1  (10% safety margin)
tight = available_kwh >= needed_kwh * 0.7
```

## Response Scenarios (1800s literary Ukrainian, 3 rotating variants each)

### 1. Currently in outage
Shows time remaining until power returns.

### 2. Power is on, outage scheduled later — battery is fine
Reassure that battery has enough charge.

### 3. Power is on, outage scheduled later — battery is tight
Warn that it might not last, suggest reducing consumption.

### 4. Power is on, outage scheduled later — battery is low
Strong warning that battery won't survive the outage.

### 5. No outages today
Celebrate.

### 6. API unreachable
Apologize, suggest checking poweron.loe.lviv.ua manually.

## Configuration

- `OUTAGE_GROUP` — outage group (default: `4.1`)
- `BATTERY_CAPACITY_KWH` — total usable battery capacity (default: `15.0`)

## Files Changed

1. `outage_schedule.py` — New file: `OutageSchedulePoller` class
2. `telegram_bot.py` — Add button, handler, response messages
3. `app.py` — Create poller, pass to bot
