# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Web dashboard for Deye solar inverters using the Solarman V5 protocol. Displays real-time solar production, battery status, grid power, and home consumption.

## Development Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run dashboard (http://localhost:8080)
python app.py

# Test inverter connection
python test_connection.py

# Scan available registers
python scan_registers.py
```

## Architecture

- `app.py` - Flask web server, serves dashboard and `/api/data` endpoint
- `inverter.py` - `DeyeInverter` class for Modbus communication
- `templates/index.html` - Dashboard UI with auto-refresh every 5 seconds

## Inverter Connection

- Uses `pysolarmanv5` library for Modbus over TCP
- Port 8899 (Solarman V5 protocol)
- **Use holding registers** (`read_holding_registers`), not input registers
- Slave ID: 1
- Configuration via environment variables: `INVERTER_IP`, `LOGGER_SERIAL`

## Key Registers (Holding)

| Register | Description | Scale |
|----------|-------------|-------|
| 514, 515 | PV1/PV2 Power | W |
| 586 | Battery Voltage | /100 V |
| 587 | Battery Current (signed) | /100 A |
| 588 | Battery SOC | % |
| 598 | Grid Voltage | /10 V |
| 607 | Grid Power (signed) | W |
| 653 | Load Power | W |
| 540, 541 | DC/Heatsink Temp | (val-1000)/10 °C |
| 502, 520, 521, 526 | Daily PV/Import/Export/Load | /10 kWh |
