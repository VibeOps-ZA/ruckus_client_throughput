"""The coordinator: one poll = one read of the counters of all chosen clients, turned into rates and daily totals."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SourceAuthError, SourceError
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .tracker import IDLE_AFTER_SECONDS, ClientTracker

_LOGGER = logging.getLogger(__name__)


class ThroughputCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """data = {mac: row}; a client that is not on the Wi-Fi right now has no row."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, source, macs: list[str], days: dict) -> None:
        interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=interval))
        self.source = source
        self.macs = [m.lower() for m in macs]
        # Idle = counters unchanged for 2.5 polls (at least the classic 150 s), so a slower poll never reads as idle.
        # `days` lives in hass.data, so the daily totals also survive a reload of the integration (options change).
        self._tracker = ClientTracker(idle_after=max(IDLE_AFTER_SECONDS, 2.5 * interval), days=days)

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            batch = await self.source.fetch(self.macs)
        except SourceAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err          # HA asks the owner for the new key / password
        except SourceError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001 - anything else is also just "no data this time"
            raise UpdateFailed(f"could not read the counters: {err}") from err
        today = dt_util.now().date().isoformat()
        wanted = {m: c for m, c in batch.counters.items() if m in self.macs}
        return self._tracker.update(wanted, batch.fetched_at, today)

    # --- used by the daily-data sensor -------------------------------------------------------------------------
    def restore_day(self, mac: str, day: str, nbytes: int) -> None:
        """Give back the total the sensor remembered from before a restart (see tracker.restore_day)."""
        self._tracker.restore_day(mac.lower(), day, nbytes)

    def day_total(self, mac: str) -> tuple[str, float] | None:
        """(day, MB) for a client, also while it is off the Wi-Fi (a TV in standby keeps today's total)."""
        today = dt_util.now().date().isoformat()
        d = self._tracker.days.get(mac.lower())
        if d is None or d["day"] != today:
            return None
        return d["day"], self._tracker.day_mb(mac.lower(), today)

    @callback
    def midnight(self, _now=None) -> None:
        """Local midnight: every client's daily total starts again at 0, without waiting for the next poll."""
        self._tracker.roll_day(dt_util.now().date().isoformat())
        if self.data is not None:
            self.async_set_updated_data(self.data)
