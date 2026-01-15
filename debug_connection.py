from pysolarmanv5 import PySolarmanV5
import time

INVERTER_IP = "192.168.1.157"
LOGGER_SERIAL = 1234567890

# Common Deye register addresses to try
test_registers = [
    (0x003B, "Battery SOC (0x003B/59)"),
    (0x006D, "Battery SOC (0x006D/109)"),
    (588, "Battery SOC (588)"),
    (514, "Total PV Power (514)"),
    (529, "Grid Power (529)"),
    (500, "Device Type (500)"),
    (0, "First register (0)"),
    (1, "Register 1"),
]

print("Testing connection to Deye inverter...")
print(f"IP: {INVERTER_IP}, Serial: {LOGGER_SERIAL}")
print("=" * 60)

for slave_id in [1]:
    print(f"\n--- Slave ID {slave_id} ---")

    try:
        inverter = PySolarmanV5(
            address=INVERTER_IP,
            serial=LOGGER_SERIAL,
            port=8899,
            mb_slave_id=slave_id,
            verbose=True,  # Enable verbose for debugging
            socket_timeout=10
        )

        # Try input registers
        print("\n📖 Testing INPUT registers:")
        for reg_addr, desc in test_registers:
            try:
                time.sleep(0.3)
                result = inverter.read_input_registers(reg_addr, 1)
                print(f"  ✅ {desc}: {result[0]}")
            except Exception as e:
                print(f"  ❌ {desc}: {type(e).__name__}")

        # Try holding registers
        print("\n📝 Testing HOLDING registers:")
        for reg_addr, desc in test_registers[:4]:
            try:
                time.sleep(0.3)
                result = inverter.read_holding_registers(reg_addr, 1)
                print(f"  ✅ {desc}: {result[0]}")
            except Exception as e:
                print(f"  ❌ {desc}: {type(e).__name__}")

        inverter.disconnect()

    except Exception as e:
        print(f"Connection error: {e}")
