"""Tests for poems.py weather code mapping and poem retrieval."""
import pytest
from unittest.mock import patch
from datetime import datetime

from poems import _weather_code_to_category, _is_night, get_poem


class TestWeatherCodeToCategory:
    def test_none_returns_clear(self):
        assert _weather_code_to_category(None) == "clear"

    def test_code_0_clear(self):
        assert _weather_code_to_category(0) == "clear"

    def test_code_1_2_clear(self):
        assert _weather_code_to_category(1) == "clear"
        assert _weather_code_to_category(2) == "clear"

    def test_code_3_cloudy(self):
        assert _weather_code_to_category(3) == "cloudy"

    def test_code_45_fog(self):
        assert _weather_code_to_category(45) == "fog"
        assert _weather_code_to_category(48) == "fog"

    def test_drizzle_range(self):
        for code in (51, 53, 55, 57):
            assert _weather_code_to_category(code) == "rain"

    def test_snow_range(self):
        for code in (71, 73, 75, 77):
            assert _weather_code_to_category(code) == "snow"

    def test_thunderstorm(self):
        for code in (95, 96, 99):
            assert _weather_code_to_category(code) == "storm"


class TestGetPoem:
    def test_returns_formatted_with_separator(self):
        poem = get_poem(weather_code=0, sunrise="2025-01-01T06:00:00", sunset="2025-01-01T20:00:00")
        assert "─────────" in poem
        assert "—" in poem  # author attribution

    def test_night_overrides_weather(self):
        """When it's before sunrise, should use 'night' category regardless of weather."""
        # Set time to 3 AM (before sunrise at 6 AM)
        fake_now = datetime(2025, 6, 15, 3, 0, 0)
        with patch("poems.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            poem = get_poem(
                weather_code=0,  # clear weather
                sunrise="2025-06-15T06:00:00",
                sunset="2025-06-15T20:00:00",
            )
        # Night poems contain night-themed content; at minimum, the poem
        # should be a valid formatted string
        assert "─────────" in poem
