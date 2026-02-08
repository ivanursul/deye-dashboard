"""Deye inverter data reader module."""
from dataclasses import dataclass
from pysolarmanv5 import PySolarmanV5
import time
import threading
import logging

logger = logging.getLogger(__name__)


@dataclass
class InverterConfig:
    """Configuration describing the inverter's capabilities."""
    phases: int = 3         # 1 or 3
    has_battery: bool = True
    pv_strings: int = 2     # 1 or 2

    def to_dict(self):
        return {
            "phases": self.phases,
            "has_battery": self.has_battery,
            "pv_strings": self.pv_strings,
        }


def to_signed(value):
    """Convert unsigned 16-bit to signed."""
    if value >= 32768:
        return value - 65536
    return value


LIFEPO4_16S_CURVE = [
    (57.6, 100), (56.0, 99), (54.4, 95), (53.6, 90),
    (53.2, 80), (52.8, 70), (52.4, 60), (52.0, 50),
    (51.6, 40), (51.2, 30), (50.4, 17), (48.0, 0),
]


def voltage_to_soc(voltage):
    """Convert LiFePO4 16S battery voltage to SOC using discharge curve."""
    if voltage >= LIFEPO4_16S_CURVE[0][0]:
        return 100
    if voltage <= LIFEPO4_16S_CURVE[-1][0]:
        return 0
    # Find the two points to interpolate between
    for i in range(len(LIFEPO4_16S_CURVE) - 1):
        v_high, soc_high = LIFEPO4_16S_CURVE[i]
        v_low, soc_low = LIFEPO4_16S_CURVE[i + 1]
        if voltage >= v_low:
            ratio = (voltage - v_low) / (v_high - v_low)
            return int(soc_low + ratio * (soc_high - soc_low))
    return 0


class DeyeInverter:
    def __init__(self, ip: str, serial: int, port: int = 8899,
                 config: InverterConfig = None):
        self.ip = ip
        self.serial = serial
        self.port = port
        self.config = config or InverterConfig()
        self.inverter = None
        self.lock = threading.Lock()

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

    def read_all_data(self, battery_sampler=None) -> dict:
        """Read all inverter data and return as dictionary."""
        with self.lock:
            return self._read_all_data_unlocked(battery_sampler)

    def _read_all_data_unlocked(self, battery_sampler=None) -> dict:
        """Internal: read all data (caller must hold self.lock)."""
        if not self.inverter:
            self.connect()

        data = {}

        try:
            # Solar PV
            data["pv1_power"] = self.read_register(514)
            time.sleep(0.05)
            if self.config.pv_strings >= 2:
                data["pv2_power"] = self.read_register(515)
                time.sleep(0.05)
            else:
                data["pv2_power"] = 0
            data["pv_total_power"] = data["pv1_power"] + data["pv2_power"]

            # Battery
            if self.config.has_battery:
                data["battery_voltage"] = self.read_register(587) / 100
                time.sleep(0.05)
                raw_current = self.read_register(586)
                data["battery_current"] = -to_signed(raw_current) / 100
                time.sleep(0.05)

                # Calculate SOC from voltage for LiFePO4 16S battery
                # 56V max, 48V min
                # Use smoothed voltage from sampler if available
                if battery_sampler:
                    smoothed_v = battery_sampler.get_voltage()
                    if smoothed_v is not None:
                        data["battery_voltage"] = smoothed_v
                        data["battery_soc"] = battery_sampler.get_soc()
                    else:
                        data["battery_soc"] = voltage_to_soc(data["battery_voltage"])
                else:
                    data["battery_soc"] = voltage_to_soc(data["battery_voltage"])

                # Store raw register value for debugging
                data["battery_soc_raw"] = self.read_register(588)
                time.sleep(0.05)
                data["battery_power"] = int(data["battery_voltage"] * data["battery_current"])
            else:
                data["battery_voltage"] = 0
                data["battery_current"] = 0
                data["battery_soc"] = 0
                data["battery_soc_raw"] = 0
                data["battery_power"] = 0

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
            if self.config.phases == 3:
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
            if self.config.has_battery:
                if data["battery_current"] > 0:
                    data["battery_status"] = "Charging"
                elif data["battery_current"] < 0:
                    data["battery_status"] = "Discharging"
                else:
                    data["battery_status"] = "Idle"
            else:
                data["battery_status"] = "N/A"

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

    def detect_config(self):
        """Auto-detect inverter configuration by reading diagnostic registers.

        Reads L2/L3 voltage, battery voltage, and PV2 power to infer
        whether the system is 3-phase, has a battery, and has 2 PV strings.
        Takes 3 samples with 2s delay; any positive reading wins.
        """
        phases_3 = False
        has_battery = False
        pv2_detected = False

        for i in range(3):
            try:
                with self.lock:
                    if not self.inverter:
                        self.connect()
                    v_l2 = self.read_register(645) / 10
                    time.sleep(0.05)
                    v_l3 = self.read_register(646) / 10
                    time.sleep(0.05)
                    bat_v = self.read_register(587) / 100
                    time.sleep(0.05)
                    pv2_w = self.read_register(515)

                if v_l2 > 50 or v_l3 > 50:
                    phases_3 = True
                if bat_v > 10:
                    has_battery = True
                if pv2_w > 0:
                    pv2_detected = True

            except Exception:
                logger.warning("detect_config: sample %d failed", i + 1)

            if i < 2:
                time.sleep(2)

        if not pv2_detected:
            logger.warning(
                "detect_config: PV2 power was 0 in all samples "
                "(may be unreliable at night), defaulting to 2 strings"
            )
            pv2_detected = True

        config = InverterConfig(
            phases=3 if phases_3 else 1,
            has_battery=has_battery,
            pv_strings=2 if pv2_detected else 1,
        )
        logger.info("Auto-detected inverter config: %s", config)
        return config


class BatterySampler:
    """Reads battery voltage periodically and provides smoothed values."""

    def __init__(self, inverter, interval=10, buffer_size=6):
        self.inverter = inverter
        self.interval = interval
        self.buffer_size = buffer_size
        self._buffer = []
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._disabled = False

    def _sample(self):
        """Read battery voltage once, store if valid."""
        try:
            with self.inverter.lock:
                if not self.inverter.inverter:
                    self.inverter.connect()
                raw = self.inverter.read_register(587)
            voltage = raw / 100
        except Exception:
            logger.debug("BatterySampler: failed to read voltage")
            return

        with self._lock:
            if 46.0 <= voltage <= 58.0:
                self._buffer.append(voltage)
                if len(self._buffer) > self.buffer_size:
                    self._buffer.pop(0)
            else:
                logger.warning("BatterySampler: discarding implausible reading %.2fV", voltage)

    def get_voltage(self):
        """Return averaged voltage from buffer, or None if no valid readings."""
        with self._lock:
            if not self._buffer:
                return None
            return sum(self._buffer) / len(self._buffer)

    def get_soc(self):
        """Return SOC based on averaged voltage, or None if no valid readings."""
        voltage = self.get_voltage()
        if voltage is None:
            return None
        return voltage_to_soc(voltage)

    def _run(self):
        """Main sampling loop."""
        while self._running:
            self._sample()
            time.sleep(self.interval)

    def start(self):
        """Start sampling in a background thread. Skips if inverter has no battery."""
        if not self.inverter.config.has_battery:
            self._disabled = True
            logger.info("BatterySampler: skipping start (no battery configured)")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop sampling."""
        self._running = False
