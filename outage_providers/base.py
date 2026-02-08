"""Base classes and factory for outage schedule providers."""
import time
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

BATTERY_CAPACITY_KWH = 16.0


class OutageProvider:
    """Base class for outage schedule providers."""

    def fetch_windows(self):
        """Return list of (start_h, start_m, end_h, end_m) for today.

        Override in subclass.
        """
        raise NotImplementedError


def create_outage_provider(provider_name, **kwargs):
    """Create an outage provider by name.

    Args:
        provider_name: "lvivoblenergo", "yasno", or "none" to disable.
        **kwargs: Provider-specific keyword arguments.

    Returns:
        An OutageProvider instance, or None if provider_name is "none".
    """
    from outage_providers.lvivoblenergo import LvivoblenergoProvider
    from outage_providers.yasno import YasnoProvider

    if provider_name == "none":
        return None
    if provider_name == "lvivoblenergo":
        return LvivoblenergoProvider(group=kwargs.get("group"))
    if provider_name == "yasno":
        return YasnoProvider(
            group=kwargs.get("group"),
            region_id=int(kwargs.get("region_id", 25)),
            dso_id=int(kwargs.get("dso_id", 902)),
        )
    raise ValueError(f"Unknown outage provider: {provider_name}")


class OutageSchedulePoller:
    """Polls an outage provider and stores today's outage schedule."""

    def __init__(self, provider=None, group=None, poll_interval=60):
        # Backward compat: if no provider given, create Lvivoblenergo
        if provider is None:
            from outage_providers.lvivoblenergo import LvivoblenergoProvider
            provider = LvivoblenergoProvider(group=group)
        self.provider = provider
        self.poll_interval = poll_interval
        self._windows = []  # list of (start_hour, start_min, end_hour, end_min)
        self._last_updated = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    def _fetch_schedule(self):
        """Fetch and parse the schedule from the provider."""
        try:
            windows = self.provider.fetch_windows()
            with self._lock:
                self._windows = windows
                self._last_updated = datetime.now()
            logger.info("Outage schedule updated: %s", windows)
        except Exception:
            logger.exception("Error fetching outage schedule")

    def get_outage_status(self):
        """Return current outage status.

        Returns a dict with:
          - status: "active", "upcoming", "clear", or "unknown"
          - end_time: datetime (if active)
          - remaining_minutes: int (if active)
          - upcoming_windows: list of (start_dt, end_dt) (if upcoming)
        """
        with self._lock:
            windows = list(self._windows)
            last_updated = self._last_updated

        if last_updated is None:
            return {"status": "unknown"}

        now = datetime.now()
        today = now.date()

        active_start = None
        active_end = None
        upcoming = []

        for sh, sm, eh, em in windows:
            start_dt = datetime.combine(today, datetime.min.time()).replace(
                hour=sh, minute=sm
            )
            # Handle 24:00 as next day 00:00
            if eh == 24:
                end_dt = datetime.combine(
                    today + timedelta(days=1), datetime.min.time()
                )
            else:
                end_dt = datetime.combine(today, datetime.min.time()).replace(
                    hour=eh, minute=em
                )

            if start_dt <= now < end_dt:
                active_start = start_dt
                active_end = end_dt
            elif now < start_dt:
                upcoming.append((start_dt, end_dt))

        if active_end:
            remaining = (active_end - now).total_seconds() / 60
            return {
                "status": "active",
                "start_time": active_start,
                "end_time": active_end,
                "remaining_minutes": int(remaining),
            }
        elif upcoming:
            # Find when the current electricity period started
            # (end of the most recent past outage window, or midnight)
            electricity_start = datetime.combine(today, datetime.min.time())
            for sh, sm, eh, em in windows:
                if eh == 24:
                    edt = datetime.combine(
                        today + timedelta(days=1), datetime.min.time()
                    )
                else:
                    edt = datetime.combine(
                        today, datetime.min.time()
                    ).replace(hour=eh, minute=em)
                if edt <= now:
                    electricity_start = edt
            return {
                "status": "upcoming",
                "upcoming_windows": upcoming,
                "electricity_start": electricity_start,
            }
        else:
            return {"status": "clear"}

    def _run(self):
        while self._running:
            self._fetch_schedule()
            time.sleep(self.poll_interval)

    def start(self):
        """Start polling in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
