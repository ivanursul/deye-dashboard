"""Deye inverter data reader module."""
from pysolarmanv5 import PySolarmanV5
import time


def to_signed(value):
    """Convert unsigned 16-bit to signed."""
    if value >= 32768:
        return value - 65536
    return value


class DeyeInverter:
    def __init__(self, ip: str, serial: int, port: int = 8899):
        self.ip = ip
        self.serial = serial
        self.port = port
        self.inverter = None

    def connect(self):
        """Establish connection to inverter."""
        self.inverter = PySolarmanV5(
            address=self.ip,
            serial=self.serial,
            port=self.port,
            mb_slave_id=1,
            verbose=False,
            socket_timeout=10
        )

    def disconnect(self):
        """Close connection."""
        if self.inverter:
            self.inverter.disconnect()
            self.inverter = None

    def read_register(self, address: int) -> int:
        """Read a single holding register."""
        return self.inverter.read_holding_registers(address, 1)[0]

    def read_all_data(self) -> dict:
        """Read all inverter data and return as dictionary."""
        if not self.inverter:
            self.connect()

        data = {}

        try:
            # Solar PV
            data["pv1_power"] = self.read_register(514)
            time.sleep(0.05)
            data["pv2_power"] = self.read_register(515)
            time.sleep(0.05)
            data["pv_total_power"] = data["pv1_power"] + data["pv2_power"]

            # Battery
            data["battery_voltage"] = self.read_register(587) / 100
            time.sleep(0.05)
            raw_current = self.read_register(588)
            data["battery_current"] = to_signed(raw_current) / 100
            time.sleep(0.05)
            data["battery_soc"] = self.read_register(589)
            time.sleep(0.05)
            data["battery_power"] = int(data["battery_voltage"] * data["battery_current"])

            # Grid
            data["grid_voltage"] = self.read_register(598) / 10
            time.sleep(0.05)
            raw_grid_power = self.read_register(607)
            data["grid_power"] = to_signed(raw_grid_power)
            time.sleep(0.05)

            # Load
            data["load_power"] = self.read_register(653)
            time.sleep(0.05)

            # Temperatures
            data["dc_temp"] = (self.read_register(540) - 1000) / 10
            time.sleep(0.05)
            data["heatsink_temp"] = (self.read_register(541) - 1000) / 10
            time.sleep(0.05)

            # Daily stats
            data["daily_pv"] = self.read_register(502) / 10
            time.sleep(0.05)
            data["daily_grid_import"] = self.read_register(520) / 10
            time.sleep(0.05)
            data["daily_grid_export"] = self.read_register(521) / 10
            time.sleep(0.05)
            data["daily_load"] = self.read_register(526) / 10
            time.sleep(0.05)

            # Phase data (3-phase system)
            data["load_l1"] = self.read_register(650)
            time.sleep(0.05)
            data["load_l2"] = self.read_register(651)
            time.sleep(0.05)
            data["load_l3"] = self.read_register(652)
            time.sleep(0.05)

            data["voltage_l1"] = self.read_register(644) / 10
            time.sleep(0.05)
            data["voltage_l2"] = self.read_register(645) / 10
            time.sleep(0.05)
            data["voltage_l3"] = self.read_register(646) / 10

            # Status indicators
            if data["battery_current"] > 0:
                data["battery_status"] = "Charging"
            elif data["battery_current"] < 0:
                data["battery_status"] = "Discharging"
            else:
                data["battery_status"] = "Idle"

            if data["grid_power"] > 0:
                data["grid_status"] = "Importing"
            elif data["grid_power"] < 0:
                data["grid_status"] = "Exporting"
            else:
                data["grid_status"] = "Idle"

        except Exception as e:
            data["error"] = str(e)
            self.disconnect()

        return data
