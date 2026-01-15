"""Deye Dashboard - Simple web dashboard for Deye solar inverters."""
from flask import Flask, render_template, jsonify, request
from inverter import DeyeInverter
from datetime import datetime, date
import os
import json
import threading
import time

app = Flask(__name__)

# Configuration - can be overridden with environment variables
INVERTER_IP = os.environ.get("INVERTER_IP", "192.168.1.157")
LOGGER_SERIAL = int(os.environ.get("LOGGER_SERIAL", "1234567890"))
OUTAGE_HISTORY_FILE = os.environ.get("OUTAGE_HISTORY_FILE", "outage_history.json")
PHASE_STATS_FILE = os.environ.get("PHASE_STATS_FILE", "phase_stats.json")
PHASE_HISTORY_FILE = os.environ.get("PHASE_HISTORY_FILE", "phase_history.json")

inverter = DeyeInverter(INVERTER_IP, LOGGER_SERIAL)

# Phase data collection
last_sample_time = None
last_history_save = None
phase_accumulator = {"l1": 0, "l2": 0, "l3": 0}


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


@app.route("/")
def index():
    """Serve the dashboard page."""
    return render_template("index.html")


@app.route("/api/data")
def get_data():
    """API endpoint to get current inverter data."""
    try:
        data = inverter.read_all_data()

        # Record phase sample for analytics
        if "load_l1" in data:
            record_phase_sample(
                data.get("load_l1", 0),
                data.get("load_l2", 0),
                data.get("load_l3", 0)
            )

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
