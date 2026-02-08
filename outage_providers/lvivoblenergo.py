"""Outage schedule provider for Lvivoblenergo (LOE)."""
import os
import re
import logging
from html.parser import HTMLParser

import requests

from outage_providers.base import OutageProvider

logger = logging.getLogger(__name__)

SCHEDULE_API_URL = "https://api.loe.lviv.ua/api/menus?page=1&type=photo-grafic"
DEFAULT_GROUP = "4.1"


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = []
        self._current = []

    def handle_data(self, data):
        self._current.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self._current:
            self.lines.append("".join(self._current).strip())
            self._current = []


def parse_group_windows(html, group):
    """Parse outage time windows for a specific group from rawHtml.

    Returns list of (start_hour, start_min, end_hour, end_min) tuples.
    """
    parser = _TextExtractor()
    parser.feed(html)

    group_pattern = re.compile(
        rf"Група\s+{re.escape(group)}\.\s+(.+)", re.IGNORECASE
    )
    time_pattern = re.compile(r"з\s+(\d{1,2}):(\d{2})\s+до\s+(\d{1,2}):(\d{2})")

    for line in parser.lines:
        match = group_pattern.match(line)
        if match:
            rest = match.group(1)
            windows = []
            for m in time_pattern.finditer(rest):
                windows.append((
                    int(m.group(1)), int(m.group(2)),
                    int(m.group(3)), int(m.group(4)),
                ))
            return windows
    return []


class LvivoblenergoProvider(OutageProvider):
    """Outage schedule provider for Lvivoblenergo (LOE)."""

    def __init__(self, group=None):
        self.group = group or os.environ.get("OUTAGE_GROUP", DEFAULT_GROUP)
        self.api_url = SCHEDULE_API_URL

    def fetch_windows(self):
        """Fetch today's outage windows from the Lvivoblenergo API."""
        resp = requests.get(self.api_url, timeout=15)
        if not resp.ok:
            logger.warning("Outage API returned %s", resp.status_code)
            return []

        data = resp.json()
        members = data.get("hydra:member", [])
        if not members:
            return []

        for item in members[0].get("menuItems", []):
            if item.get("name") == "Today":
                html = item.get("rawHtml", "")
                return parse_group_windows(html, self.group)

        return []
