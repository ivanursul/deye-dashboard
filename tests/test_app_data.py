"""Tests for data recording functions in app.py."""
import json
import os
import pytest
from unittest.mock import patch
from datetime import datetime, timedelta


class TestRecordGridDailyImport:
    def test_creates_new_log(self, tmp_path):
        log_file = str(tmp_path / "grid_log.json")
        with patch("app.GRID_DAILY_LOG_FILE", log_file):
            from app import record_grid_daily_import
            record_grid_daily_import(5.5)
        with open(log_file) as f:
            log = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        assert log[today] == 5.5

    def test_overwrites_same_day(self, tmp_path):
        log_file = str(tmp_path / "grid_log.json")
        today = datetime.now().strftime("%Y-%m-%d")
        with open(log_file, "w") as f:
            json.dump({today: 3.0}, f)
        with patch("app.GRID_DAILY_LOG_FILE", log_file):
            from app import record_grid_daily_import
            record_grid_daily_import(7.0)
        with open(log_file) as f:
            log = json.load(f)
        assert log[today] == 7.0

    def test_90_day_rotation(self, tmp_path):
        log_file = str(tmp_path / "grid_log.json")
        # Create 95 days of entries
        base = datetime.now()
        old_log = {}
        for i in range(95):
            day = (base - timedelta(days=i)).strftime("%Y-%m-%d")
            old_log[day] = float(i)
        with open(log_file, "w") as f:
            json.dump(old_log, f)
        with patch("app.GRID_DAILY_LOG_FILE", log_file):
            from app import record_grid_daily_import
            record_grid_daily_import(1.0)
        with open(log_file) as f:
            log = json.load(f)
        assert len(log) <= 90


class TestTrackGeneratorRuntime:
    def _reset_globals(self):
        """Reset global state before each test."""
        import app
        app.generator_last_running = None
        app.generator_session_start = None

    def test_off_to_on_starts_session(self, tmp_path):
        self._reset_globals()
        log_file = str(tmp_path / "gen_log.json")
        with patch("app.GENERATOR_LOG_FILE", log_file):
            import app
            app.track_generator_runtime(1000)  # power > 0 = running
        with open(log_file) as f:
            log = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        assert len(log[today]["sessions"]) == 1
        assert log[today]["sessions"][0]["end"] is None

    def test_on_to_off_closes_session(self, tmp_path):
        self._reset_globals()
        log_file = str(tmp_path / "gen_log.json")
        with patch("app.GENERATOR_LOG_FILE", log_file):
            import app
            # First: start running
            app.track_generator_runtime(1000)
            # Simulate 60s elapsed
            app.generator_session_start = datetime.now() - timedelta(seconds=60)
            # Then: stop running
            app.track_generator_runtime(0)
        with open(log_file) as f:
            log = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        assert log[today]["runtime_seconds"] >= 59
        assert log[today]["sessions"][-1]["end"] is not None

    def test_stays_off_no_session(self, tmp_path):
        self._reset_globals()
        log_file = str(tmp_path / "gen_log.json")
        with patch("app.GENERATOR_LOG_FILE", log_file):
            import app
            app.track_generator_runtime(0)
            app.track_generator_runtime(0)
        with open(log_file) as f:
            log = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        assert log[today]["sessions"] == []

    def test_stays_on_no_duplicate(self, tmp_path):
        self._reset_globals()
        log_file = str(tmp_path / "gen_log.json")
        with patch("app.GENERATOR_LOG_FILE", log_file):
            import app
            app.track_generator_runtime(1000)
            app.track_generator_runtime(1000)
        with open(log_file) as f:
            log = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        assert len(log[today]["sessions"]) == 1

    def test_90_day_rotation(self, tmp_path):
        self._reset_globals()
        log_file = str(tmp_path / "gen_log.json")
        base = datetime.now()
        old_log = {}
        for i in range(95):
            day = (base - timedelta(days=i)).strftime("%Y-%m-%d")
            old_log[day] = {"runtime_seconds": 0, "sessions": []}
        with open(log_file, "w") as f:
            json.dump(old_log, f)
        with patch("app.GENERATOR_LOG_FILE", log_file):
            import app
            app.track_generator_runtime(0)
        with open(log_file) as f:
            log = json.load(f)
        assert len(log) <= 90


class TestRecordPhaseSample:
    def _reset_globals(self):
        import app
        app.last_sample_time = None
        app.last_history_save = None
        app.phase_accumulator = {"l1": 0, "l2": 0, "l3": 0}

    def test_first_sample_no_energy(self, tmp_path):
        self._reset_globals()
        stats_file = str(tmp_path / "phase_stats.json")
        history_file = str(tmp_path / "phase_history.json")
        with patch("app.PHASE_STATS_FILE", stats_file), \
             patch("app.PHASE_HISTORY_FILE", history_file):
            import app
            app.record_phase_sample(100, 200, 300)
        with open(stats_file) as f:
            stats = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        assert stats[today]["samples"] == 1
        # No energy accumulated on first sample (no previous time)
        assert stats[today]["l1_wh"] == 0

    def test_energy_accumulation(self, tmp_path):
        self._reset_globals()
        stats_file = str(tmp_path / "phase_stats.json")
        history_file = str(tmp_path / "phase_history.json")
        with patch("app.PHASE_STATS_FILE", stats_file), \
             patch("app.PHASE_HISTORY_FILE", history_file):
            import app
            # First sample: sets last_sample_time
            app.record_phase_sample(1000, 2000, 3000)
            # Simulate 60 seconds elapsed
            app.last_sample_time = datetime.now() - timedelta(seconds=60)
            # Second sample
            app.record_phase_sample(1000, 2000, 3000)
        with open(stats_file) as f:
            stats = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        # 1000W * (60s/3600) = ~16.67 Wh
        assert stats[today]["l1_wh"] > 15
        assert stats[today]["l1_wh"] < 20

    def test_large_interval_skipped(self, tmp_path):
        self._reset_globals()
        stats_file = str(tmp_path / "phase_stats.json")
        history_file = str(tmp_path / "phase_history.json")
        with patch("app.PHASE_STATS_FILE", stats_file), \
             patch("app.PHASE_HISTORY_FILE", history_file):
            import app
            app.record_phase_sample(1000, 2000, 3000)
            # Simulate 10 minutes elapsed (> 5 min threshold)
            app.last_sample_time = datetime.now() - timedelta(minutes=10)
            app.record_phase_sample(1000, 2000, 3000)
        with open(stats_file) as f:
            stats = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        # Energy should NOT have been accumulated (interval > 0.1 hours = 6 min)
        assert stats[today]["l1_wh"] == 0

    def test_max_tracking(self, tmp_path):
        self._reset_globals()
        stats_file = str(tmp_path / "phase_stats.json")
        history_file = str(tmp_path / "phase_history.json")
        with patch("app.PHASE_STATS_FILE", stats_file), \
             patch("app.PHASE_HISTORY_FILE", history_file):
            import app
            app.record_phase_sample(100, 200, 300)
            app.last_sample_time = datetime.now() - timedelta(seconds=30)
            app.record_phase_sample(500, 600, 700)
        with open(stats_file) as f:
            stats = json.load(f)
        today = datetime.now().strftime("%Y-%m-%d")
        assert stats[today]["l1_max"] == 500
        assert stats[today]["l2_max"] == 600
        assert stats[today]["l3_max"] == 700


class TestSaveToPhaseHistory:
    def test_appends_data_point(self, tmp_path):
        history_file = str(tmp_path / "phase_history.json")
        with patch("app.PHASE_HISTORY_FILE", history_file):
            from app import save_to_phase_history
            now = datetime.now()
            save_to_phase_history(now, 100, 200, 300)
        with open(history_file) as f:
            history = json.load(f)
        today = now.strftime("%Y-%m-%d")
        assert len(history[today]) == 1
        assert history[today][0]["l1"] == 100

    def test_7_day_rotation(self, tmp_path):
        history_file = str(tmp_path / "phase_history.json")
        base = datetime.now()
        old_history = {}
        for i in range(10):
            day = (base - timedelta(days=i)).strftime("%Y-%m-%d")
            old_history[day] = [{"time": "12:00:00", "l1": 0, "l2": 0, "l3": 0}]
        with open(history_file, "w") as f:
            json.dump(old_history, f)
        with patch("app.PHASE_HISTORY_FILE", history_file):
            from app import save_to_phase_history
            save_to_phase_history(base, 100, 200, 300)
        with open(history_file) as f:
            history = json.load(f)
        assert len(history) <= 7
