"""Config flow: controller login (reused from the built-in Ruckus integration) + clients."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import RuckusClientApi
from .const import CONF_CLIENTS, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, RUCKUS_DOMAIN


async def _client_options(hass, data: dict) -> list[SelectOptionDict]:
    api = RuckusClientApi(data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD])
    try:
        clients = await api.client_counters()
    finally:
        await api.close()
    from .sensor import _known_name

    opts = []
    for mac, c in sorted(clients.items(), key=lambda kv: (_known_name(hass, kv[0]) or kv[1]["hostname"] or "~", kv[0])):
        name = _known_name(hass, mac) or c["hostname"] or "unknown"
        opts.append(SelectOptionDict(value=mac, label=f"{name} - {mac} ({c['ap_name']})"))
    return opts


def _clients_schema(options: list, selected: list, interval: int) -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_CLIENTS, default=selected): SelectSelector(
            SelectSelectorConfig(options=options, multiple=True, custom_value=True)
        ),
        vol.Optional(CONF_SCAN_INTERVAL, default=interval): NumberSelector(
            NumberSelectorConfig(min=10, max=300, step=5, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
        ),
    })


class RuckusClientThroughputConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        # Pre-fill from Home Assistant's own Ruckus integration if it is set up.
        existing = next(iter(self.hass.config_entries.async_entries(RUCKUS_DOMAIN)), None)
        defaults = dict(existing.data) if existing else {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input.get(CONF_PASSWORD) or defaults.get(CONF_PASSWORD, ""),
            }
            await self.async_set_unique_id(data[CONF_HOST])
            self._abort_if_unique_id_configured()
            try:
                self._options = await _client_options(self.hass, data)
            except Exception:  # noqa: BLE001
                errors["base"] = "cannot_connect"
            else:
                self._data = data
                return await self.async_step_clients()
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Optional(CONF_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }),
            description_placeholders={"reuse": "yes" if existing else "no"},
        )

    async def async_step_clients(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"Ruckus clients ({self._data[CONF_HOST]})",
                data=self._data,
                options={
                    CONF_CLIENTS: [m.lower() for m in user_input.get(CONF_CLIENTS, [])],
                    CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                },
            )
        return self.async_show_form(
            step_id="clients", data_schema=_clients_schema(self._options, [], DEFAULT_SCAN_INTERVAL)
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RuckusClientThroughputOptionsFlow()


class RuckusClientThroughputOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(data={
                CONF_CLIENTS: [m.lower() for m in user_input.get(CONF_CLIENTS, [])],
                CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            })
        selected = list(self.config_entry.options.get(CONF_CLIENTS, []))
        try:
            options = await _client_options(self.hass, dict(self.config_entry.data))
        except Exception:  # noqa: BLE001
            options = []
        known = {o["value"] for o in options}
        options += [SelectOptionDict(value=m, label=f"{m} (not connected now)") for m in selected if m not in known]
        return self.async_show_form(
            step_id="init",
            data_schema=_clients_schema(
                options, selected, self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
