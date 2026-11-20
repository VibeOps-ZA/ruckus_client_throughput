# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-11-20

### Added
- **Counter source** setting: *Automatic* (default), *Gateway only* or *Own login only*. With a gateway the
  integration reads the byte counters of all chosen clients with **one HTTP request per poll** to the Ruckus
  gateway's read-only front door (`client-counters`, ruckus-gateway 2.2.0 or newer), so it no longer needs its own
  admin session on the controller. The own login stays as a fallback: in *Automatic* mode it is used only after the
  gateway failed three polls in a row, and it is released again as soon as the gateway answers.
- Config flow: source choice, gateway address + key (tested when you press Submit), optional fallback login, a
  re-authentication step for a refused key/password, and the same choices under **Configure**.
- **Wi-Fi data today** now survives Home Assistant restarts and option changes (restored state, plus an in-memory
  store across reloads), keeps today's total while a client is off the Wi-Fi (a sleeping TV), and resets exactly at
  local midnight (not at the next poll).
- Tests (pytest with Home Assistant stand-ins) and a CI job that runs them and `ruff`.

### Changed
- Direct login: a request timeout (20 s), **no repeated logins** - after a failure the next login waits 30 s,
  then 60 s, 120 s ... up to 10 minutes, with +-20 % jitter; a wrong password is reported once for
  re-authentication instead of being retried; a bad answer no longer throws away a good session.
- The rate is timed with the moment the controller was asked (the gateway reports it) instead of the moment Home
  Assistant polled, which removes most of the jitter in single readings.
- A client that leaves the Wi-Fi keeps its daily total (before, tracking restarted from 0 when it came back).
- Counters older than 5 minutes are refused rather than shown. The "idle" time follows slower poll intervals.
- `aioruckus` is limited to `>=0.42,<0.50`; a missing private call gives a clear error.
- Text: the interval hint says 60 s (was 30 s).

### Compatibility
- Entity ids, unique ids (`<mac>_throughput`, `<mac>_data_today`) and devices are **unchanged**.
- Existing entries are migrated automatically (config version 1 -> 2) and keep using their own login until a
  gateway address and key are added under **Configure**.
- New attribute `date` on the *Wi-Fi data today* sensor (which day the total belongs to).

## [0.2.0] - 2026-10-17

### Added
- **Wi-Fi data today** sensor per client (MB, `data_size`, resets at local midnight)
  for a per-day usage total and history.
- `counter_age_seconds` attribute on the throughput sensor, showing how old the
  current reading is (the APs refresh roughly once a minute).

### Changed
- Default update interval is now **60 s** (was 30 s) to match how often the access
  points refresh their counters - same resolution, half the load on the controller.

## [0.1.0] - 2026-10-14

### Added
- First release.
- UI setup that reuses the built-in Ruckus integration's address, user and password.
- A **Wi-Fi throughput** sensor (kbit/s, download + upload) per selected client, with
  download/upload, access point and SSID as attributes.
- Options to change the clients and the update interval.
- Light and dark logos (original design).
