# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
