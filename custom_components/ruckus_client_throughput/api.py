"""Where the per-client byte counters come from.

Three sources, all with the same method `await source.fetch(macs) -> CounterBatch`:

* GatewaySource - asks the Ruckus gateway (HTTP front door, read-only). The gateway holds the one admin session to
  the controller, caches, rate-limits and retries; this side only sends one GET per poll for all chosen clients.
* DirectSource  - logs in to the controller itself with aioruckus (the behaviour of 0.1 / 0.2). It now has a
  request timeout, never logs in twice in one poll, and after a failure waits with exponential back-off + jitter, so
  a broken session can never cause a login storm.
* AutoSource    - gateway first; after a few failed polls in a row it falls back to the direct login (if one is
  set up) and goes back to the gateway as soon as that answers again.

Counters: "rx" = bytes received by the AP from the client (upload), "tx" = sent to the client (download).
"""
from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .backoff import Backoff
from .const import (
    GATEWAY_FAILS_BEFORE_FALLBACK,
    LOGIN_BACKOFF_JITTER,
    LOGIN_BACKOFF_MAX,
    LOGIN_BACKOFF_MIN,
    MAX_DATA_AGE,
    REQUEST_TIMEOUT,
    SOURCE_DIRECT,
    SOURCE_GATEWAY,
)

_LOGGER = logging.getLogger(__name__)

CLIENT_STATS_REQUEST = (
    "<ajax-request action='getstat' comp='stamgr' enable-gzip='0'>"
    "<client LEVEL='2' /></ajax-request>"
)


class SourceError(Exception):
    """The counters could not be read this time (the next poll tries again)."""


class SourceAuthError(SourceError):
    """The credentials were refused: retrying will not help until they are changed (re-authentication)."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind            # "gateway" (the key) or "direct" (the controller password)


@dataclass
class CounterBatch:
    counters: dict[str, dict]       # {mac: {rx, tx, hostname, ap_name, ssid}}
    fetched_at: float               # epoch seconds: when the controller was asked (the counters' own time)
    source: str                     # SOURCE_GATEWAY or SOURCE_DIRECT
    extra: dict = field(default_factory=dict)


def norm_mac(mac: str) -> str:
    return (mac or "").strip().lower().replace("-", ":")


# ------------------------------------------------------------------------------------------------- gateway
def parse_gateway(payload: dict, now: float | None = None) -> CounterBatch:
    """The answer of the gateway's `client-counters` command -> CounterBatch."""
    now = time.time() if now is None else now
    try:
        clients = payload["clients"]
        fetched_at = float(payload.get("fetched_at") or now)
        counters = {
            norm_mac(mac): {
                "rx": int(c["rx_bytes"]),
                "tx": int(c["tx_bytes"]),
                "hostname": c.get("hostname") or "",
                "ap_name": c.get("ap") or "",
                "ssid": c.get("ssid") or "",
            }
            for mac, c in clients.items()
        }
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise SourceError(f"unexpected answer from the gateway ({err!r})") from err
    age = now - fetched_at
    if age > MAX_DATA_AGE:
        raise SourceError(f"the gateway's counters are {round(age)} s old (limit {MAX_DATA_AGE} s): not using them")
    return CounterBatch(counters, fetched_at, SOURCE_GATEWAY)


class GatewaySource:
    name = SOURCE_GATEWAY

    def __init__(self, session, url: str, key: str, timeout: float = REQUEST_TIMEOUT) -> None:
        self._session, self._url, self._key, self._timeout = session, url.rstrip("/"), key, timeout

    async def fetch(self, macs: list[str] | None = None) -> CounterBatch:
        import aiohttp   # imported here: Home Assistant always has it, and tests of the maths do not need it

        params = {"macs": ",".join(norm_mac(m) for m in macs)} if macs else None
        try:
            async with self._session.get(
                f"{self._url}/client-counters",
                params=params,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                if resp.status == 401:
                    raise SourceAuthError("the gateway refused the key (401)", "gateway")
                if resp.status == 403:
                    raise SourceError("the gateway does not accept this Home Assistant address (403)")
                if resp.status == 429:
                    retry = resp.headers.get("Retry-After", "?")
                    raise SourceError(f"the gateway is rate limiting us (429, retry after {retry} s)")
                if resp.status >= 400:
                    raise SourceError(f"the gateway answered HTTP {resp.status}")
                payload = await resp.json(content_type=None)
        except SourceError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise SourceError(f"gateway not reachable: {err!r}") from err
        return parse_gateway(payload)

    async def close(self) -> None:        # the HTTP session belongs to Home Assistant: nothing to close
        return None


# ------------------------------------------------------------------------------------------------- direct
def parse_direct(raw: str) -> dict[str, dict]:
    """The controller's 'getstat stamgr client LEVEL=2' XML -> {mac: {rx, tx, hostname, ap_name, ssid}}."""
    root = ET.fromstring(raw)
    out: dict[str, dict] = {}
    for el in root.iter("client"):
        mac = norm_mac(el.get("mac") or "")
        if not mac:
            continue
        try:
            rx = int(el.get("total-rx-bytes", "0"))
            tx = int(el.get("total-tx-bytes", "0"))
        except ValueError:
            continue
        out[mac] = {
            "rx": rx,
            "tx": tx,
            "hostname": el.get("hostname") or "",
            "ap_name": el.get("ap-name") or "",
            "ssid": el.get("ssid") or "",
        }
    return out


class DirectSource:
    """One logged-in aioruckus session, kept open. A failure drops it and the next login waits (back-off)."""

    name = SOURCE_DIRECT

    def __init__(self, host: str, username: str, password: str, timeout: float = REQUEST_TIMEOUT,
                 backoff: Backoff | None = None, session_factory=None) -> None:
        self._args = (host, username, password)
        self._timeout = timeout
        self._session = None
        self._factory = session_factory           # tests hand in a fake; None = aioruckus
        self.backoff = backoff or Backoff(LOGIN_BACKOFF_MIN, LOGIN_BACKOFF_MAX, LOGIN_BACKOFF_JITTER)

    async def _login(self):
        wait = self.backoff.wait_left()
        if wait > 0:
            raise SourceError(f"waiting {round(wait)} s before the next login to the controller (back-off)")
        try:
            if self._factory is not None:
                session = self._factory(*self._args)
            else:
                from aioruckus import AjaxSession
                session = AjaxSession.async_create(*self._args)
            async with asyncio.timeout(self._timeout):
                await session.login()
        except Exception as err:  # noqa: BLE001 - every login failure is handled the same way
            await self._drop()
            if _is_auth_error(err):
                # A refused password is not fixed by trying again (and repeated tries can lock the account).
                self.backoff.failed()
                raise SourceAuthError("the controller refused the login", "direct") from err
            delay = self.backoff.failed()
            raise SourceError(f"controller login failed ({err!r}); next try in {round(delay)} s") from err
        self._session = session
        return session

    async def _drop(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("closing the controller session failed", exc_info=True)

    async def fetch(self, macs: list[str] | None = None) -> CounterBatch:
        session = self._session or await self._login()
        t0 = time.time()
        try:
            async with asyncio.timeout(self._timeout):
                api = session.api
                request = getattr(api, "_cmdstat_noparse", None)    # private in aioruckus: check it is still there
                if request is None:
                    raise SourceError("this aioruckus version has no _cmdstat_noparse: update the integration")
                raw = await request(CLIENT_STATS_REQUEST)
        except SourceError:
            raise
        except Exception as err:  # noqa: BLE001 - connection trouble: drop the session, log in again later
            await self._drop()
            delay = self.backoff.failed()
            raise SourceError(f"controller request failed ({err!r}); next login in {round(delay)} s") from err
        try:
            counters = await asyncio.to_thread(parse_direct, raw)    # XML parsing off the event loop
        except ET.ParseError as err:                                 # a bad answer does not mean a bad session
            raise SourceError(f"the controller's answer could not be read ({err})") from err
        self.backoff.succeeded()
        if macs:
            wanted = {norm_mac(m) for m in macs}
            counters = {m: c for m, c in counters.items() if m in wanted}
        return CounterBatch(counters, t0, SOURCE_DIRECT)

    async def close(self) -> None:
        await self._drop()


def _is_auth_error(err: BaseException) -> bool:
    try:
        from aioruckus.exceptions import AuthenticationError
    except ImportError:
        return type(err).__name__ == "AuthenticationError"
    return isinstance(err, AuthenticationError)


# ------------------------------------------------------------------------------------------------- auto
class AutoSource:
    """Gateway first; the direct login only as a fallback (and only if one is set up)."""

    name = "auto"

    def __init__(self, gateway: GatewaySource | None, direct: DirectSource | None,
                 fails_before_fallback: int = GATEWAY_FAILS_BEFORE_FALLBACK) -> None:
        if gateway is None and direct is None:
            raise ValueError("no source configured")
        self.gateway, self.direct = gateway, direct
        self.fails_before_fallback = fails_before_fallback
        self.gateway_failures = 0
        self.active = SOURCE_GATEWAY if gateway else SOURCE_DIRECT

    async def fetch(self, macs: list[str] | None = None) -> CounterBatch:
        if self.gateway is None:
            self.active = SOURCE_DIRECT
            return await self.direct.fetch(macs)
        try:
            batch = await self.gateway.fetch(macs)
        except SourceAuthError:
            raise                                   # a wrong key needs the owner, not a fallback
        except SourceError as err:
            self.gateway_failures += 1
            if self.direct is None or self.gateway_failures < self.fails_before_fallback:
                raise
            _LOGGER.warning("gateway failed %s times in a row (%s): using the direct login for now",
                            self.gateway_failures, err)
            self.active = SOURCE_DIRECT
            return await self.direct.fetch(macs)
        if self.gateway_failures:
            _LOGGER.info("the gateway answers again: back to the gateway")
        self.gateway_failures = 0
        self.active = SOURCE_GATEWAY
        if self.direct is not None:
            await self.direct.close()               # no need to keep a controller session while the gateway works
        return batch

    async def close(self) -> None:
        for s in (self.gateway, self.direct):
            if s is not None:
                await s.close()
