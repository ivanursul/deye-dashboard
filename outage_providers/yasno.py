"""Outage schedule provider for YASNO (DTEK regions)."""
import os
import logging

import requests

from outage_providers.base import OutageProvider

logger = logging.getLogger(__name__)


class YasnoProvider(OutageProvider):
    """Outage schedule provider for YASNO (DTEK regions)."""

    API_URL_TEMPLATE = (
        "https://app.yasno.ua/api/blackout-service/public/shutdowns"
        "/regions/{region_id}/dsos/{dso_id}/planned-outages"
    )

    def __init__(self, group=None, region_id=25, dso_id=902):
        self.group = group or os.environ.get("OUTAGE_GROUP", "2.1")
        self.region_id = region_id
        self.dso_id = dso_id

    def fetch_windows(self):
        """Fetch today's outage windows from the YASNO API."""
        url = self.API_URL_TEMPLATE.format(
            region_id=self.region_id, dso_id=self.dso_id
        )
        resp = requests.get(url, timeout=15)
        if not resp.ok:
            logger.warning("YASNO API returned %s", resp.status_code)
            return []

        data = resp.json()
        group_data = data.get(self.group, {})
        today = group_data.get("today", {})
        slots = today.get("slots", [])

        windows = []
        for slot in slots:
            if slot.get("type") != "Definite":
                continue
            sh, sm = divmod(slot["start"], 60)
            eh, em = divmod(slot["end"], 60)
            windows.append((sh, sm, eh, em))
        return windows
