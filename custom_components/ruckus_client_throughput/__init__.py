"""Ruckus Client Throughput: live Wi-Fi throughput sensors for chosen clients.

Home Assistant's built-in Ruckus integration only tracks presence. This adds a
data-rate sensor (kbit/s) per selected client, worked out from the access
points' byte counters - so it also sees local traffic (AirPlay, DLNA, phone ->
TV) that never passes the router.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RuckusClientApi
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


# The controller refreshes each client's byte counters only about once a minute
# (per AP). A rate is therefore worked out between two *changes* of the counters,
# not between two polls, and held until the next change. If the counters have
# not moved for this long the client really is idle and the rate drops to 0.
IDLE_AFTER_SECONDS = 150


class ThroughputCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Polls the controller and turns byte counters into rates."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: RuckusClientApi) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=interval)
        )
        self.api = api
        # mac -> {"ts": time of last counter change, "rx", "tx", "up", "down"}
        self._track: dict[str, dict] = {}

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            counters = await self.api.client_counters()
        except Exception as err:
            raise UpdateFailed(f"Ruckus controller not reachable: {err}") from err
        now = time.monotonic()
        result: dict[str, dict] = {}
        for mac, c in counters.items():
            t = self._track.get(mac)
            if t is None or c["rx"] < t["rx"] or c["tx"] < t["tx"]:
                # First sight, or counters reset (client re-associated): new baseline.
                self._track[mac] = {"ts": now, "rx": c["rx"], "tx": c["tx"], "up": None, "down": None}
            elif c["rx"] != t["rx"] or c["tx"] != t["tx"]:
                dt = max(now - t["ts"], 1.0)
                t.update(
                    up=round((c["rx"] - t["rx"]) * 8 / 1000 / dt, 1),
                    down=round((c["tx"] - t["tx"]) * 8 / 1000 / dt, 1),
                    ts=now, rx=c["rx"], tx=c["tx"],
                )
            elif now - t["ts"] > IDLE_AFTER_SECONDS:
                t.update(up=0.0, down=0.0)
            t = self._track[mac]
            result[mac] = {**c, "upload_kbps": t["up"], "download_kbps": t["down"]}
        for mac in list(self._track):
            if mac not in counters:
                self._track.pop(mac, None)
        return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    api = RuckusClientApi(entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = ThroughputCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.api.close()
    return ok
