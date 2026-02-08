"""Scan for battery voltage register on Deye inverter."""
from pysolarmanv5 import PySolarmanV5
import time
import os

INVERTER_IP = os.environ.get("INVERTER_IP", "0.0.0.0")
LOGGER_SERIAL = int(os.environ.get("LOGGER_SERIAL", "0"))

# Registers that might contain battery voltage
# Based on various Deye models documentation
BATTERY_REGISTERS = list(range(580, 620)) + list(range(100, 130)) + list(range(210, 250))

print("Scanning for battery voltage register...")
print("Look for a value that matches your actual battery voltage (typically 48-58V for 48V system)")
print("=" * 80)

try:
    inverter = PySolarmanV5(
        address=INVERTER_IP,
        serial=LOGGER_SERIAL,
        port=8899,
        mb_slave_id=1,
        verbose=False,
        socket_timeout=10
    )

    results = []

    for reg in BATTERY_REGISTERS:
        try:
            time.sleep(0.1)
            raw = inverter.read_holding_registers(reg, 1)[0]

            # Try different scaling factors
            div10 = raw / 10
            div100 = raw / 100
            div1 = raw

            # Only show registers with values in plausible battery voltage ranges
            # 48V system: 40-60V typical, but also check for raw values
            if (40 <= div10 <= 70) or (40 <= div100 <= 70) or (40 <= div1 <= 70):
                results.append({
                    'reg': reg,
                    'raw': raw,
                    'div10': div10,
                    'div100': div100,
                    'div1': div1
                })
                print(f"  Reg {reg:4d}: raw={raw:6d}  /1={div1:6.1f}V  /10={div10:6.2f}V  /100={div100:6.3f}V")
        except Exception as e:
            pass  # Skip unreadable registers

    print("\n" + "=" * 80)
    print("LIKELY CANDIDATES (values between 40-60V with some scaling):")
    print("=" * 80)

    for r in results:
        print(f"  Register {r['reg']}: raw={r['raw']}")
        if 40 <= r['div1'] <= 70:
            print(f"    -> {r['div1']:.1f}V (no scaling)")
        if 40 <= r['div10'] <= 70:
            print(f"    -> {r['div10']:.2f}V (divide by 10)")
        if 40 <= r['div100'] <= 70:
            print(f"    -> {r['div100']:.3f}V (divide by 100)")

    inverter.disconnect()
    print("\nDone. Compare these values to your actual battery voltage.")

except Exception as e:
    print(f"Connection error: {e}")
