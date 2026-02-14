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
    has_generator: bool = False

    def to_dict(self):
        return {
            "phases": self.phases,
            "has_battery": self.has_battery,
            "pv_strings": self.pv_strings,
            "has_generator": self.has_generator,
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
        self.disconnect()
        logger.info("Connecting to inverter at %s:%d (serial=%d)", self.ip, self.port, self.serial)
        self.inverter = PySolarmanV5(
            address=self.ip,
            serial=self.serial,
            port=self.port,
            mb_slave_id=1,
            verbose=False,
            socket_timeout=10
        )
        logger.info("Connected to inverter")

    def disconnect(self):
        """Close connection."""
        if self.inverter:
            logger.debug("Disconnecting from inverter")
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
        if self.config.phases == 1:
            return self._read_1p_data_unlocked(battery_sampler)
        return self._read_3p_data_unlocked(battery_sampler)

    def _read_1p_data_unlocked(self, battery_sampler=None) -> dict:
        """Read all data from single-phase hybrid inverter (Sunsynk register map)."""
        data = {}

        try:
            if not self.inverter:
                self.connect()

            # Solar PV
            data["pv1_power"] = self.read_register(186)
            time.sleep(0.05)
            if self.config.pv_strings >= 2:
                data["pv2_power"] = self.read_register(187)
                time.sleep(0.05)
            else:
                data["pv2_power"] = 0
            data["pv_total_power"] = data["pv1_power"] + data["pv2_power"]

            # Battery
            if self.config.has_battery:
                data["battery_voltage"] = self.read_register(183) / 100
                time.sleep(0.05)
                raw_current = self.read_register(191)
                data["battery_current"] = -to_signed(raw_current) / 100
                time.sleep(0.05)

                raw_soc = self.read_register(184)
                time.sleep(0.05)
                data["battery_soc_raw"] = raw_soc

                data["battery_capacity"] = self.read_register(107)
                time.sleep(0.05)
                data["battery_nominal_voltage"] = self.read_register(236) / 100
                time.sleep(0.05)
                data["battery_discharge_percent"] = self.read_register(237)
                time.sleep(0.05)

                available_capacity = (data["battery_capacity"] / 100) * data["battery_discharge_percent"]
                data["battery_max_available_capacity_wh"] = available_capacity * data["battery_nominal_voltage"]

                if battery_sampler:
                    smoothed_v = battery_sampler.get_voltage()
                    if smoothed_v is not None:
                        data["battery_voltage"] = smoothed_v
                    smoothed_soc = battery_sampler.get_soc()
                    if smoothed_soc is not None:
                        data["battery_soc"] = smoothed_soc
                    else:
                        data["battery_soc"] = raw_soc
                else:
                    data["battery_soc"] = raw_soc
                data["battery_power"] = int(data["battery_voltage"] * data["battery_current"])
            else:
                data["battery_voltage"] = 0
                data["battery_current"] = 0
                data["battery_soc"] = 0
                data["battery_soc_raw"] = 0
                data["battery_power"] = 0

            # Grid
            data["grid_voltage"] = self.read_register(150) / 10
            time.sleep(0.05)
            raw_grid_power = self.read_register(169)
            data["grid_power"] = to_signed(raw_grid_power)
            time.sleep(0.05)

            # Load
            data["load_power"] = self.read_register(178)
            time.sleep(0.05)
            data["load_l1"] = self.read_register(176)
            time.sleep(0.05)

            # Temperatures
            data["dc_temp"] = (self.read_register(90) - 1000) / 10
            time.sleep(0.05)
            data["heatsink_temp"] = (self.read_register(91) - 1000) / 10
            time.sleep(0.05)

            # Daily stats
            data["daily_pv"] = self.read_register(108) / 10
            time.sleep(0.05)
            data["daily_grid_import"] = self.read_register(76) / 10
            time.sleep(0.05)
            data["daily_grid_export"] = self.read_register(77) / 10
            time.sleep(0.05)
            data["daily_load"] = self.read_register(84) / 10
            time.sleep(0.05)

            # Generator (GEN/GRID2 port) — 1-phase Sunsynk uses register 166
            if self.config.has_generator:
                data["generator_power"] = self.read_register(166)
                time.sleep(0.05)
            else:
                data["generator_power"] = 0

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
        finally:
            self.disconnect()

        return data

    def _read_3p_data_unlocked(self, battery_sampler=None) -> dict:
        """Read all data from 3-phase hybrid inverter (original register map)."""
        data = {}

        try:
            if not self.inverter:
                self.connect()
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

                # SOC from register 588 (BMS-reported, same as Solarman)
                # Use smoothed median from sampler if available for outlier rejection
                raw_soc = self.read_register(588)
                time.sleep(0.05)
                data["battery_soc_raw"] = raw_soc

                if battery_sampler:
                    smoothed_v = battery_sampler.get_voltage()
                    if smoothed_v is not None:
                        data["battery_voltage"] = smoothed_v
                    smoothed_soc = battery_sampler.get_soc()
                    if smoothed_soc is not None:
                        data["battery_soc"] = smoothed_soc
                    else:
                        data["battery_soc"] = raw_soc
                else:
                    data["battery_soc"] = raw_soc
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

            # Generator (GEN/GRID2 port) — 3-phase uses register 667
            if self.config.has_generator:
                data["generator_power"] = self.read_register(667)
                time.sleep(0.05)
            else:
                data["generator_power"] = 0

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
            logger.warning("Error reading inverter data: %s", e)
            data["error"] = str(e)
        finally:
            self.disconnect()

        return data

    def detect_config(self):
        """Auto-detect inverter configuration by reading diagnostic registers.

        Two-stage detection:
        Stage 1 — Read L2/L3 voltage to determine phase count.
        Stage 2 — Read battery voltage and PV2 power using the register map
                   appropriate for the detected phase count (3-phase vs Sunsynk).
        Takes 3 samples per stage with 2s delay; any positive reading wins.
        """
        # --- Stage 1: detect phase count ---
        phases_3 = False

        for i in range(3):
            logger.info("detect_config stage 1: taking sample %d/3 (phase detection)", i + 1)
            with self.lock:
                if not self.inverter:
                    self.connect()

                v_l2 = v_l3 = 0
                try:
                    v_l2 = self.read_register(645) / 10
                    time.sleep(0.05)
                    v_l3 = self.read_register(646) / 10
                    time.sleep(0.05)
                except Exception as e:
                    logger.info("detect_config stage 1: L2/L3 voltage read failed: %s", e)

            logger.info(
                "detect_config stage 1: sample %d — v_l2=%.1f v_l3=%.1f",
                i + 1, v_l2, v_l3,
            )

            if v_l2 > 50 or v_l3 > 50:
                phases_3 = True

            if i < 2:
                time.sleep(2)

        detected_phases = 3 if phases_3 else 1
        logger.info("detect_config stage 1 result: phases=%d", detected_phases)

        # --- Stage 2: detect battery & PV2 using correct register map ---
        if detected_phases == 3:
            bat_reg, pv2_reg = 587, 515
        else:
            bat_reg, pv2_reg = 183, 187
        logger.info(
            "detect_config stage 2: using %s register map (battery=%d, pv2=%d)",
            "3-phase" if detected_phases == 3 else "single-phase (Sunsynk)",
            bat_reg, pv2_reg,
        )

        has_battery = False
        pv2_detected = False

        for i in range(3):
            logger.info("detect_config stage 2: taking sample %d/3 (battery & PV2)", i + 1)
            with self.lock:
                if not self.inverter:
                    self.connect()

                bat_v = 0
                try:
                    bat_v = self.read_register(bat_reg) / 100
                    time.sleep(0.05)
                except Exception as e:
                    logger.info("detect_config stage 2: battery voltage read failed: %s", e)

                pv2_w = 0
                try:
                    pv2_w = self.read_register(pv2_reg)
                except Exception as e:
                    logger.info("detect_config stage 2: PV2 power read failed: %s", e)

            logger.info(
                "detect_config stage 2: sample %d — bat_v=%.2f (reg %d) pv2_w=%d (reg %d)",
                i + 1, bat_v, bat_reg, pv2_w, pv2_reg,
            )

            if bat_v > 10:
                has_battery = True
            if pv2_w > 0:
                pv2_detected = True

            if i < 2:
                time.sleep(2)

        if not has_battery:
            logger.warning(
                "detect_config: battery voltage was 0 in all samples "
                "(may be unreliable during glitches), defaulting to has_battery=True"
            )
            has_battery = True

        if not pv2_detected:
            logger.warning(
                "detect_config: PV2 power was 0 in all samples "
                "(may be unreliable at night), defaulting to 2 strings"
            )
            pv2_detected = True

        # --- Stage 3: detect generator (GEN/GRID2 port) ---
        gen_reg = 667 if detected_phases == 3 else 166
        logger.info(
            "detect_config stage 3: using register %d for generator detection",
            gen_reg,
        )

        has_generator = False

        for i in range(3):
            logger.info("detect_config stage 3: taking sample %d/3 (generator)", i + 1)
            with self.lock:
                if not self.inverter:
                    self.connect()

                gen_w = 0
                try:
                    gen_w = self.read_register(gen_reg)
                except Exception as e:
                    logger.info("detect_config stage 3: generator read failed: %s", e)

            logger.info(
                "detect_config stage 3: sample %d — gen_w=%d (reg %d)",
                i + 1, gen_w, gen_reg,
            )

            if gen_w > 0:
                has_generator = True

            if i < 2:
                time.sleep(2)

        logger.info("detect_config stage 3 result: has_generator=%s", has_generator)

        config = InverterConfig(
            phases=detected_phases,
            has_battery=has_battery,
            pv_strings=2 if pv2_detected else 1,
            has_generator=has_generator,
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
        self._soc_buffer = []
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._disabled = False

    def _sample(self):
        """Read battery voltage and SOC once, store if valid."""
        if self.inverter.config.phases == 1:
            reg_voltage, reg_soc = 183, 184
        else:
            reg_voltage, reg_soc = 587, 588
        try:
            with self.inverter.lock:
                if not self.inverter.inverter:
                    self.inverter.connect()
                raw_v = self.inverter.read_register(reg_voltage)
                raw_soc = self.inverter.read_register(reg_soc)
                self.inverter.disconnect()
            voltage = raw_v / 100
        except Exception as e:
            logger.warning("BatterySampler: failed to read battery registers: %s", e)
            return

        with self._lock:
            if 46.0 <= voltage <= 58.0:
                self._buffer.append(voltage)
                if len(self._buffer) > self.buffer_size:
                    self._buffer.pop(0)
            else:
                logger.warning("BatterySampler: discarding implausible voltage %.2fV", voltage)

            if 0 <= raw_soc <= 100:
                self._soc_buffer.append(raw_soc)
                if len(self._soc_buffer) > self.buffer_size:
                    self._soc_buffer.pop(0)
            else:
                logger.warning("BatterySampler: discarding implausible SOC %d%%", raw_soc)

    def get_voltage(self):
        """Return averaged voltage from buffer, or None if no valid readings."""
        with self._lock:
            if not self._buffer:
                return None
            return sum(self._buffer) / len(self._buffer)

    def get_soc(self):
        """Return SOC from register 588 using median to reject outliers."""
        with self._lock:
            if not self._soc_buffer:
                return None
            return sorted(self._soc_buffer)[len(self._soc_buffer) // 2]

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
