"""Scan for phase-related registers on Deye inverter."""
from pysolarmanv5 import PySolarmanV5
import time
import os

INVERTER_IP = os.environ.get("INVERTER_IP", "192.168.1.157")
LOGGER_SERIAL = int(os.environ.get("LOGGER_SERIAL", "1234567890"))

# Common Deye 3-phase register addresses
PHASE_REGISTERS = {
    # Grid phase voltages
    598: "Grid Voltage L1 (0.1V)",
    599: "Grid Current L1 (0.1A)",
    600: "Grid Voltage L2 (0.1V)",
    601: "Grid Current L2 (0.1A)",
    602: "Grid Voltage L3 (0.1V)",
    603: "Grid Current L3 (0.1A)",

    # Grid phase power
    604: "Grid Frequency (0.01Hz)",
    607: "Total Grid Power (W)",
    608: "Grid Power L1 (W)",
    609: "Grid Power L2 (W)",
    610: "Grid Power L3 (W)",

    # Load phase data
    644: "Load Voltage L1 (0.1V)",
    645: "Load Voltage L2 (0.1V)",
    646: "Load Voltage L3 (0.1V)",
    650: "Load Power L1 (W)",
    651: "Load Power L2 (W)",
    652: "Load Power L3 (W)",
    653: "Total Load Power (W)",

    # Alternative registers
    625: "Grid Power L1 alt (W)",
    626: "Grid Power L2 alt (W)",
    627: "Grid Power L3 alt (W)",

    # CT/External readings
    616: "External CT L1 (W)",
    617: "External CT L2 (W)",
    618: "External CT L3 (W)",

    # More phase registers
    678: "Phase A Power (W)",
    679: "Phase B Power (W)",
    680: "Phase C Power (W)",
}

print("Scanning for phase-related registers...")
print("=" * 70)

try:
    inverter = PySolarmanV5(
        address=INVERTER_IP,
        serial=LOGGER_SERIAL,
        port=8899,
        mb_slave_id=1,
        verbose=False,
        socket_timeout=10
    )

    for reg, desc in sorted(PHASE_REGISTERS.items()):
        try:
            time.sleep(0.1)
            value = inverter.read_holding_registers(reg, 1)[0]

            # Handle signed values for power
            if "Power" in desc or "CT" in desc:
                if value >= 32768:
                    value = value - 65536

            # Apply scaling
            display = value
            if "0.1V" in desc or "0.1A" in desc:
                display = value / 10
            elif "0.01Hz" in desc:
                display = value / 100

            print(f"  {reg:4d}: {value:7d}  -> {display:8.1f}  ({desc})")

        except Exception as e:
            print(f"  {reg:4d}: ERROR - {type(e).__name__}")

    inverter.disconnect()
    print("\n✅ Scan complete")

except Exception as e:
    print(f"❌ Connection error: {e}")
