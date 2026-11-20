"""Reading a config entry (plain Python; the entry only needs `.data` and `.options`) and migrating old ones."""
from __future__ import annotations

from collections.abc import Mapping

from .const import (
    CONF_GATEWAY_KEY,
    CONF_GATEWAY_URL,
    CONF_SOURCE,
    SOURCE_AUTO,
    SOURCE_DIRECT,
    SOURCE_GATEWAY,
    SOURCES,
)

HOST, USERNAME, PASSWORD = "host", "username", "password"   # same strings as homeassistant.const.CONF_*


def has_gateway(data: Mapping) -> bool:
    return bool(data.get(CONF_GATEWAY_URL) and data.get(CONF_GATEWAY_KEY))


def has_direct(data: Mapping) -> bool:
    return bool(data.get(HOST) and data.get(USERNAME) and data.get(PASSWORD))


def source_mode(entry) -> str:
    """auto / gateway / direct: the option wins, then the data, default auto."""
    mode = entry.options.get(CONF_SOURCE) or entry.data.get(CONF_SOURCE) or SOURCE_AUTO
    return mode if mode in SOURCES else SOURCE_AUTO


def usable_sources(entry) -> list[str]:
    """Which sources the entry can actually use, in the order they are tried."""
    mode, data = source_mode(entry), entry.data
    out = []
    if mode in (SOURCE_AUTO, SOURCE_GATEWAY) and has_gateway(data):
        out.append(SOURCE_GATEWAY)
    if mode in (SOURCE_AUTO, SOURCE_DIRECT) and has_direct(data):
        out.append(SOURCE_DIRECT)
    return out


def migrate_v1_to_v2(data: Mapping, options: Mapping) -> tuple[dict, dict]:
    """0.1 / 0.2 entries only have a direct login. They keep working unchanged: mode 'auto' with no gateway set up
    yet means 'direct login'; the gateway is added later under Configure (it needs a key only the owner has)."""
    new_data = dict(data)
    new_options = dict(options)
    new_options.setdefault(CONF_SOURCE, SOURCE_AUTO)
    return new_data, new_options
