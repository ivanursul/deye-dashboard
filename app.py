"""Deye Dashboard - Simple web dashboard for Deye solar inverters."""
from flask import Flask, render_template, jsonify, request
from inverter import DeyeInverter, BatterySampler, InverterConfig
from telegram_bot import TelegramBot
from outage_providers import OutageSchedulePoller, create_outage_provider
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
            result = self.inverter.read_all_data(
                battery_sampler=self.battery_sampler
            )
            result["last_updated"] = datetime.now().isoformat()
            with self._lock:
                self._cache = result
            self._save_cache()

            # Record daily grid import for monthly totals
            if "daily_grid_import" in result:
                record_grid_daily_import(result["daily_grid_import"])

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


def build_inverter_config(inv):
    """Build InverterConfig from env vars, auto-detecting any missing values."""
    env_phases = os.environ.get("INVERTER_PHASES")
    env_battery = os.environ.get("INVERTER_HAS_BATTERY")
    env_pv = os.environ.get("INVERTER_PV_STRINGS")

    if env_phases and env_battery and env_pv:
        return InverterConfig(
            phases=int(env_phases),
            has_battery=env_battery.lower() in ("true", "1", "yes"),
            pv_strings=int(env_pv),
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
    )


inverter = DeyeInverter(INVERTER_IP, LOGGER_SERIAL)
inverter_config = build_inverter_config(inverter)
inverter.config = inverter_config

battery_sampler = BatterySampler(inverter)
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


def start_telegram_bot():
    """Start the Telegram bot in a background thread if configured."""
    if os.environ.get("TELEGRAM_ENABLED", "true").lower() == "false":
        logging.info("Telegram bot disabled via TELEGRAM_ENABLED=false")
        return None

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed = os.environ.get("TELEGRAM_ALLOWED_USERS", "")

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
    )
    bot.start(inverter_interval=120)
    logging.info("Telegram bot started with %d allowed users", len(user_ids))
    return bot


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Flask debug reloader spawns two processes. Only start the bot once:
    # - If WERKZEUG_RUN_MAIN is set, we're in the reloader child — start bot
    # - If it's not set and use_reloader is False, start bot (no reloader)
    # - Otherwise skip (we're the reloader parent, child will start it)
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_telegram_bot()
    app.run(host="0.0.0.0", port=8080, debug=True)
