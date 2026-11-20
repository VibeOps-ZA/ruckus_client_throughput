"""Ruckus Client Throughput: live Wi-Fi throughput sensors for chosen clients.

Home Assistant's built-in Ruckus integration only tracks presence. This adds a
data-rate sensor (kbit/s) per selected client, worked out from the access
points' byte counters - so it also sees local traffic (AirPlay, DLNA, phone ->
TV) that never passes the router. It also tracks how much data each client has
used today.

Where the counters come from (setting "source"): the Ruckus gateway (preferred:
it holds the one admin session to the controller), a login of our own (fallback),
or "auto" = gateway first, direct login only if the gateway stops answering.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import AutoSource, DirectSource, GatewaySource
from .const import (
    CONF_CLIENTS,
    CONF_GATEWAY_KEY,
    CONF_GATEWAY_URL,
    CONFIG_VERSION,
    DOMAIN,
    SOURCE_DIRECT,
    SOURCE_GATEWAY,
)
from .coordinator import ThroughputCoordinator
from .entry_data import migrate_v1_to_v2, source_mode, usable_sources

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]


def build_source(hass: HomeAssistant, entry: ConfigEntry):
    """The counter source for this entry, or None when nothing usable is set up."""
    usable = usable_sources(entry)
    gateway = direct = None
    if SOURCE_GATEWAY in usable:
        gateway = GatewaySource(
            async_get_clientsession(hass), entry.data[CONF_GATEWAY_URL], entry.data[CONF_GATEWAY_KEY]
        )
    if SOURCE_DIRECT in usable:
        direct = DirectSource(entry.data[CONF_HOST], entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    if gateway is None and direct is None:
        return None
    return AutoSource(gateway, direct)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """0.1 / 0.2 -> 0.3: add the source option. Entity ids, unique ids and devices are not touched."""
    if entry.version > CONFIG_VERSION:
        return False                                  # created by a newer version: do not touch
    if entry.version == 1:
        data, options = migrate_v1_to_v2(entry.data, entry.options)
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=2)
        _LOGGER.info("Ruckus Client Throughput: entry %s upgraded; it keeps using its own controller login until a "
                     "gateway URL and key are added under Configure", entry.title)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    source = build_source(hass, entry)
    if source is None:
        _LOGGER.error("No usable counter source (mode %s): add a gateway URL + key or a controller login under "
                      "Configure", source_mode(entry))
        return False
    macs = [m.lower() for m in entry.options.get(CONF_CLIENTS, [])]
    # Daily totals live in hass.data, so a reload (changing the options) does not lose them.
    days = hass.data.setdefault(DOMAIN, {}).setdefault("days", {})
    coordinator = ThroughputCoordinator(hass, entry, source, macs, days)
    await coordinator.async_config_entry_first_refresh()      # raises ConfigEntryAuthFailed -> re-authentication
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Local midnight: the daily totals start at 0 at once, not at the next poll.
    entry.async_on_unload(async_track_time_change(hass, coordinator.midnight, hour=0, minute=0, second=0))
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.source.close()
    return ok
