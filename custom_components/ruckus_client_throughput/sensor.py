"""Per-client sensors: live Wi-Fi throughput (kbit/s) and data used today (MB)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfDataRate, UnitOfInformation
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CLIENTS, DOMAIN


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data
    macs = [m.lower() for m in entry.options.get(CONF_CLIENTS, [])]
    entities = []
    for mac in macs:
        name = _known_name(hass, mac)
        entities.append(ClientThroughputSensor(coordinator, mac, name))
        entities.append(ClientDailyDataSensor(coordinator, mac, name))
    async_add_entities(entities)


def _known_name(hass, mac: str) -> str | None:
    """Friendly name another integration already uses for this MAC (e.g. 'Study TV').

    Devices that are only named after the MAC (e.g. presence trackers for clients
    without a hostname) are skipped, and devices that belong to a real integration
    (they have identifiers) win over bare tracker devices.
    """
    reg = dr.async_get(hass)
    conn = {(dr.CONNECTION_NETWORK_MAC, mac)}
    getter = getattr(reg, "async_get_devices", None)  # HA 2026.x
    devices = getter(connections=conn) if getter else [
        d for d in reg.devices.values() if d.connections & conn  # older HA
    ]
    bare = mac.replace(":", "").lower()
    best: tuple[int, str] | None = None
    for dev in devices:
        if (DOMAIN, mac) in dev.identifiers:
            continue
        name = dev.name_by_user or dev.name
        if not name or "".join(ch for ch in name.lower() if ch.isalnum()) == bare:
            continue
        rank = 0 if dev.identifiers else 1
        if best is None or rank < best[0]:
            best = (rank, name)
    return best[1] if best else None


class _ClientEntity(CoordinatorEntity, SensorEntity):
    """Base: one device per client, carrying the client's MAC as a connection."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, mac: str, known_name: str | None) -> None:
        super().__init__(coordinator)
        self._mac = mac.lower()
        label = known_name or self._mac
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            connections={(dr.CONNECTION_NETWORK_MAC, self._mac)},
            name=f"{label} Ruckus",
            manufacturer="Ruckus client",
        )

    @property
    def _data(self) -> dict | None:
        return (self.coordinator.data or {}).get(self._mac)


class ClientThroughputSensor(_ClientEntity):
    """Total Wi-Fi traffic of one client (download + upload)."""

    _attr_name = "Wi-Fi throughput"
    _attr_device_class = SensorDeviceClass.DATA_RATE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfDataRate.KILOBITS_PER_SECOND
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:wifi-arrow-up-down"

    def __init__(self, coordinator, mac: str, known_name: str | None) -> None:
        super().__init__(coordinator, mac, known_name)
        self._attr_unique_id = f"{self._mac}_throughput"

    @property
    def native_value(self):
        data = self._data
        if data is None:
            return 0  # not connected to Wi-Fi right now
        if data["download_kbps"] is None:
            return None  # first sample after start/reconnect
        return round(data["download_kbps"] + data["upload_kbps"], 1)

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data or {}
        return {
            "mac": self._mac,
            "connected": bool(data),
            "download_kbps": data.get("download_kbps"),
            "upload_kbps": data.get("upload_kbps"),
            "access_point": data.get("ap_name"),
            "ssid": data.get("ssid"),
            # How long ago (seconds) the AP counters last moved. The APs refresh
            # roughly once a minute, so a reading up to ~60s old is normal; a much
            # larger value means the client is idle or the counters are stale.
            "counter_age_seconds": data.get("counter_age"),
        }


class ClientDailyDataSensor(_ClientEntity):
    """Data used by one client so far today (resets at local midnight)."""

    _attr_name = "Wi-Fi data today"
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:wifi-arrow-up-down"

    def __init__(self, coordinator, mac: str, known_name: str | None) -> None:
        super().__init__(coordinator, mac, known_name)
        self._attr_unique_id = f"{self._mac}_data_today"

    @property
    def native_value(self):
        data = self._data
        return None if data is None else data.get("day_mb")
