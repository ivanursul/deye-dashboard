"""Deye Dashboard - Simple web dashboard for Deye solar inverters."""
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from flask import Flask, render_template, jsonify, request
from inverter import DeyeInverter, BatterySampler, InverterConfig
from telegram_bot import TelegramBot
from outage_providers import OutageSchedulePoller, create_outage_provider
from update_manager import get_current_version, UpdatePoller, UpdateManager
from datetime import datetime, date
import os
import json
import logging
import threading
import time
import requests

WEATHER_LATITUDE = os.environ.get("WEATHER_LATITUDE", "0.0")
WEATHER_LONGITUDE = os.environ.get("WEATHER_LONGITUDE", "0.0")
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={WEATHER_LATITUDE}&longitude={WEATHER_LONGITUDE}"
    "&current=temperature_2m,weather_code"
    "&daily=sunrise,sunset,temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code"
    "&timezone=auto&forecast_days=1"
)

logger = logging.getLogger(__name__)


class WeatherPoller:
    """Polls Open-Meteo API for current weather conditions."""

    def __init__(self, poll_interval=900):
        self.poll_interval = poll_interval
        self._cache = {}
        self._lock = threading.Lock()

    def _fetch(self):
        try:
            resp = requests.get(OPEN_METEO_URL, timeout=15)
            if not resp.ok:
                logger.warning("Open-Meteo API returned %s", resp.status_code)
                return
            raw = resp.json()
            current = raw.get("current", {})
            daily = raw.get("daily", {})
            result = {
                "temperature": current.get("temperature_2m"),
                "weather_code": current.get("weather_code"),
                "sunrise": daily.get("sunrise", [None])[0],
                "sunset": daily.get("sunset", [None])[0],
                "temp_max": daily.get("temperature_2m_max", [None])[0],
                "temp_min": daily.get("temperature_2m_min", [None])[0],
                "precipitation": daily.get("precipitation_sum", [None])[0],
                "daily_weather_code": daily.get("weather_code", [None])[0],
                "last_updated": datetime.now().isoformat(),
            }
            with self._lock:
                self._cache = result
            logger.info("Weather updated: %.1f°C code=%s", result.get("temperature", 0), result.get("weather_code"))
        except Exception:
            logger.exception("Error fetching weather data")

    @property
    def data(self):
        with self._lock:
            return dict(self._cache) if self._cache else None

    def _run(self):
        while True:
            self._fetch()
            time.sleep(self.poll_interval)

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()


INVERTER_CACHE_FILE = os.environ.get("INVERTER_CACHE_FILE", "inverter_cache.json")
INVERTER_CACHE_MAX_AGE = 300  # seconds – serve cached data if fresher than 5 min


class InverterPoller:
    """Polls inverter for current data in a background thread."""

    def __init__(self, inverter, battery_sampler, poll_interval=60,
                 cache_file=None):
        self.inverter = inverter
        self.battery_sampler = battery_sampler
        self.poll_interval = poll_interval
        self._cache = {}
        self._lock = threading.Lock()
        self.cache_file = cache_file
        self._load_cache()

    def _load_cache(self):
        """Load last inverter data from file if fresh enough."""
        if not self.cache_file or not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, "r") as f:
                data = json.load(f)
            last = data.get("last_updated")
            if last:
                age = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
                if age < INVERTER_CACHE_MAX_AGE:
                    with self._lock:
                        self._cache = data
                    logger.info("Loaded inverter cache (%.0fs old)", age)
                else:
                    logger.info("Inverter cache too old (%.0fs), ignoring", age)
        except Exception:
            logger.exception("Failed to load inverter cache")

    def _save_cache(self):
        """Persist latest inverter data to file."""
        if not self.cache_file:
            return
        try:
            with self._lock:
                data = dict(self._cache)
            with open(self.cache_file, "w") as f:
                json.dump(data, f)
        except Exception:
            logger.exception("Failed to save inverter cache")

    def _fetch(self):
        try:
            t0 = time.time()
            result = self.inverter.read_all_data(
                battery_sampler=self.battery_sampler
            )
            elapsed = time.time() - t0

            if result.get("error"):
                logger.warning("Inverter poll returned error after %.1fs: %s", elapsed, result["error"])
            else:
                logger.info("Inverter poll OK in %.1fs (PV=%dW load=%dW grid=%dW)",
                            elapsed,
                            result.get("pv_total_power", 0),
                            result.get("load_power", 0),
                            result.get("grid_power", 0))

            result["last_updated"] = datetime.now().isoformat()
            with self._lock:
                self._cache = result
            self._save_cache()

            # Record daily grid import for monthly totals
            if "daily_grid_import" in result:
                record_grid_daily_import(result["daily_grid_import"])

            # Track generator runtime
            if inverter_config.has_generator and "generator_power" in result:
                track_generator_runtime(result["generator_power"])

            # Record phase sample for analytics (only for 3-phase)
            if "load_l1" in result and inverter_config.phases == 3:
                record_phase_sample(
                    result.get("load_l1", 0),
                    result.get("load_l2", 0),
                    result.get("load_l3", 0),
                )
        except Exception:
            logger.exception("Error polling inverter data")

    @property
    def data(self):
        with self._lock:
            return dict(self._cache) if self._cache else None

    def _run(self):
        while True:
            self._fetch()
            time.sleep(self.poll_interval)

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()


app = Flask(__name__)

# Configuration - can be overridden with environment variables
INVERTER_IP = os.environ.get("INVERTER_IP", "0.0.0.0")
LOGGER_SERIAL = int(os.environ.get("LOGGER_SERIAL", "0"))
OUTAGE_HISTORY_FILE = os.environ.get("OUTAGE_HISTORY_FILE", "outage_history.json")
PHASE_STATS_FILE = os.environ.get("PHASE_STATS_FILE", "phase_stats.json")
PHASE_HISTORY_FILE = os.environ.get("PHASE_HISTORY_FILE", "phase_history.json")
GRID_DAILY_LOG_FILE = os.environ.get("GRID_DAILY_LOG_FILE", "grid_daily_log.json")
GENERATOR_LOG_FILE = os.environ.get("GENERATOR_LOG_FILE", "generator_log.json")
GENERATOR_FUEL_RATE = float(os.environ.get("GENERATOR_FUEL_RATE", "0"))
GENERATOR_OIL_CHANGE_DATE = os.environ.get("GENERATOR_OIL_CHANGE_DATE", "")


def build_inverter_config(inv):
    """Build InverterConfig from env vars, auto-detecting any missing values."""
    env_phases = os.environ.get("INVERTER_PHASES")
    env_battery = os.environ.get("INVERTER_HAS_BATTERY")
    env_pv = os.environ.get("INVERTER_PV_STRINGS")
    env_generator = os.environ.get("INVERTER_HAS_GENERATOR")

    if env_phases and env_battery and env_pv and env_generator:
        return InverterConfig(
            phases=int(env_phases),
            has_battery=env_battery.lower() in ("true", "1", "yes"),
            pv_strings=int(env_pv),
            has_generator=env_generator.lower() in ("true", "1", "yes"),
        )

    # Auto-detect missing values
    try:
        detected = inv.detect_config()
    except Exception:
        logger.warning("Auto-detect failed, using defaults")
        detected = InverterConfig()

    return InverterConfig(
        phases=int(env_phases) if env_phases else detected.phases,
        has_battery=(env_battery.lower() in ("true", "1", "yes"))
            if env_battery else detected.has_battery,
        pv_strings=int(env_pv) if env_pv else detected.pv_strings,
        has_generator=(env_generator.lower() in ("true", "1", "yes"))
            if env_generator else detected.has_generator,
    )


inverter = DeyeInverter(INVERTER_IP, LOGGER_SERIAL)
inverter_config = build_inverter_config(inverter)
inverter.config = inverter_config

battery_sampler = BatterySampler(inverter, interval=30)
battery_sampler.start()

# Outage schedule provider
OUTAGE_PROVIDER_NAME = os.environ.get("OUTAGE_PROVIDER", "lvivoblenergo")
OUTAGE_GROUP = os.environ.get("OUTAGE_GROUP")
outage_provider = create_outage_provider(
    OUTAGE_PROVIDER_NAME,
    group=OUTAGE_GROUP,
    region_id=os.environ.get("OUTAGE_REGION_ID", "25"),
    dso_id=os.environ.get("OUTAGE_DSO_ID", "902"),
)
if outage_provider is not None:
    outage_poller = OutageSchedulePoller(provider=outage_provider)
    outage_poller.start()
else:
    outage_poller = None
    logger.info("Outage schedule disabled (OUTAGE_PROVIDER=none)")

weather_poller = WeatherPoller()
weather_poller.start()
inverter_poller = InverterPoller(inverter, battery_sampler,
                                cache_file=INVERTER_CACHE_FILE)
inverter_poller.start()

# OTA update system
GITHUB_REPO = os.environ.get("GITHUB_REPO", "ivanursul/deye-dashboard")
UPDATE_CHECK_INTERVAL = int(os.environ.get("UPDATE_CHECK_INTERVAL", "600"))
update_poller = UpdatePoller(repo=GITHUB_REPO, poll_interval=UPDATE_CHECK_INTERVAL)
update_manager = UpdateManager()
update_poller.start()

# Phase data collection
last_sample_time = None
last_history_save = None
phase_accumulator = {"l1": 0, "l2": 0, "l3": 0}


def load_grid_daily_log():
    """Load grid daily import log from file."""
    if os.path.exists(GRID_DAILY_LOG_FILE):
        with open(GRID_DAILY_LOG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_grid_daily_log(log):
    """Save grid daily import log to file."""
    with open(GRID_DAILY_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def record_grid_daily_import(daily_kwh):
    """Record today's daily grid import value, overwriting previous entry."""
    today = datetime.now().strftime("%Y-%m-%d")
    log = load_grid_daily_log()
    log[today] = daily_kwh
    # Keep only last 90 days
    sorted_dates = sorted(log.keys(), reverse=True)
    if len(sorted_dates) > 90:
        for old_date in sorted_dates[90:]:
            del log[old_date]
    save_grid_daily_log(log)


def load_generator_log():
    """Load generator runtime log from file."""
    if os.path.exists(GENERATOR_LOG_FILE):
        with open(GENERATOR_LOG_FILE, "r") as f:
            return json.load(f)
    return {}


def save_generator_log(log):
    """Save generator runtime log to file."""
    with open(GENERATOR_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


# Generator runtime tracking state
generator_last_running = None
generator_session_start = None


def track_generator_runtime(generator_power):
    """Track generator runtime based on power readings."""
    global generator_last_running, generator_session_start

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    running = generator_power > 0

    log = load_generator_log()

    if today not in log:
        log[today] = {"runtime_seconds": 0, "sessions": []}

    if running and not generator_last_running:
        # Transition: off → on — start new session
        generator_session_start = now
        log[today]["sessions"].append({
            "start": now.strftime("%H:%M:%S"),
            "end": None,
        })
    elif not running and generator_last_running:
        # Transition: on → off — close session
        if generator_session_start:
            elapsed = (now - generator_session_start).total_seconds()
            log[today]["runtime_seconds"] += int(elapsed)
            # Close the last open session
            if log[today]["sessions"] and log[today]["sessions"][-1]["end"] is None:
                log[today]["sessions"][-1]["end"] = now.strftime("%H:%M:%S")
        generator_session_start = None

    generator_last_running = running

    # Keep only last 90 days
    sorted_dates = sorted(log.keys(), reverse=True)
    if len(sorted_dates) > 90:
        for old_date in sorted_dates[90:]:
            del log[old_date]

    save_generator_log(log)


def load_outage_history():
    """Load outage history from file."""
    if os.path.exists(OUTAGE_HISTORY_FILE):
        with open(OUTAGE_HISTORY_FILE, "r") as f:
            return json.load(f)
    return []


def save_outage_history(history):
    """Save outage history to file."""
    with open(OUTAGE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_phase_stats():
    """Load phase statistics from file."""
    if os.path.exists(PHASE_STATS_FILE):
        with open(PHASE_STATS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_phase_stats(stats):
    """Save phase statistics to file."""
    with open(PHASE_STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def load_phase_history():
    """Load phase time-series history from file."""
    if os.path.exists(PHASE_HISTORY_FILE):
        with open(PHASE_HISTORY_FILE, "r") as f:
            return json.load(f)
    return {}


def save_phase_history(history):
    """Save phase time-series history to file."""
    with open(PHASE_HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def record_phase_sample(load_l1, load_l2, load_l3):
    """Record a phase power sample and accumulate energy."""
    global last_sample_time, last_history_save, phase_accumulator

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # Load existing stats
    stats = load_phase_stats()

    # Initialize today's entry if needed
    if today not in stats:
        stats[today] = {
            "l1_wh": 0,
            "l2_wh": 0,
            "l3_wh": 0,
            "samples": 0,
            "l1_max": 0,
            "l2_max": 0,
            "l3_max": 0
        }

    # Calculate energy (Wh) from power (W) and time interval
    if last_sample_time:
        interval_hours = (now - last_sample_time).total_seconds() / 3600

        # Only accumulate if interval is reasonable (< 5 minutes)
        if interval_hours < 0.1:
            stats[today]["l1_wh"] += load_l1 * interval_hours
            stats[today]["l2_wh"] += load_l2 * interval_hours
            stats[today]["l3_wh"] += load_l3 * interval_hours

    # Update max values
    stats[today]["l1_max"] = max(stats[today]["l1_max"], load_l1)
    stats[today]["l2_max"] = max(stats[today]["l2_max"], load_l2)
    stats[today]["l3_max"] = max(stats[today]["l3_max"], load_l3)
    stats[today]["samples"] += 1

    last_sample_time = now

    # Keep only last 30 days
    sorted_dates = sorted(stats.keys(), reverse=True)
    if len(sorted_dates) > 30:
        for old_date in sorted_dates[30:]:
            del stats[old_date]

    save_phase_stats(stats)

    # Save to time-series history (every 30 seconds for smooth charts)
    if last_history_save is None or (now - last_history_save).total_seconds() >= 30:
        save_to_phase_history(now, load_l1, load_l2, load_l3)
        last_history_save = now


def save_to_phase_history(timestamp, l1, l2, l3):
    """Save a data point to the time-series history."""
    history = load_phase_history()
    today = timestamp.strftime("%Y-%m-%d")
    time_str = timestamp.strftime("%H:%M:%S")

    if today not in history:
        history[today] = []

    history[today].append({
        "time": time_str,
        "l1": l1,
        "l2": l2,
        "l3": l3
    })

    # Keep only last 7 days of history
    sorted_dates = sorted(history.keys(), reverse=True)
    if len(sorted_dates) > 7:
        for old_date in sorted_dates[7:]:
            del history[old_date]

    save_phase_history(history)


@app.after_request
def add_no_cache_headers(response):
    """Prevent browsers from serving stale cached pages."""
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    """Serve the dashboard page."""
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    """API endpoint to get current inverter data (cached)."""
    data = inverter_poller.data
    if not data:
        return jsonify({"error": "not yet available"}), 503
    config = inverter_config.to_dict()
    config["has_outage_schedule"] = outage_poller is not None
    data["config"] = config
    return jsonify(data)


@app.route("/api/phase-stats")
def get_phase_stats():
    """Get phase statistics."""
    stats = load_phase_stats()

    # Calculate daily totals and format for frontend
    result = []
    for day, data in sorted(stats.items(), reverse=True)[:14]:  # Last 14 days
        total_wh = data["l1_wh"] + data["l2_wh"] + data["l3_wh"]
        result.append({
            "date": day,
            "l1_kwh": round(data["l1_wh"] / 1000, 2),
            "l2_kwh": round(data["l2_wh"] / 1000, 2),
            "l3_kwh": round(data["l3_wh"] / 1000, 2),
            "total_kwh": round(total_wh / 1000, 2),
            "l1_max": data["l1_max"],
            "l2_max": data["l2_max"],
            "l3_max": data["l3_max"],
            "l1_pct": round(data["l1_wh"] / total_wh * 100, 1) if total_wh > 0 else 0,
            "l2_pct": round(data["l2_wh"] / total_wh * 100, 1) if total_wh > 0 else 0,
            "l3_pct": round(data["l3_wh"] / total_wh * 100, 1) if total_wh > 0 else 0,
        })

    return jsonify(result)


@app.route("/api/phase-history")
def get_phase_history():
    """Get phase time-series data for charting."""
    history = load_phase_history()
    date_param = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))

    if date_param in history:
        return jsonify({
            "date": date_param,
            "data": history[date_param],
            "available_dates": sorted(history.keys(), reverse=True)
        })
    else:
        return jsonify({
            "date": date_param,
            "data": [],
            "available_dates": sorted(history.keys(), reverse=True)
        })


@app.route("/api/phase-stats/clear", methods=["POST"])
def clear_phase_stats():
    """Clear phase statistics."""
    save_phase_stats({})
    save_phase_history({})
    return jsonify({"status": "ok"})


@app.route("/api/outage_schedule")
def get_outage_schedule():
    """Get current outage schedule status from the poller."""
    if outage_poller is None:
        return jsonify({"status": "disabled"})
    status = outage_poller.get_outage_status()
    result = {"status": status["status"]}
    if status["status"] == "active":
        result["start_time"] = status["start_time"].isoformat()
        result["end_time"] = status["end_time"].isoformat()
        result["remaining_minutes"] = status["remaining_minutes"]
    elif status["status"] == "upcoming":
        result["upcoming_windows"] = [
            {"start": s.isoformat(), "end": e.isoformat()}
            for s, e in status["upcoming_windows"]
        ]
        if "electricity_start" in status:
            result["electricity_start"] = status["electricity_start"].isoformat()
    return jsonify(result)


@app.route("/api/outages", methods=["GET"])
def get_outages():
    """Get outage history."""
    history = load_outage_history()
    return jsonify(history)


@app.route("/api/outages", methods=["POST"])
def add_outage():
    """Add a new outage event."""
    data = request.json
    history = load_outage_history()

    event = {
        "id": len(history) + 1,
        "type": data.get("type"),  # "start" or "end"
        "timestamp": data.get("timestamp"),
        "voltage": data.get("voltage", 0)
    }

    # If this is an "end" event, calculate duration
    if event["type"] == "end" and history:
        # Find the last "start" event
        for i in range(len(history) - 1, -1, -1):
            if history[i]["type"] == "start" and "duration" not in history[i]:
                start_time = datetime.fromisoformat(history[i]["timestamp"])
                end_time = datetime.fromisoformat(event["timestamp"])
                duration = (end_time - start_time).total_seconds()
                history[i]["duration"] = duration
                history[i]["end_timestamp"] = event["timestamp"]
                break

    history.append(event)

    # Keep only last 100 events
    if len(history) > 100:
        history = history[-100:]

    save_outage_history(history)
    return jsonify({"status": "ok"})


@app.route("/api/outages/clear", methods=["POST"])
def clear_outages():
    """Clear outage history."""
    save_outage_history([])
    return jsonify({"status": "ok"})


@app.route("/api/weather")
def get_weather():
    """Get current weather conditions."""
    data = weather_poller.data
    if not data:
        return jsonify({"error": "not yet available"}), 503
    return jsonify(data)


@app.route("/api/generator")
def get_generator():
    """Get generator status and runtime data."""
    if not inverter_config.has_generator:
        return jsonify({"enabled": False})

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    log = load_generator_log()

    # Current power from inverter poller
    inv_data = inverter_poller.data
    power = inv_data.get("generator_power", 0) if inv_data else 0
    running = power > 0

    # Today's runtime (account for currently-running session)
    today_entry = log.get(today, {"runtime_seconds": 0, "sessions": []})
    today_seconds = today_entry["runtime_seconds"]
    if running and generator_session_start:
        today_seconds += int((now - generator_session_start).total_seconds())
    today_hours = round(today_seconds / 3600, 2)

    # Monthly runtime
    month_prefix = now.strftime("%Y-%m")
    monthly_seconds = 0
    for day_key, day_data in log.items():
        if day_key.startswith(month_prefix):
            monthly_seconds += day_data.get("runtime_seconds", 0)
    if running and generator_session_start:
        monthly_seconds += int((now - generator_session_start).total_seconds())
    monthly_hours = round(monthly_seconds / 3600, 2)

    result = {
        "enabled": True,
        "running": running,
        "power": power,
        "today_runtime_hours": today_hours,
        "today_sessions": today_entry.get("sessions", []),
        "monthly_runtime_hours": monthly_hours,
    }

    # Fuel estimates
    if GENERATOR_FUEL_RATE > 0:
        result["fuel_rate"] = GENERATOR_FUEL_RATE
        result["fuel_today_liters"] = round(today_hours * GENERATOR_FUEL_RATE, 2)
        result["fuel_monthly_liters"] = round(monthly_hours * GENERATOR_FUEL_RATE, 2)
    else:
        result["fuel_rate"] = None
        result["fuel_today_liters"] = None
        result["fuel_monthly_liters"] = None

    # Oil change tracking
    if GENERATOR_OIL_CHANGE_DATE:
        result["oil_change_date"] = GENERATOR_OIL_CHANGE_DATE
        try:
            oil_date = datetime.strptime(GENERATOR_OIL_CHANGE_DATE, "%Y-%m-%d")
            # Sum all runtime hours since oil change date
            oil_hours = 0
            for day_key, day_data in log.items():
                if day_key >= GENERATOR_OIL_CHANGE_DATE:
                    oil_hours += day_data.get("runtime_seconds", 0) / 3600
            if running and generator_session_start:
                oil_hours += (now - generator_session_start).total_seconds() / 3600
            result["oil_change_hours_since"] = round(oil_hours, 1)
        except ValueError:
            result["oil_change_hours_since"] = None
    else:
        result["oil_change_date"] = None
        result["oil_change_hours_since"] = None

    return jsonify(result)


@app.route("/api/update/status")
def get_update_status():
    """Get current version, update availability, and manager state."""
    data = update_poller.data or {}
    mgr_status = update_manager.status
    return jsonify({
        "current_version": data.get("current_version", get_current_version()),
        "latest_tag": data.get("latest_tag"),
        "update_available": data.get("update_available", False),
        "available_tags": data.get("available_tags", []),
        "last_checked": data.get("last_checked"),
        "manager_state": mgr_status["state"],
        "manager_message": mgr_status["message"],
        "manager_error": mgr_status["error"],
        "is_git_repo": update_manager.is_git_repo(),
    })


@app.route("/api/update/check", methods=["POST"])
def check_for_updates():
    """Force an immediate check for updates."""
    update_poller.force_check()
    return jsonify({"status": "ok"})


@app.route("/api/update/apply", methods=["POST"])
def apply_update():
    """Apply an update to the specified tag."""
    data = request.json or {}
    tag = data.get("tag")
    if not tag:
        return jsonify({"status": "error", "error": "Missing 'tag' parameter"}), 400
    ok = update_manager.update_to_tag(tag)
    if not ok:
        return jsonify({"status": "error", "error": "Update already in progress"}), 409
    return jsonify({"status": "ok", "message": f"Update to {tag} started"})


@app.route("/api/update/rollback", methods=["POST"])
def rollback_update():
    """Rollback to the specified tag (same mechanism as update)."""
    data = request.json or {}
    tag = data.get("tag")
    if not tag:
        return jsonify({"status": "error", "error": "Missing 'tag' parameter"}), 400
    ok = update_manager.update_to_tag(tag)
    if not ok:
        return jsonify({"status": "error", "error": "Rollback already in progress"}), 409
    return jsonify({"status": "ok", "message": f"Rollback to {tag} started"})


@app.route("/api/update/preflight")
def update_preflight():
    """Run preflight checks before update."""
    ok, issues = update_manager.preflight_check()
    return jsonify({"ok": ok, "issues": issues})


def start_telegram_bot():
    """Start the Telegram bot in a background thread if configured."""
    if os.environ.get("TELEGRAM_ENABLED", "true").lower() == "false":
        logging.info("Telegram bot disabled via TELEGRAM_ENABLED=false")
        return None

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    is_public = os.environ.get("TELEGRAM_PUBLIC", "false").lower() in ("true", "1", "yes")

    if not token:
        logging.info("TELEGRAM_BOT_TOKEN not set, Telegram bot disabled")
        return None

    user_ids = set()
    for uid in allowed.split(","):
        uid = uid.strip()
        if uid.isdigit():
            user_ids.add(int(uid))

    state_file = os.environ.get("BOT_STATE_FILE", "bot_state.json")
    bot = TelegramBot(
        token=token, allowed_users=user_ids, inverter=inverter,
        battery_sampler=battery_sampler, outage_poller=outage_poller,
        state_file=state_file,
        grid_daily_log_file=GRID_DAILY_LOG_FILE,
        weather_poller=weather_poller,
        is_public=is_public,
    )
    bot.start(inverter_interval=120)
    logging.info("Telegram bot started with %d allowed users (public=%s)", len(user_ids), is_public)
    return bot


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # Log startup configuration
    logger.info("=== Deye Dashboard starting ===")
    logger.info("Version: %s", get_current_version())
    logger.info("INVERTER_IP=%s  LOGGER_SERIAL=%s", INVERTER_IP, LOGGER_SERIAL)
    logger.info("Inverter config: %s", inverter_config.to_dict())
    logger.info("Generator: has_generator=%s fuel_rate=%s oil_change=%s",
                inverter_config.has_generator, GENERATOR_FUEL_RATE, GENERATOR_OIL_CHANGE_DATE or "N/A")
    logger.info("OUTAGE_PROVIDER=%s  OUTAGE_GROUP=%s", OUTAGE_PROVIDER_NAME, OUTAGE_GROUP)
    logger.info("WEATHER coords: lat=%s lon=%s", WEATHER_LATITUDE, WEATHER_LONGITUDE)
    telegram_enabled = os.environ.get("TELEGRAM_ENABLED", "true").lower() != "false"
    telegram_token_set = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
    logger.info("TELEGRAM: enabled=%s token_set=%s", telegram_enabled, telegram_token_set)

    # Flask debug reloader spawns two processes. Only start the bot once:
    # - If WERKZEUG_RUN_MAIN is set, we're in the reloader child — start bot
    # - If it's not set and use_reloader is False, start bot (no reloader)
    # - Otherwise skip (we're the reloader parent, child will start it)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_telegram_bot()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
