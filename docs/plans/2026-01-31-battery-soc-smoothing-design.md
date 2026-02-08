# Battery SOC Smoothing Design

## Problem

Single Modbus reads of battery voltage can return 0 due to communication glitches with the inverter logger. Since SOC is calculated from voltage, a single bad read causes SOC to show 0% momentarily. This triggers false low-battery alerts in the Telegram bot and incorrect dashboard display.

## Solution

Add a `BatterySampler` class that reads battery voltage every 10 seconds, stores readings in a rolling buffer (last 60 seconds), discards 0-values as glitches, and exposes averaged voltage/SOC for all consumers.

## Design

### BatterySampler class (in inverter.py)

- Background thread reads register 587 (battery voltage) every 10 seconds
- Circular buffer of last 6 readings (~60 seconds)
- 0-values are discarded as communication errors (real LiFePO4 battery never reads 0V)
- `get_voltage()` → average of valid readings in buffer, or `None` if no valid readings
- `get_soc()` → applies LiFePO4 voltage-to-SOC formula (48V-56V) to averaged voltage, or `None`
- Thread-safe: uses `threading.Lock` for buffer access
- Uses same lock for inverter communication (pysolarmanv5 is not thread-safe)

### Integration

- **inverter.py**: `read_all_data()` accepts optional `battery_sampler` param. If provided and sampler has valid data, uses smoothed voltage/SOC. Falls back to single read otherwise. `battery_soc_raw` (register 588) continues to be read for debugging.
- **app.py**: Creates one `BatterySampler` at startup, passes to `/api/data` handler and `TelegramBot`. Sampler thread starts once.
- **telegram_bot.py**: No changes needed — already calls `inverter.read_all_data()` which returns smoothed values.

### Edge Cases

- **Startup (< 6 readings)**: Average whatever valid readings exist, even just 1
- **All reads 0**: `get_voltage()` returns `None`, `read_all_data()` falls back to single register read
- **Thread safety**: Lock protects both buffer access and inverter communication so sampler and `read_all_data()` never access Modbus simultaneously

## Files Changed

1. `inverter.py` — Add `BatterySampler` class, add lock to `DeyeInverter`, update `read_all_data()` signature
2. `app.py` — Create and start `BatterySampler`, pass to `read_all_data()` calls and `TelegramBot`
