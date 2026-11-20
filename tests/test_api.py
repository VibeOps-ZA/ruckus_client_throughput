"""The counter sources (api.py): gateway answers, direct login with back-off, automatic fallback."""
import asyncio

import aiohttp
import pytest

from custom_components.ruckus_client_throughput import api
from custom_components.ruckus_client_throughput.backoff import Backoff
from custom_components.ruckus_client_throughput.const import MAX_DATA_AGE, SOURCE_DIRECT, SOURCE_GATEWAY

MAC = "aa:bb:cc:00:00:01"
OTHER = "aa:bb:cc:00:00:02"


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------------------------------------- gateway
def gw_payload(age=5.0, now=1_000_000.0, **extra):
    return {"fetched_at": now - age, "age_s": age, "count": 2, "missing": [], "clients": {
        MAC: {"rx_bytes": 100, "tx_bytes": 200, "hostname": "Study TV", "ap": "AP-One", "ssid": "Home"},
        OTHER: {"rx_bytes": 1, "tx_bytes": 2, "hostname": None, "ap": None, "ssid": None}}, **extra}


def test_parse_gateway_maps_the_fields():
    batch = api.parse_gateway(gw_payload(), now=1_000_000.0)
    assert batch.source == SOURCE_GATEWAY and batch.fetched_at == 999_995.0
    assert batch.counters[MAC] == {"rx": 100, "tx": 200, "hostname": "Study TV", "ap_name": "AP-One", "ssid": "Home"}
    assert batch.counters[OTHER]["hostname"] == "" and batch.counters[OTHER]["ssid"] == ""


def test_parse_gateway_refuses_stale_and_broken_answers():
    with pytest.raises(api.SourceError, match="old"):
        api.parse_gateway(gw_payload(age=MAX_DATA_AGE + 10), now=1_000_000.0)
    for bad in ({}, {"clients": 5}, {"clients": {MAC: {"rx_bytes": "x", "tx_bytes": 1}}}, {"clients": {MAC: {}}}):
        with pytest.raises(api.SourceError, match="unexpected"):
            api.parse_gateway(bad)


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status, self._payload, self.headers = status, payload, headers or {}

    async def json(self, content_type=None):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeHttp:
    """Stand-in for Home Assistant's aiohttp session: answers from a script, remembers the calls."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def gateway(http):
    return api.GatewaySource(http, "https://gw.example/ruckus/", "secret-key")


def fresh_payload():
    import time
    return gw_payload(now=time.time())


def test_gateway_sends_one_bearer_request_with_all_macs():
    http = FakeHttp(FakeResponse(200, fresh_payload()))
    batch = run(gateway(http).fetch([MAC.upper(), OTHER]))
    assert len(http.calls) == 1                                   # ONE call for all clients, never one per client
    call = http.calls[0]
    assert call["url"] == "https://gw.example/ruckus/client-counters"
    assert call["params"] == {"macs": f"{MAC},{OTHER}"}
    assert call["headers"] == {"Authorization": "Bearer secret-key"}
    assert set(batch.counters) == {MAC, OTHER}


def test_gateway_without_macs_asks_for_everything():
    http = FakeHttp(FakeResponse(200, fresh_payload()))
    run(gateway(http).fetch(None))
    assert http.calls[0]["params"] is None


@pytest.mark.parametrize("status,error,text", [
    (401, api.SourceAuthError, "refused the key"),
    (403, api.SourceError, "address"),
    (429, api.SourceError, "rate limiting"),
    (503, api.SourceError, "503"),
])
def test_gateway_status_codes(status, error, text):
    http = FakeHttp(FakeResponse(status, {}, {"Retry-After": "30"}))
    with pytest.raises(error, match=text):
        run(gateway(http).fetch([MAC]))


def test_gateway_wrong_key_is_an_auth_error_of_kind_gateway():
    with pytest.raises(api.SourceAuthError) as err:
        run(gateway(FakeHttp(FakeResponse(401))).fetch([MAC]))
    assert err.value.kind == "gateway"


def test_gateway_network_problems_become_source_errors():
    for problem in (aiohttp.ClientConnectionError("down"), asyncio.TimeoutError()):
        with pytest.raises(api.SourceError, match="not reachable"):
            run(gateway(FakeHttp(problem)).fetch([MAC]))
    with pytest.raises(api.SourceError, match="not reachable"):
        run(gateway(FakeHttp(FakeResponse(200, ValueError("not json")))).fetch([MAC]))


# ------------------------------------------------------------------------------------------------- direct
XML = ("<ajax-response><response><apstamgr-stat>"
       f"<client mac='{MAC.upper()}' total-rx-bytes='10' total-tx-bytes='20' hostname='tv' ap-name='AP' ssid='Home'/>"
       f"<client mac='{OTHER}' total-rx-bytes='1' total-tx-bytes='2'/>"
       "<client mac='' total-rx-bytes='1' total-tx-bytes='2'/>"
       "<client mac='aa:bb:cc:00:00:09' total-rx-bytes='zzz' total-tx-bytes='2'/>"
       "</apstamgr-stat></response></ajax-response>")


def test_parse_direct_keeps_good_rows_and_skips_bad_ones():
    out = api.parse_direct(XML)
    assert set(out) == {MAC, OTHER}
    assert out[MAC] == {"rx": 10, "tx": 20, "hostname": "tv", "ap_name": "AP", "ssid": "Home"}


class FakeAjax:
    """Stand-in for an aioruckus session. `script` is a list of outcomes for requests: str = answer, Exception."""

    def __init__(self, log, script, login_error=None):
        self.log, self.script, self.login_error, self.closed = log, script, login_error, False
        self.api = self

    async def login(self):
        self.log.append("login")
        if self.login_error:
            raise self.login_error

    async def close(self):
        self.closed = True
        self.log.append("close")

    async def _cmdstat_noparse(self, request):
        self.log.append("request")
        out = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(out, Exception):
            raise out
        return out


class AuthenticationError(Exception):      # the name aioruckus uses; api.py matches it by name when aioruckus is absent
    pass


def direct(log, script, login_error=None, clock=None, **kw):
    backoff = Backoff(30, 600, jitter=0, clock=clock or (lambda: 0.0))
    return api.DirectSource("10.0.0.5", "admin", "pw", backoff=backoff,
                            session_factory=lambda *a: FakeAjax(log, script, login_error), **kw)


def test_direct_logs_in_once_and_keeps_the_session():
    log = []
    src = direct(log, [XML])
    for _ in range(5):
        batch = run(src.fetch([MAC]))
    assert log.count("login") == 1 and log.count("request") == 5      # a held session, not a login per poll
    assert set(batch.counters) == {MAC} and batch.source == SOURCE_DIRECT   # only the chosen client is returned


def test_direct_a_broken_session_cannot_cause_a_login_storm():
    log = []
    now = [0.0]
    src = direct(log, [ConnectionError("reset")], clock=lambda: now[0])

    async def hammer():
        errors = []
        for _ in range(50):                                         # 50 polls, 1 s apart, controller is broken
            try:
                await src.fetch([MAC])
            except api.SourceError as err:
                errors.append(str(err))
            now[0] += 1.0
        return errors
    errors = run(hammer())
    assert len(errors) == 50
    assert log.count("login") <= 2                                  # first login + one after the 30 s back-off
    assert any("back-off" in e for e in errors)


def test_direct_backoff_grows_and_is_capped_across_failed_logins():
    log = []
    now = [0.0]
    src = direct(log, [XML], login_error=ConnectionError("unreachable"), clock=lambda: now[0])

    async def hammer():
        for _ in range(400):                                        # 400 polls over ~100 minutes of outage
            try:
                await src.fetch([MAC])
            except api.SourceError:
                pass
            now[0] += 15.0
    run(hammer())
    # 30, 60, 120, 240, 480, then 600 s apart: a handful of logins, never one per poll
    assert log.count("login") <= 15
    assert src.backoff.wait_left() <= 600


def test_direct_refused_password_is_an_auth_error_and_is_not_retried_at_once():
    log = []
    src = direct(log, [XML], login_error=AuthenticationError("bad"))
    with pytest.raises(api.SourceAuthError) as err:
        run(src.fetch([MAC]))
    assert err.value.kind == "direct"
    with pytest.raises(api.SourceError, match="back-off"):
        run(src.fetch([MAC]))
    assert log.count("login") == 1


def test_direct_a_bad_answer_does_not_drop_a_good_session():
    log = []
    src = direct(log, ["<not xml", XML])
    with pytest.raises(api.SourceError, match="could not be read"):
        run(src.fetch([MAC]))
    assert "close" not in log
    run(src.fetch([MAC]))
    assert log.count("login") == 1                                   # same session, no new login


def test_direct_timeout_drops_the_session_and_backs_off():
    log = []

    class Slow(FakeAjax):
        async def _cmdstat_noparse(self, request):
            await asyncio.sleep(5)

    src = api.DirectSource("h", "u", "p", timeout=0.05, backoff=Backoff(30, 600, 0, clock=lambda: 0.0),
                           session_factory=lambda *a: Slow(log, [XML]))
    with pytest.raises(api.SourceError, match="request failed"):
        run(src.fetch([MAC]))
    assert "close" in log and src.backoff.wait_left() > 0


def test_direct_reports_a_clear_error_if_aioruckus_changed_its_private_call():
    class NoCall:
        api = object()

        async def login(self):
            return None

        async def close(self):
            return None
    src = api.DirectSource("h", "u", "p", backoff=Backoff(30, 600, 0, clock=lambda: 0.0),
                           session_factory=lambda *a: NoCall())
    with pytest.raises(api.SourceError, match="_cmdstat_noparse"):
        run(src.fetch([MAC]))


# ------------------------------------------------------------------------------------------------- auto
class StubSource:
    def __init__(self, name, outcomes):
        self.name, self.outcomes, self.calls, self.closed = name, list(outcomes), 0, 0

    async def fetch(self, macs=None):
        self.calls += 1
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, Exception):
            raise out
        return api.CounterBatch({MAC: {"rx": 1, "tx": 1}}, 1.0, self.name)

    async def close(self):
        self.closed += 1


def test_auto_uses_the_gateway_and_never_touches_the_direct_login():
    gw, dr = StubSource(SOURCE_GATEWAY, ["ok"]), StubSource(SOURCE_DIRECT, ["ok"])
    auto = api.AutoSource(gw, dr)
    for _ in range(4):
        assert run(auto.fetch([MAC])).source == SOURCE_GATEWAY
    assert dr.calls == 0 and auto.active == SOURCE_GATEWAY


def test_auto_falls_back_after_n_failures_and_returns_when_the_gateway_is_back():
    err = api.SourceError("down")
    gw, dr = StubSource(SOURCE_GATEWAY, [err, err, err, err, "ok"]), StubSource(SOURCE_DIRECT, ["ok"])
    auto = api.AutoSource(gw, dr, fails_before_fallback=3)
    for _ in range(2):                                               # first two failures: no fallback yet
        with pytest.raises(api.SourceError):
            run(auto.fetch([MAC]))
    assert dr.calls == 0
    assert run(auto.fetch([MAC])).source == SOURCE_DIRECT and auto.active == SOURCE_DIRECT
    assert run(auto.fetch([MAC])).source == SOURCE_DIRECT            # still failing: stays on the fallback
    assert run(auto.fetch([MAC])).source == SOURCE_GATEWAY           # recovered: gateway again ...
    assert auto.active == SOURCE_GATEWAY and auto.gateway_failures == 0
    assert dr.closed == 1                                            # ... and the controller session is released


def test_auto_a_refused_gateway_key_is_never_hidden_by_the_fallback():
    gw = StubSource(SOURCE_GATEWAY, [api.SourceAuthError("no", "gateway")])
    dr = StubSource(SOURCE_DIRECT, ["ok"])
    with pytest.raises(api.SourceAuthError):
        run(api.AutoSource(gw, dr, fails_before_fallback=1).fetch([MAC]))
    assert dr.calls == 0


def test_auto_gateway_only_just_raises_and_direct_only_just_works():
    err = api.SourceError("down")
    with pytest.raises(api.SourceError):
        run(api.AutoSource(StubSource(SOURCE_GATEWAY, [err]), None, fails_before_fallback=1).fetch([MAC]))
    assert run(api.AutoSource(None, StubSource(SOURCE_DIRECT, ["ok"])).fetch([MAC])).source == SOURCE_DIRECT
    with pytest.raises(ValueError):
        api.AutoSource(None, None)


def test_auto_close_closes_both():
    gw, dr = StubSource(SOURCE_GATEWAY, ["ok"]), StubSource(SOURCE_DIRECT, ["ok"])
    run(api.AutoSource(gw, dr).close())
    assert gw.closed == dr.closed == 1

