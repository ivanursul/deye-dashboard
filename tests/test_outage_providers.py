"""Tests for outage provider factory, HTML parsing, and schedule status."""
import pytest
from unittest.mock import patch
from datetime import datetime, timedelta

from outage_providers.base import create_outage_provider, OutageSchedulePoller
from outage_providers.lvivoblenergo import LvivoblenergoProvider, parse_group_windows
from outage_providers.yasno import YasnoProvider


class TestCreateOutageProvider:
    def test_none_returns_none(self):
        assert create_outage_provider("none") is None

    def test_lvivoblenergo(self):
        provider = create_outage_provider("lvivoblenergo", group="4.1")
        assert isinstance(provider, LvivoblenergoProvider)
        assert provider.group == "4.1"

    def test_yasno(self):
        provider = create_outage_provider(
            "yasno", group="2.1", region_id="25", dso_id="902"
        )
        assert isinstance(provider, YasnoProvider)
        assert provider.group == "2.1"
        assert provider.region_id == 25
        assert provider.dso_id == 902

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown outage provider"):
            create_outage_provider("unknown_provider")


class TestParseGroupWindows:
    def test_single_window(self):
        html = "<p>Група 4.1. з 09:00 до 12:00</p>"
        windows = parse_group_windows(html, "4.1")
        assert windows == [(9, 0, 12, 0)]

    def test_multiple_windows(self):
        html = "<p>Група 4.1. з 09:00 до 12:00, з 18:00 до 21:00</p>"
        windows = parse_group_windows(html, "4.1")
        assert windows == [(9, 0, 12, 0), (18, 0, 21, 0)]

    def test_group_not_found(self):
        html = "<p>Група 3.2. з 09:00 до 12:00</p>"
        windows = parse_group_windows(html, "4.1")
        assert windows == []

    def test_empty_html(self):
        windows = parse_group_windows("", "4.1")
        assert windows == []


class TestOutageSchedulePollerStatus:
    def _make_poller(self, windows, last_updated=None):
        """Helper to create a poller with pre-set state."""
        provider = LvivoblenergoProvider(group="4.1")
        poller = OutageSchedulePoller(provider=provider)
        poller._windows = windows
        poller._last_updated = last_updated
        return poller

    def test_unknown_when_never_fetched(self):
        poller = self._make_poller([], last_updated=None)
        status = poller.get_outage_status()
        assert status["status"] == "unknown"

    def test_active_during_window(self):
        # Fixed time: 12:30, inside window 12:00-13:00
        now = datetime.now().replace(hour=12, minute=30, second=0, microsecond=0)
        poller = self._make_poller(
            [(12, 0, 13, 0)],
            last_updated=now,
        )
        with patch("outage_providers.base.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            status = poller.get_outage_status()
        assert status["status"] == "active"
        assert "remaining_minutes" in status
        assert status["remaining_minutes"] >= 0

    def test_upcoming_before_window(self):
        # Use a fixed time (10:00) so +2h doesn't cross midnight
        now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        poller = self._make_poller(
            [(12, 0, 13, 0)],  # window from 12:00-13:00
            last_updated=now,
        )
        with patch("outage_providers.base.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            status = poller.get_outage_status()
        assert status["status"] == "upcoming"
        assert len(status["upcoming_windows"]) == 1

    def test_clear_all_past(self):
        # Fixed time: 15:00, past window 8:00-10:00
        now = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
        poller = self._make_poller(
            [(8, 0, 10, 0)],
            last_updated=now,
        )
        with patch("outage_providers.base.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            status = poller.get_outage_status()
        assert status["status"] == "clear"

    def test_midnight_crossing(self):
        """Window (22,0,24,0) should create end_dt as next day midnight."""
        now = datetime.now().replace(hour=22, minute=30, second=0, microsecond=0)
        poller = self._make_poller(
            [(22, 0, 24, 0)],
            last_updated=now,
        )
        with patch("outage_providers.base.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            status = poller.get_outage_status()
        assert status["status"] == "active"
        # end_time should be next day midnight
        assert status["end_time"].hour == 0
        assert status["end_time"].day == now.day + 1

    def test_electricity_start_tracks_last_ended_window(self):
        """electricity_start should be the end of the last past window."""
        # Fixed time: 12:00. Past window 8:00-11:00, future window 14:00-15:00
        now = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        poller = self._make_poller(
            [
                (8, 0, 11, 0),   # past window (ended at 11:00)
                (14, 0, 15, 0),  # future window
            ],
            last_updated=now,
        )
        with patch("outage_providers.base.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            status = poller.get_outage_status()
        assert status["status"] == "upcoming"
        assert "electricity_start" in status
        assert status["electricity_start"].hour == 11

    def test_multiple_upcoming(self):
        """All future windows should be returned in the upcoming list."""
        # Fixed time: 10:00. Two future windows at 14:00-15:00 and 18:00-19:00
        now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        poller = self._make_poller(
            [
                (14, 0, 15, 0),
                (18, 0, 19, 0),
            ],
            last_updated=now,
        )
        with patch("outage_providers.base.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            status = poller.get_outage_status()
        assert status["status"] == "upcoming"
        assert len(status["upcoming_windows"]) == 2
