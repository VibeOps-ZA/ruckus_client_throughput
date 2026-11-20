"""The coordinator (one poll = rates + daily totals), the entry helpers and migration, and the sensors' ids."""
import asyncio
import datetime as dt
import json
import pathlib

import pytest

from custom_components.ruckus_client_throughput import api, async_migrate_entry, entry_data
from custom_components.ruckus_client_throughput import sensor as sensor_mod
from custom_components.ruckus_client_throughput.const import (
    CONF_CLIENTS,
    CONF_GATEWAY_KEY,
    CONF_GATEWAY_URL,
    CONF_SCAN_INTERVAL,
    CONF_SOURCE,
    DOMAIN,
    SOURCE_AUTO,
    SOURCE_DIRECT,
    SOURCE_GATEWAY,
)
from custom_components.ruckus_client_throughput.coordinator import ThroughputCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

MAC = "aa:bb:cc:00:00:01"
OTHER = "aa:bb:cc:00:00:02"
ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "ruckus_client_throughput"
UTC = dt.timezone.utc


class Entry:
    def __init__(self, data=None, options=None, version=2, title="Ruckus"):
        self.data, self.options, self.version, self.title = data or {}, options or {}, version, title


class FakeSource:
    def __init__(self, *batches):
        self.batches, self.macs_asked, self.closed = list(batches), [], False

    async def fetch(self, macs=None):
        self.macs_asked.append(macs)
        out = self.batches.pop(0) if len(self.batches) > 1 else self.batches[0]
        if isinstance(out, Exception):
            raise out
        return out

    async def close(self):
        self.closed = True


def batch(ts, **by_mac):
    return api.CounterBatch({m: {"rx": v[0], "tx": v[1], "hostname": "tv", "ap_name": "AP", "ssid": "Home"}
                             for m, v in by_mac.items()} if by_mac else {}, ts, SOURCE_GATEWAY)


def batch_of(ts, mapping):
    return api.CounterBatch({m: {"rx": v[0], "tx": v[1], "hostname": "tv", "ap_name": "AP", "ssid": "Home"}
                             for m, v in mapping.items()}, ts, SOURCE_GATEWAY)


def make(source, interval=60, macs=(MAC,), days=None):
    entry = Entry(options={CONF_SCAN_INTERVAL: interval})
    return ThroughputCoordinator(None, entry, source, list(macs), days if days is not None else {})


def poll(coord):
    asyncio.run(coord.async_refresh())
    return coord.data


# ------------------------------------------------------------------------------------------------- polling
def test_poll_asks_for_the_chosen_clients_only_and_returns_rows_for_them(hass_clock):
    hass_clock(dt.datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    src = FakeSource(batch_of(1000.0, {MAC: (0, 0), OTHER: (5, 5)}))
    coord = make(src)
    data = poll(coord)
    assert src.macs_asked == [[MAC]] and set(data) == {MAC}      # one bulk call; the other client is ignored


def test_poll_computes_rate_and_daily_total_from_the_sources_own_timestamps(hass_clock):
    hass_clock(dt.datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    src = FakeSource(batch_of(1000.0, {MAC: (0, 0)}), batch_of(1060.0, {MAC: (750_000, 1_500_000)}))
    coord = make(src)
    poll(coord)
    row = poll(coord)[MAC]
    assert row["upload_kbps"] == 100.0 and row["download_kbps"] == 200.0 and row["day_mb"] == 2.2


def test_errors_map_to_home_assistant_exceptions():
    with pytest.raises(UpdateFailed, match="down"):
        poll(make(FakeSource(api.SourceError("down"))))
    with pytest.raises(UpdateFailed, match="could not read"):
        poll(make(FakeSource(RuntimeError("boom"))))
    with pytest.raises(ConfigEntryAuthFailed):
        poll(make(FakeSource(api.SourceAuthError("no", "gateway"))))


def test_slow_polling_never_reads_as_idle():
    assert make(FakeSource(batch(1.0)), interval=60)._tracker.idle_after == 150
    assert make(FakeSource(batch(1.0)), interval=300)._tracker.idle_after == 750


# ------------------------------------------------------------------------------------------------- restart / midnight
def test_daily_total_survives_a_restart_and_a_reload(hass_clock):
    hass_clock(dt.datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    store: dict = {}
    first = make(FakeSource(batch_of(1000.0, {MAC: (0, 0)}), batch_of(1060.0, {MAC: (4_000_000, 0)})), days=store)
    poll(first)
    assert poll(first)[MAC]["day_mb"] == 4.0
    reloaded = make(FakeSource(batch_of(1120.0, {MAC: (4_000_000, 0)})), days=store)    # options changed -> reload
    assert poll(reloaded)[MAC]["day_mb"] == 4.0

    restarted = make(FakeSource(batch_of(1200.0, {MAC: (50, 50)})))                     # a fresh start, empty store
    poll(restarted)
    restarted.restore_day(MAC, "2026-11-20", 4_200_000)                                  # what the sensor remembered
    assert restarted.data[MAC]["day_mb"] == 4.2
    assert restarted.day_total(MAC) == ("2026-11-20", 4.2)


def test_a_client_that_sleeps_keeps_showing_todays_total(hass_clock):
    hass_clock(dt.datetime(2026, 11, 20, 12, 0, tzinfo=UTC))
    coord = make(FakeSource(batch_of(1000.0, {MAC: (0, 0)}), batch_of(1060.0, {MAC: (2_000_000, 0)}),
                            batch_of(1120.0, {})))
    poll(coord)
    poll(coord)
    assert MAC not in poll(coord)                                # off the Wi-Fi: no row ...
    assert coord.day_total(MAC) == ("2026-11-20", 2.0)           # ... but the total is still there


def test_midnight_resets_at_local_midnight_and_tells_the_entities(hass_clock):
    hass_clock(dt.datetime(2026, 11, 20, 23, 59, tzinfo=UTC))
    coord = make(FakeSource(batch_of(1000.0, {MAC: (0, 0)}), batch_of(1060.0, {MAC: (3_000_000, 0)}),
                            batch_of(1120.0, {MAC: (3_500_000, 0)})))
    poll(coord)
    assert poll(coord)[MAC]["day_mb"] == 3.0
    updates = coord.updated
    hass_clock(dt.datetime(2026, 11, 21, 0, 0, 1, tzinfo=UTC))
    coord.midnight()
    assert coord.data[MAC]["day_mb"] == 0.0 and coord.data[MAC]["day"] == "2026-11-21"
    assert coord.updated == updates + 1                          # entities were told at once
    assert coord.day_total(MAC) == ("2026-11-21", 0.0)
    assert poll(coord)[MAC]["day_mb"] == 0.5                     # the traffic after midnight counts for the new day


# ------------------------------------------------------------------------------------------------- entry + migration
def test_source_mode_and_usable_sources():
    gw = {CONF_GATEWAY_URL: "https://x/ruckus", CONF_GATEWAY_KEY: "k"}
    direct = {"host": "h", "username": "u", "password": "p"}
    assert entry_data.source_mode(Entry()) == SOURCE_AUTO
    assert entry_data.source_mode(Entry(options={CONF_SOURCE: "nonsense"})) == SOURCE_AUTO
    assert entry_data.usable_sources(Entry({**gw, **direct})) == [SOURCE_GATEWAY, SOURCE_DIRECT]
    assert entry_data.usable_sources(Entry({**gw, **direct}, {CONF_SOURCE: SOURCE_GATEWAY})) == [SOURCE_GATEWAY]
    assert entry_data.usable_sources(Entry({**gw, **direct}, {CONF_SOURCE: SOURCE_DIRECT})) == [SOURCE_DIRECT]
    assert entry_data.usable_sources(Entry(direct)) == [SOURCE_DIRECT]           # an old entry keeps working
    assert entry_data.usable_sources(Entry(gw, {CONF_SOURCE: SOURCE_DIRECT})) == []


class FakeHass:
    class config_entries:   # noqa: N801 - mimics hass.config_entries
        @staticmethod
        def async_update_entry(entry, data=None, options=None, version=None):
            entry.data, entry.options = data, options
            entry.version = version


def test_migration_keeps_an_old_entry_working_and_changes_nothing_else():
    old = Entry({"host": "172.22.20.5", "username": "admin", "password": "pw"},
                {CONF_CLIENTS: [MAC, OTHER], CONF_SCAN_INTERVAL: 60}, version=1)
    assert asyncio.run(async_migrate_entry(FakeHass(), old)) is True
    assert old.version == 2
    assert old.data == {"host": "172.22.20.5", "username": "admin", "password": "pw"}       # login untouched
    assert old.options == {CONF_CLIENTS: [MAC, OTHER], CONF_SCAN_INTERVAL: 60, CONF_SOURCE: SOURCE_AUTO}
    assert entry_data.usable_sources(old) == [SOURCE_DIRECT]       # no gateway yet: still its own login, as before


def test_migration_refuses_an_entry_from_the_future():
    assert asyncio.run(async_migrate_entry(FakeHass(), Entry(version=99))) is False


# ------------------------------------------------------------------------------------------------- ids unchanged
class Coord:
    data = {MAC: {"upload_kbps": 1.0, "download_kbps": 2.0, "day_mb": 3.0, "day": "2026-11-20",
                  "counter_age": 5, "ap_name": "AP", "ssid": "Home"}}

    def day_total(self, mac):
        return None

    def restore_day(self, mac, day, nbytes):
        self.restored = (mac, day, nbytes)


def test_unique_ids_names_and_devices_are_unchanged():
    thr = sensor_mod.ClientThroughputSensor(Coord(), MAC.upper(), "Study TV")
    day = sensor_mod.ClientDailyDataSensor(Coord(), MAC.upper(), "Study TV")
    assert thr._attr_unique_id == f"{MAC}_throughput" and day._attr_unique_id == f"{MAC}_data_today"
    assert thr._attr_name == "Wi-Fi throughput" and day._attr_name == "Wi-Fi data today"
    for s in (thr, day):
        info = s._attr_device_info
        assert info["identifiers"] == {(DOMAIN, MAC)} and info["name"] == "Study TV Ruckus"
    assert thr.native_value == 3.0 and day.native_value == 3.0
    assert day.extra_state_attributes == {"date": "2026-11-20"}


def test_daily_sensor_restores_the_remembered_total():
    class Last:
        native_value = 12.5

    class State:
        attributes = {"date": "2026-11-20"}
        last_updated = dt.datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
    coord = Coord()
    day = sensor_mod.ClientDailyDataSensor(coord, MAC, None)
    day.last_sensor, day.last_state = Last(), State()
    asyncio.run(day.async_added_to_hass())
    assert coord.restored == (MAC, "2026-11-20", 12_500_000)


def test_daily_sensor_restore_uses_the_state_date_for_a_pre_0_3_state_and_ignores_unknown():
    class Last:
        native_value = 2.0

    class OldState:
        attributes = {}
        last_updated = dt.datetime(2026, 11, 19, 22, 0, tzinfo=UTC)
    coord = Coord()
    day = sensor_mod.ClientDailyDataSensor(coord, MAC, None)
    day.last_sensor, day.last_state = Last(), OldState()
    asyncio.run(day.async_added_to_hass())
    assert coord.restored == (MAC, "2026-11-19", 2_000_000)

    class Unknown:
        native_value = "unknown"
    other = Coord()
    day2 = sensor_mod.ClientDailyDataSensor(other, MAC, None)
    day2.last_sensor, day2.last_state = Unknown(), OldState()
    asyncio.run(day2.async_added_to_hass())
    assert not hasattr(other, "restored")


# ------------------------------------------------------------------------------------------------- packaging
def test_strings_and_translation_are_identical_and_cover_every_step():
    strings = json.loads((COMPONENT / "strings.json").read_text())
    assert strings == json.loads((COMPONENT / "translations" / "en.json").read_text())
    assert {"user", "gateway", "direct", "clients", "reauth_confirm"} <= set(strings["config"]["step"])
    assert {"init", "gateway", "direct"} <= set(strings["options"]["step"])
    assert {"cannot_connect", "invalid_auth", "host_required"} <= set(strings["config"]["error"])


def test_manifest():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == DOMAIN and manifest["version"] == "0.3.0"
    assert manifest["requirements"] == ["aioruckus>=0.42,<0.50"]          # bounded (the private call is wrapped)
