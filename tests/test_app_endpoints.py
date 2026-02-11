"""Tests for Flask API endpoints in app.py."""
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timedelta

from inverter import InverterConfig


@pytest.fixture
def client():
    """Create a Flask test client with mocked pollers."""
    import app as app_module

    app_module.app.config["TESTING"] = True

    # Store originals
    orig_inverter_poller = app_module.inverter_poller
    orig_outage_poller = app_module.outage_poller
    orig_weather_poller = app_module.weather_poller
    orig_inverter_config = app_module.inverter_config

    # Create mock pollers
    mock_inv_poller = MagicMock()
    mock_weather_poller = MagicMock()

    app_module.inverter_poller = mock_inv_poller
    app_module.weather_poller = mock_weather_poller
    app_module.inverter_config = InverterConfig(phases=3, has_battery=True, pv_strings=2, has_generator=False)

    with app_module.app.test_client() as c:
        yield c, mock_inv_poller, app_module

    # Restore originals
    app_module.inverter_poller = orig_inverter_poller
    app_module.outage_poller = orig_outage_poller
    app_module.weather_poller = orig_weather_poller
    app_module.inverter_config = orig_inverter_config


class TestGetData:
    def test_503_when_no_data(self, client):
        c, mock_inv, _ = client
        type(mock_inv).data = PropertyMock(return_value=None)
        resp = c.get("/api/data")
        assert resp.status_code == 503

    def test_returns_data_with_config(self, client):
        c, mock_inv, app_module = client
        type(mock_inv).data = PropertyMock(return_value={
            "pv_total_power": 500,
            "battery_soc": 75,
            "grid_power": -100,
        })
        app_module.outage_poller = None
        resp = c.get("/api/data")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["pv_total_power"] == 500
        assert "config" in data
        assert data["config"]["phases"] == 3


class TestGetPhaseStats:
    def test_empty_stats_returns_empty_list(self, client):
        c, _, app_module = client
        with patch.object(app_module, "load_phase_stats", return_value={}):
            resp = c.get("/api/phase-stats")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_calculates_percentages(self, client):
        c, _, app_module = client
        stats = {
            "2025-01-15": {
                "l1_wh": 1000, "l2_wh": 2000, "l3_wh": 3000,
                "samples": 100, "l1_max": 500, "l2_max": 1000, "l3_max": 1500,
            }
        }
        with patch.object(app_module, "load_phase_stats", return_value=stats):
            resp = c.get("/api/phase-stats")
        data = resp.get_json()
        assert len(data) == 1
        entry = data[0]
        assert entry["l1_pct"] == pytest.approx(16.7, abs=0.1)
        assert entry["l2_pct"] == pytest.approx(33.3, abs=0.1)
        assert entry["l3_pct"] == pytest.approx(50.0, abs=0.1)

    def test_zero_total_no_division_error(self, client):
        c, _, app_module = client
        stats = {
            "2025-01-15": {
                "l1_wh": 0, "l2_wh": 0, "l3_wh": 0,
                "samples": 1, "l1_max": 0, "l2_max": 0, "l3_max": 0,
            }
        }
        with patch.object(app_module, "load_phase_stats", return_value=stats):
            resp = c.get("/api/phase-stats")
        assert resp.status_code == 200
        entry = resp.get_json()[0]
        assert entry["l1_pct"] == 0
        assert entry["l2_pct"] == 0
        assert entry["l3_pct"] == 0


class TestGetOutageSchedule:
    def test_disabled_returns_disabled(self, client):
        c, _, app_module = client
        app_module.outage_poller = None
        resp = c.get("/api/outage_schedule")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "disabled"

    def test_active_outage_returns_times(self, client):
        c, _, app_module = client
        now = datetime.now()
        mock_poller = MagicMock()
        mock_poller.get_outage_status.return_value = {
            "status": "active",
            "start_time": now - timedelta(minutes=30),
            "end_time": now + timedelta(minutes=30),
            "remaining_minutes": 30,
        }
        app_module.outage_poller = mock_poller
        resp = c.get("/api/outage_schedule")
        data = resp.get_json()
        assert data["status"] == "active"
        assert "start_time" in data
        assert "end_time" in data
        assert data["remaining_minutes"] == 30


class TestAddOutage:
    def test_start_event_appended(self, client):
        c, _, app_module = client
        with patch.object(app_module, "load_outage_history", return_value=[]), \
             patch.object(app_module, "save_outage_history") as mock_save:
            resp = c.post("/api/outages", json={
                "type": "start",
                "timestamp": "2025-01-15T10:00:00",
                "voltage": 0,
            })
        assert resp.status_code == 200
        saved = mock_save.call_args[0][0]
        assert len(saved) == 1
        assert saved[0]["type"] == "start"

    def test_end_event_calculates_duration(self, client):
        c, _, app_module = client
        existing = [{
            "id": 1,
            "type": "start",
            "timestamp": "2025-01-15T10:00:00",
            "voltage": 0,
        }]
        with patch.object(app_module, "load_outage_history", return_value=existing), \
             patch.object(app_module, "save_outage_history") as mock_save:
            resp = c.post("/api/outages", json={
                "type": "end",
                "timestamp": "2025-01-15T11:00:00",
                "voltage": 230,
            })
        assert resp.status_code == 200
        saved = mock_save.call_args[0][0]
        # The start event should have been updated with duration
        assert saved[0]["duration"] == 3600  # 1 hour in seconds


class TestGetGenerator:
    def test_disabled_returns_false(self, client):
        c, _, app_module = client
        app_module.inverter_config = InverterConfig(has_generator=False)
        resp = c.get("/api/generator")
        data = resp.get_json()
        assert data["enabled"] is False

    def test_running_with_fuel_data(self, client):
        c, mock_inv, app_module = client
        app_module.inverter_config = InverterConfig(has_generator=True)
        type(mock_inv).data = PropertyMock(return_value={"generator_power": 3000})
        with patch.object(app_module, "load_generator_log", return_value={}), \
             patch("app.GENERATOR_FUEL_RATE", 2.5), \
             patch("app.GENERATOR_OIL_CHANGE_DATE", ""), \
             patch("app.generator_session_start", None):
            resp = c.get("/api/generator")
        data = resp.get_json()
        assert data["enabled"] is True
        assert data["running"] is True
        assert data["power"] == 3000


class TestGetWeather:
    def test_503_when_no_data(self, client):
        c, _, app_module = client
        type(app_module.weather_poller).data = PropertyMock(return_value=None)
        resp = c.get("/api/weather")
        assert resp.status_code == 503

    def test_returns_data(self, client):
        c, _, app_module = client
        type(app_module.weather_poller).data = PropertyMock(return_value={
            "temperature": 22.5,
            "weather_code": 0,
        })
        resp = c.get("/api/weather")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["temperature"] == 22.5


class TestClearEndpoints:
    def test_clear_outages_and_phase_stats(self, client):
        c, _, app_module = client
        with patch.object(app_module, "save_outage_history") as mock_outage, \
             patch.object(app_module, "save_phase_stats") as mock_phase, \
             patch.object(app_module, "save_phase_history") as mock_hist:
            resp1 = c.post("/api/outages/clear")
            resp2 = c.post("/api/phase-stats/clear")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        mock_outage.assert_called_once_with([])
        mock_phase.assert_called_once_with({})
        mock_hist.assert_called_once_with({})
