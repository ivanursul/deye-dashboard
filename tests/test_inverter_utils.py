"""Tests for pure utility functions in inverter.py."""
from inverter import to_signed, voltage_to_soc, InverterConfig


class TestToSigned:
    def test_zero(self):
        assert to_signed(0) == 0

    def test_positive(self):
        assert to_signed(100) == 100

    def test_max_positive(self):
        assert to_signed(32767) == 32767

    def test_boundary_negative(self):
        assert to_signed(32768) == -32768

    def test_max_unsigned(self):
        assert to_signed(65535) == -1

    def test_midrange_negative(self):
        assert to_signed(65000) == -536


class TestVoltageToSoc:
    def test_above_max(self):
        assert voltage_to_soc(60.0) == 100

    def test_exact_max(self):
        assert voltage_to_soc(57.6) == 100

    def test_below_min(self):
        assert voltage_to_soc(40.0) == 0

    def test_exact_min(self):
        assert voltage_to_soc(48.0) == 0

    def test_midrange(self):
        # 52.0V is the (52.0, 50) point in the curve
        assert voltage_to_soc(52.0) == 50

    def test_high_interpolation(self):
        # Between (53.6, 90) and (53.2, 80)
        result = voltage_to_soc(53.4)
        assert 80 <= result <= 90

    def test_low_interpolation(self):
        # Between (51.2, 30) and (50.4, 17)
        result = voltage_to_soc(50.8)
        assert 17 <= result <= 30

    def test_returns_int(self):
        assert isinstance(voltage_to_soc(52.5), int)


class TestInverterConfigToDict:
    def test_default_config(self):
        config = InverterConfig()
        d = config.to_dict()
        assert d == {
            "phases": 3,
            "has_battery": True,
            "pv_strings": 2,
            "has_generator": False,
        }

    def test_with_generator(self):
        config = InverterConfig(has_generator=True)
        d = config.to_dict()
        assert d["has_generator"] is True
