from pysolarmanv5 import PySolarmanV5
import time
import os

INVERTER_IP = os.environ.get("INVERTER_IP", "0.0.0.0")
LOGGER_SERIAL = int(os.environ.get("LOGGER_SERIAL", "0"))

print("Connecting to Deye inverter...")

try:
    inverter = PySolarmanV5(
        address=INVERTER_IP,
        serial=LOGGER_SERIAL,
        port=8899,
        mb_slave_id=1,
        verbose=False,
        socket_timeout=10
    )

    # Read battery SOC from holding register 588
    result = inverter.read_holding_registers(588, 1)
    print(f"✅ Connection successful!")
    print(f"   Battery SOC: {result[0]}%")

    # Read a few more registers
    pv_power = inverter.read_holding_registers(514, 1)
    print(f"   Total PV Power: {pv_power[0]} W")

    inverter.disconnect()
    print("✅ Disconnected successfully")

except Exception as e:
    print(f"❌ Error: {e}")
