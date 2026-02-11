"""Tests for build_inverter_config() env var logic."""
import pytest
from unittest.mock import patch, MagicMock
from inverter import InverterConfig, DeyeInverter


class TestBuildInverterConfig:
    def _build(self, env_vars, detect_result=None, detect_raises=False):
        """Helper that imports and calls build_inverter_config with env overrides."""
        with patch("inverter.PySolarmanV5"):
            inv = DeyeInverter(ip="192.168.1.1", serial=123456)
            inv.inverter = MagicMock()

            if detect_raises:
                inv.detect_config = MagicMock(side_effect=Exception("timeout"))
            elif detect_result:
                inv.detect_config = MagicMock(return_value=detect_result)
            else:
                inv.detect_config = MagicMock(
                    return_value=InverterConfig(phases=3, has_battery=True, pv_strings=2, has_generator=False)
                )

            with patch.dict("os.environ", env_vars, clear=False):
                # Remove any existing env vars that might interfere
                for key in ["INVERTER_PHASES", "INVERTER_HAS_BATTERY",
                            "INVERTER_PV_STRINGS", "INVERTER_HAS_GENERATOR"]:
                    if key not in env_vars:
                        import os
                        os.environ.pop(key, None)

                from app import build_inverter_config
                return build_inverter_config(inv), inv

    def test_all_env_vars_skips_detect(self):
        env = {
            "INVERTER_PHASES": "1",
            "INVERTER_HAS_BATTERY": "true",
            "INVERTER_PV_STRINGS": "1",
            "INVERTER_HAS_GENERATOR": "false",
        }
        config, inv = self._build(env)
        assert config.phases == 1
        assert config.has_battery is True
        assert config.pv_strings == 1
        assert config.has_generator is False
        inv.detect_config.assert_not_called()

    def test_partial_env_falls_back(self):
        env = {"INVERTER_PHASES": "1"}
        detected = InverterConfig(phases=3, has_battery=True, pv_strings=2, has_generator=True)
        config, inv = self._build(env, detect_result=detected)
        # phases from env, rest from detect
        assert config.phases == 1
        assert config.has_battery is True
        assert config.pv_strings == 2
        assert config.has_generator is True
        inv.detect_config.assert_called_once()

    def test_no_env_auto_detects(self):
        detected = InverterConfig(phases=3, has_battery=True, pv_strings=2, has_generator=False)
        config, inv = self._build({}, detect_result=detected)
        assert config.phases == 3
        assert config.has_battery is True
        assert config.pv_strings == 2
        inv.detect_config.assert_called_once()

    def test_detect_failure_uses_defaults(self):
        config, inv = self._build({}, detect_raises=True)
        # Should fall back to InverterConfig() defaults
        assert config.phases == 3
        assert config.has_battery is True
        assert config.pv_strings == 2
        assert config.has_generator is False

    def test_generator_env_true(self):
        env = {
            "INVERTER_PHASES": "3",
            "INVERTER_HAS_BATTERY": "true",
            "INVERTER_PV_STRINGS": "2",
            "INVERTER_HAS_GENERATOR": "true",
        }
        config, _ = self._build(env)
        assert config.has_generator is True

    def test_generator_env_false(self):
        env = {
            "INVERTER_PHASES": "3",
            "INVERTER_HAS_BATTERY": "true",
            "INVERTER_PV_STRINGS": "2",
            "INVERTER_HAS_GENERATOR": "false",
        }
        config, _ = self._build(env)
        assert config.has_generator is False

    def test_boolean_variants(self):
        """'yes', '1', 'True' should all work as truthy."""
        for val in ("yes", "1", "True"):
            env = {
                "INVERTER_PHASES": "3",
                "INVERTER_HAS_BATTERY": val,
                "INVERTER_PV_STRINGS": "2",
                "INVERTER_HAS_GENERATOR": val,
            }
            config, _ = self._build(env)
            assert config.has_battery is True, f"Failed for {val}"
            assert config.has_generator is True, f"Failed for {val}"
