"""Ruckus Client Throughput: live Wi-Fi throughput sensors for chosen clients.

Home Assistant's built-in Ruckus integration only tracks presence. This adds a
data-rate sensor (kbit/s) per selected client, worked out from the access
points' byte counters - so it also sees local traffic (AirPlay, DLNA, phone ->
TV) that never passes the router. It also tracks how much data each client has
used today.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

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
    """Polls the controller and turns byte counters into rates and daily totals."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: RuckusClientApi) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=timedelta(seconds=interval)
        )
        self.api = api
        # mac -> tracking dict. Keys:
        #   ts, rx, tx  -> counter values at the last *change* (for the rate)
        #   up, down    -> last computed rates (kbit/s), None until first change
        #   poll_rx, poll_tx -> counter values at the last *poll* (for daily totals)
        #   day, day_bytes   -> local date and bytes used so far that day
        self._track: dict[str, dict] = {}

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            counters = await self.api.client_counters()
        except Exception as err:  # noqa: BLE001 - surfaced as UpdateFailed
            raise UpdateFailed(f"Ruckus controller not reachable: {err}") from err

        now = time.monotonic()
        today = dt_util.now().date().isoformat()
        result: dict[str, dict] = {}

        for mac, c in counters.items():
            t = self._track.get(mac)
            if t is None:
                # First sight: baseline everything, no rate yet.
                t = self._track[mac] = {
                    "ts": now, "rx": c["rx"], "tx": c["tx"], "up": None, "down": None,
                    "poll_rx": c["rx"], "poll_tx": c["tx"], "day": today, "day_bytes": 0,
                }
            else:
                # --- daily total: sum positive deltas, handle a counter reset ---
                if t["day"] != today:
                    t["day"] = today
                    t["day_bytes"] = 0
                d_rx = c["rx"] - t["poll_rx"]
                d_tx = c["tx"] - t["poll_tx"]
                # A re-associated client resets the AP counters to ~0; count the
                # current value as the traffic since the reset rather than a negative.
                t["day_bytes"] += (c["rx"] if d_rx < 0 else d_rx) + (c["tx"] if d_tx < 0 else d_tx)
                t["poll_rx"], t["poll_tx"] = c["rx"], c["tx"]

                # --- rate: computed between counter *changes* ---
                if c["rx"] < t["rx"] or c["tx"] < t["tx"]:
                    t.update(ts=now, rx=c["rx"], tx=c["tx"], up=None, down=None)  # reset
                elif c["rx"] != t["rx"] or c["tx"] != t["tx"]:
                    dt = max(now - t["ts"], 1.0)
                    t.update(
                        up=round((c["rx"] - t["rx"]) * 8 / 1000 / dt, 1),
                        down=round((c["tx"] - t["tx"]) * 8 / 1000 / dt, 1),
                        ts=now, rx=c["rx"], tx=c["tx"],
                    )
                elif now - t["ts"] > IDLE_AFTER_SECONDS:
                    t.update(up=0.0, down=0.0)

            result[mac] = {
                **c,
                "upload_kbps": t["up"],
                "download_kbps": t["down"],
                "counter_age": round(now - t["ts"]),   # seconds since the counter last moved
                "day_mb": round(t["day_bytes"] / 1_000_000, 1),
            }

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
