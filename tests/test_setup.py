"""Tests for setup.py load_existing_env and write_env."""
import os
import pytest

from setup import load_existing_env, write_env


class TestLoadExistingEnv:
    def test_no_file_returns_empty(self, tmp_path):
        values, extra = load_existing_env(str(tmp_path / "nonexistent.env"))
        assert values == {}
        assert extra == []

    def test_parses_managed_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("INVERTER_IP=192.168.1.100\nLOGGER_SERIAL=12345\n")
        values, extra = load_existing_env(str(env_file))
        assert values["INVERTER_IP"] == "192.168.1.100"
        assert values["LOGGER_SERIAL"] == "12345"
        assert extra == []

    def test_extra_keys_in_extra_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "INVERTER_IP=1.2.3.4\n"
            "CUSTOM_KEY=custom_value\n"
        )
        values, extra = load_existing_env(str(env_file))
        assert "INVERTER_IP" in values
        assert "CUSTOM_KEY" not in values
        assert "CUSTOM_KEY=custom_value" in extra

    def test_comments_and_blanks_ignored(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# This is a comment\n"
            "\n"
            "INVERTER_IP=1.2.3.4\n"
            "  \n"
            "# Another comment\n"
        )
        values, extra = load_existing_env(str(env_file))
        assert values == {"INVERTER_IP": "1.2.3.4"}
        assert extra == []


class TestWriteEnv:
    def test_basic_output(self, tmp_path):
        env_file = str(tmp_path / ".env")
        values = {
            "INVERTER_IP": "192.168.1.100",
            "LOGGER_SERIAL": "12345",
            "WEATHER_LATITUDE": "49.84",
            "WEATHER_LONGITUDE": "24.03",
            "OUTAGE_PROVIDER": "lvivoblenergo",
            "OUTAGE_GROUP": "4.1",
            "TELEGRAM_ENABLED": "false",
        }
        write_env(values, [], path=env_file)
        content = open(env_file).read()
        assert "INVERTER_IP=192.168.1.100" in content
        assert "LOGGER_SERIAL=12345" in content
        assert "OUTAGE_PROVIDER=lvivoblenergo" in content
        assert "OUTAGE_GROUP=4.1" in content

    def test_generator_section_when_enabled(self, tmp_path):
        env_file = str(tmp_path / ".env")
        values = {
            "INVERTER_IP": "1.2.3.4",
            "LOGGER_SERIAL": "99",
            "OUTAGE_PROVIDER": "none",
            "TELEGRAM_ENABLED": "false",
            "INVERTER_HAS_GENERATOR": "true",
            "GENERATOR_FUEL_RATE": "2.5",
        }
        write_env(values, [], path=env_file)
        content = open(env_file).read()
        assert "INVERTER_HAS_GENERATOR=true" in content
        assert "GENERATOR_FUEL_RATE=2.5" in content
        assert "# Generator" in content

    def test_no_generator_section_when_disabled(self, tmp_path):
        env_file = str(tmp_path / ".env")
        values = {
            "INVERTER_IP": "1.2.3.4",
            "LOGGER_SERIAL": "99",
            "OUTAGE_PROVIDER": "none",
            "TELEGRAM_ENABLED": "false",
            "INVERTER_HAS_GENERATOR": "false",
        }
        write_env(values, [], path=env_file)
        content = open(env_file).read()
        assert "INVERTER_HAS_GENERATOR" not in content
        assert "# Generator" not in content

    def test_extra_lines_appended(self, tmp_path):
        env_file = str(tmp_path / ".env")
        values = {
            "INVERTER_IP": "1.2.3.4",
            "LOGGER_SERIAL": "99",
            "OUTAGE_PROVIDER": "none",
            "TELEGRAM_ENABLED": "false",
        }
        extra = ["DEPLOY_HOST=server.example.com", "DEPLOY_USER=admin"]
        write_env(values, extra, path=env_file)
        content = open(env_file).read()
        assert "# Additional settings" in content
        assert "DEPLOY_HOST=server.example.com" in content
        assert "DEPLOY_USER=admin" in content
