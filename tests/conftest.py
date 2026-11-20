"""Test setup: run the tests without Home Assistant or a Ruckus controller.

The maths (tracker.py, backoff.py), the counter sources (api.py) and the entry helpers (entry_data.py) are plain
Python; the coordinator, sensors and config flow import Home Assistant. When Home Assistant is not installed, tiny
stand-ins are registered here before the integration is imported - just enough for the imports and the few
behaviours the tests need. Nothing opens a network connection.

Run from the repository root with:  python3 -m pytest
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
COMPONENT = ROOT / "custom_components" / "ruckus_client_throughput"
PACKAGE = "custom_components.ruckus_client_throughput"


def _installed(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    parent, _, child = name.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], child, mod)
    return mod


class _Names(type):
    """Attribute access returns the lower-case name (Platform.SENSOR == "sensor")."""

    def __getattr__(cls, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return name.lower()


class _Enum(metaclass=_Names):
    pass


class _Anything:
    """Accepts any arguments (selectors, DeviceInfo ...) and keeps them."""

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs

    def __getitem__(self, key):
        return self.kwargs[key]


class _UpdateFailed(Exception):
    pass


class _ConfigEntryAuthFailed(Exception):
    pass


class _Coordinator:
    def __init__(self, hass, logger, config_entry=None, name="", update_interval=None):
        self.hass, self.config_entry, self.name, self.update_interval = hass, config_entry, name, update_interval
        self.data = None
        self.updated = 0

    def __class_getitem__(cls, item):
        return cls

    def async_set_updated_data(self, data):
        self.data = data
        self.updated += 1

    async def async_refresh(self):
        self.data = await self._async_update_data()


class _CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator


class _RestoreSensor:
    last_sensor = None
    last_state = None

    async def async_added_to_hass(self):
        return None

    async def async_get_last_sensor_data(self):
        return self.last_sensor

    async def async_get_last_state(self):
        return self.last_state


# The clock the stand-in dt_util.now() uses; tests move it with `clock.now = ...`.
class Clock:
    now = dt.datetime(2026, 11, 20, 12, 0, 0, tzinfo=dt.timezone.utc)


clock = Clock()


def _install_standins() -> None:
    _module("homeassistant")
    _module("homeassistant.helpers")
    _module("homeassistant.components")
    _module("homeassistant.util")
    _module("homeassistant.config_entries", ConfigEntry=_Anything,
            ConfigFlow=type("ConfigFlow", (), {"__init_subclass__": classmethod(lambda cls, **kw: None)}),
            OptionsFlow=type("OptionsFlow", (), {}))
    _module("homeassistant.const", CONF_HOST="host", CONF_PASSWORD="password", CONF_USERNAME="username",
            Platform=_Enum, UnitOfDataRate=_Enum, UnitOfInformation=_Enum)
    _module("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
    _module("homeassistant.exceptions", ConfigEntryAuthFailed=_ConfigEntryAuthFailed)
    _module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
    _module("homeassistant.helpers.event", async_track_time_change=lambda *a, **k: (lambda: None))
    _module("homeassistant.helpers.selector", NumberSelector=_Anything, NumberSelectorConfig=_Anything,
            NumberSelectorMode=_Enum, SelectOptionDict=dict, SelectSelector=_Anything,
            SelectSelectorConfig=_Anything, TextSelector=_Anything, TextSelectorConfig=_Anything,
            TextSelectorType=_Enum)
    _module("homeassistant.helpers.device_registry", DeviceInfo=dict, CONNECTION_NETWORK_MAC="mac",
            async_get=lambda hass: None)
    _module("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_Coordinator,
            UpdateFailed=_UpdateFailed, CoordinatorEntity=_CoordinatorEntity)
    _module("homeassistant.components.sensor", SensorDeviceClass=_Enum, SensorStateClass=_Enum,
            SensorEntity=type("SensorEntity", (), {}), RestoreSensor=_RestoreSensor)
    _module("homeassistant.util.dt", now=lambda: clock.now, as_local=lambda d: d)


if not _installed("homeassistant"):
    _install_standins()
if not _installed("voluptuous"):
    _module("voluptuous", Schema=_Anything, Optional=lambda k, **kw: k, Required=lambda k, **kw: k)

# The real package folder under the name the integration is loaded by (custom_components is a plain folder).
_module("custom_components")
sys.modules["custom_components"].__path__ = [str(ROOT / "custom_components")]


@pytest.fixture()
def hass_clock():
    """Move the stand-in clock: hass_clock(datetime)."""
    original = clock.now

    def set_now(value):
        clock.now = value
    yield set_now
    clock.now = original
