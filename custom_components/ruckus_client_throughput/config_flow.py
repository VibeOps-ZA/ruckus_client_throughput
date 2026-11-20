"""Config flow: where the counters come from (gateway and/or controller login) + which clients to measure."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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

from .api import AutoSource, DirectSource, GatewaySource, SourceAuthError
from .const import (
    CONF_CLIENTS,
    CONF_GATEWAY_KEY,
    CONF_GATEWAY_URL,
    CONF_SCAN_INTERVAL,
    CONF_SOURCE,
    CONFIG_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    RUCKUS_DOMAIN,
    SOURCE_AUTO,
    SOURCE_DIRECT,
    SOURCE_GATEWAY,
)
from .entry_data import source_mode

_SOURCE_LABELS = {
    SOURCE_AUTO: "Automatic: gateway first, own login only if the gateway stops answering",
    SOURCE_GATEWAY: "Gateway only: never log in to the controller",
    SOURCE_DIRECT: "Own login only: log in to the controller directly (the old way)",
}


def _password_field() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _source_selector() -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(
        options=[SelectOptionDict(value=k, label=v) for k, v in _SOURCE_LABELS.items()], multiple=False))


async def _read_clients(hass, gateway: tuple[str, str] | None, direct: tuple[str, str, str] | None) -> dict[str, dict]:
    """Read every connected client once, from the gateway if given, else with a login (both closed again).
    Raises SourceAuthError (refused credentials) or another exception (cannot connect)."""
    source = AutoSource(
        GatewaySource(async_get_clientsession(hass), *gateway) if gateway else None,
        DirectSource(*direct) if direct and not gateway else None,
        fails_before_fallback=1,
    )
    try:
        return (await source.fetch(None)).counters
    finally:
        await source.close()


async def _client_options(hass, clients: dict[str, dict]) -> list[SelectOptionDict]:
    from .sensor import _known_name

    opts = []
    for mac, c in sorted(clients.items(), key=lambda kv: (_known_name(hass, kv[0]) or kv[1]["hostname"] or "~", kv[0])):
        name = _known_name(hass, mac) or c["hostname"] or "unknown"
        opts.append(SelectOptionDict(value=mac, label=f"{name} - {mac} ({c['ap_name']})"))
    return opts


def _clients_schema(options: list, selected: list, interval: int, source: str | None = None) -> vol.Schema:
    schema: dict = {
        vol.Optional(CONF_CLIENTS, default=selected): SelectSelector(
            SelectSelectorConfig(options=options, multiple=True, custom_value=True)
        ),
        vol.Optional(CONF_SCAN_INTERVAL, default=interval): NumberSelector(
            NumberSelectorConfig(min=10, max=300, step=5, mode=NumberSelectorMode.BOX, unit_of_measurement="s")
        ),
    }
    if source is not None:
        schema[vol.Optional(CONF_SOURCE, default=source)] = _source_selector()
    return vol.Schema(schema)


def _error_for(err: Exception) -> str:
    return "invalid_auth" if isinstance(err, SourceAuthError) else "cannot_connect"


class RuckusClientThroughputConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = CONFIG_VERSION

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._source = SOURCE_AUTO
        self._clients: dict[str, dict] = {}

    # --- 1. which source -------------------------------------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._source = user_input[CONF_SOURCE]
            return await (self.async_step_direct() if self._source == SOURCE_DIRECT else self.async_step_gateway())
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_SOURCE, default=SOURCE_AUTO): _source_selector()}),
        )

    # --- 2. the gateway --------------------------------------------------------------------------------------
    async def async_step_gateway(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_GATEWAY_URL].strip().rstrip("/")
            key = user_input[CONF_GATEWAY_KEY].strip()
            try:
                self._clients = await _read_clients(self.hass, (url, key), None)
            except Exception as err:  # noqa: BLE001
                errors["base"] = _error_for(err)
            else:
                self._data.update({CONF_GATEWAY_URL: url, CONF_GATEWAY_KEY: key})
                return await (self.async_step_direct() if self._source == SOURCE_AUTO else self.async_step_clients())
        return self.async_show_form(
            step_id="gateway",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_GATEWAY_URL, default=(user_input or {}).get(CONF_GATEWAY_URL, "")): str,
                vol.Required(CONF_GATEWAY_KEY): _password_field(),
            }),
        )

    # --- 3. the controller login (required for "direct", optional fallback for "auto") ------------------------
    async def async_step_direct(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        # Pre-fill address and user from Home Assistant's own Ruckus integration if it is set up.
        existing = next(iter(self.hass.config_entries.async_entries(RUCKUS_DOMAIN)), None)
        defaults = dict(existing.data) if existing else {}
        optional = self._source == SOURCE_AUTO
        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            if not host and optional:
                return await self.async_step_clients()           # no fallback login: gateway only
            data = {
                CONF_HOST: host,
                CONF_USERNAME: user_input.get(CONF_USERNAME, ""),
                CONF_PASSWORD: user_input.get(CONF_PASSWORD) or defaults.get(CONF_PASSWORD, ""),
            }
            if not host:
                errors["base"] = "host_required"
            else:
                try:
                    seen = await _read_clients(self.hass, None, (host, data[CONF_USERNAME], data[CONF_PASSWORD]))
                    self._clients = self._clients or seen        # the gateway's list (if any) came first
                except Exception as err:  # noqa: BLE001
                    errors["base"] = _error_for(err)
                else:
                    self._data.update(data)
                    return await self.async_step_clients()
        host_field = vol.Optional if optional else vol.Required
        return self.async_show_form(
            step_id="direct",
            errors=errors,
            data_schema=vol.Schema({
                host_field(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                host_field(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Optional(CONF_PASSWORD): _password_field(),
            }),
            description_placeholders={"reuse": "yes" if existing else "no"},
        )

    # --- 4. which clients ------------------------------------------------------------------------------------
    async def async_step_clients(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            await self.async_set_unique_id(self._data.get(CONF_HOST) or self._data[CONF_GATEWAY_URL])
            self._abort_if_unique_id_configured()
            where = self._data.get(CONF_HOST) or self._data[CONF_GATEWAY_URL]
            return self.async_create_entry(
                title=f"Ruckus clients ({where})",
                data=self._data,
                options={
                    CONF_CLIENTS: [m.lower() for m in user_input.get(CONF_CLIENTS, [])],
                    CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                    CONF_SOURCE: self._source,
                },
            )
        options = await _client_options(self.hass, self._clients)
        return self.async_show_form(step_id="clients", data_schema=_clients_schema(options, [], DEFAULT_SCAN_INTERVAL))

    # --- re-authentication: the gateway key or the controller password was refused -----------------------------
    async def async_step_reauth(self, entry_data: dict[str, Any]):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        has_gw, has_direct = bool(entry.data.get(CONF_GATEWAY_KEY)), bool(entry.data.get(CONF_PASSWORD))
        if user_input is not None:
            updates = {k: v for k, v in user_input.items() if v}
            data = {**entry.data, **updates}
            try:
                await _read_clients(
                    self.hass,
                    (data[CONF_GATEWAY_URL], data[CONF_GATEWAY_KEY]) if has_gw else None,
                    (data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD]) if has_direct and not has_gw else None,
                )
            except Exception as err:  # noqa: BLE001
                errors["base"] = _error_for(err)
            else:
                return self.async_update_reload_and_abort(entry, data_updates=updates)
        fields: dict = {}
        if has_gw:
            fields[vol.Optional(CONF_GATEWAY_KEY)] = _password_field()
        if has_direct:
            fields[vol.Optional(CONF_PASSWORD)] = _password_field()
        return self.async_show_form(step_id="reauth_confirm", errors=errors, data_schema=vol.Schema(fields))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RuckusClientThroughputOptionsFlow()


class RuckusClientThroughputOptionsFlow(OptionsFlow):
    """Configure: clients, interval, source; then the gateway and/or controller login the source needs."""

    def __init__(self) -> None:
        self._opts: dict[str, Any] = {}
        self._data: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None:
            self._opts = {
                CONF_CLIENTS: [m.lower() for m in user_input.get(CONF_CLIENTS, [])],
                CONF_SCAN_INTERVAL: int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                CONF_SOURCE: user_input.get(CONF_SOURCE, source_mode(entry)),
            }
            self._data = dict(entry.data)
            return await self._next("init")
        selected = list(entry.options.get(CONF_CLIENTS, []))
        try:
            data = entry.data
            clients = await _read_clients(
                self.hass,
                (data[CONF_GATEWAY_URL], data[CONF_GATEWAY_KEY]) if data.get(CONF_GATEWAY_KEY) else None,
                (data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD]) if data.get(CONF_PASSWORD) else None,
            )
            options = await _client_options(self.hass, clients)
        except Exception:  # noqa: BLE001
            options = []
        known = {o["value"] for o in options}
        options += [SelectOptionDict(value=m, label=f"{m} (not connected now)") for m in selected if m not in known]
        return self.async_show_form(
            step_id="init",
            data_schema=_clients_schema(
                options, selected, entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL), source_mode(entry)
            ),
        )

    async def _next(self, after: str):
        mode = self._opts[CONF_SOURCE]
        if after == "init" and mode != SOURCE_DIRECT:
            return await self.async_step_gateway()
        if after in ("init", "gateway") and mode != SOURCE_GATEWAY:
            return await self.async_step_direct()
        return self._finish()

    def _finish(self):
        self.hass.config_entries.async_update_entry(self.config_entry, data=self._data)
        return self.async_create_entry(data=self._opts)

    async def async_step_gateway(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_GATEWAY_URL].strip().rstrip("/")
            key = (user_input.get(CONF_GATEWAY_KEY) or "").strip() or self._data.get(CONF_GATEWAY_KEY, "")
            try:
                await _read_clients(self.hass, (url, key), None)
            except Exception as err:  # noqa: BLE001
                errors["base"] = _error_for(err)
            else:
                self._data.update({CONF_GATEWAY_URL: url, CONF_GATEWAY_KEY: key})
                return await self._next("gateway")
        return self.async_show_form(
            step_id="gateway",
            errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_GATEWAY_URL, default=self._data.get(CONF_GATEWAY_URL, "")): str,
                vol.Optional(CONF_GATEWAY_KEY): _password_field(),    # empty = keep the stored key
            }),
        )

    async def async_step_direct(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        optional = self._opts[CONF_SOURCE] == SOURCE_AUTO
        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            if not host and optional:
                for k in (CONF_HOST, CONF_USERNAME, CONF_PASSWORD):      # no fallback login any more
                    self._data.pop(k, None)
                return self._finish()
            password = user_input.get(CONF_PASSWORD) or self._data.get(CONF_PASSWORD, "")
            if not host:
                errors["base"] = "host_required"
            else:
                try:
                    await _read_clients(self.hass, None, (host, user_input.get(CONF_USERNAME, ""), password))
                except Exception as err:  # noqa: BLE001
                    errors["base"] = _error_for(err)
                else:
                    self._data.update({CONF_HOST: host, CONF_USERNAME: user_input.get(CONF_USERNAME, ""),
                                       CONF_PASSWORD: password})
                    return self._finish()
        host_field = vol.Optional if optional else vol.Required
        return self.async_show_form(
            step_id="direct",
            errors=errors,
            data_schema=vol.Schema({
                host_field(CONF_HOST, default=self._data.get(CONF_HOST, "")): str,
                host_field(CONF_USERNAME, default=self._data.get(CONF_USERNAME, "")): str,
                vol.Optional(CONF_PASSWORD): _password_field(),           # empty = keep the stored password
            }),
        )
