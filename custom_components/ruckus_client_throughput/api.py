"""Read per-client byte counters from a Ruckus Unleashed / ZoneDirector controller.

Uses aioruckus (already installed with Home Assistant's built-in Ruckus
integration). Counters come from the controller's "LEVEL 2" client statistics:
``total-rx-bytes`` (received by the AP from the client = upload) and
``total-tx-bytes`` (sent by the AP to the client = download).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from aioruckus import AjaxSession

CLIENT_STATS_REQUEST = (
    "<ajax-request action='getstat' comp='stamgr' enable-gzip='0'>"
    "<client LEVEL='2' /></ajax-request>"
)


class RuckusClientApi:
    """Tiny wrapper that keeps one logged-in session and re-logs in on failure."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self._args = (host, username, password)
        self._session: AjaxSession | None = None

    async def _ensure(self) -> AjaxSession:
        if self._session is None:
            session = AjaxSession.async_create(*self._args)
            await session.login()
            self._session = session
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            finally:
                self._session = None

    async def client_counters(self) -> dict[str, dict]:
        """{mac: {rx, tx, hostname, ap_name, ssid}} for every connected client."""
        for attempt in (1, 2):
            try:
                session = await self._ensure()
                raw = await session.api._cmdstat_noparse(CLIENT_STATS_REQUEST)  # noqa: SLF001
                return _parse(raw)
            except Exception:
                await self.close()
                if attempt == 2:
                    raise
        return {}


def _parse(raw: str) -> dict[str, dict]:
    root = ET.fromstring(raw)
    out: dict[str, dict] = {}
    for el in root.iter("client"):
        mac = (el.get("mac") or "").lower()
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
