# Ruckus Client Throughput

<img src="custom_components/ruckus_client_throughput/brand/icon.png" width="96" align="right" alt="logo">

A small Home Assistant integration that turns the traffic counters of a
**Ruckus Unleashed / ZoneDirector** Wi-Fi network into a live
**throughput sensor (kbit/s) per Wi-Fi client** you choose, e.g. your TVs.

## Why?

Your router (UniFi, pfSense, …) only sees traffic that passes **through** it.
When your phone AirPlays or casts to a TV on the same Wi-Fi, that traffic stays
inside the Ruckus access points and the router never sees it. The access points
do count every byte, so this integration reads those counters.

Home Assistant's built-in **Ruckus** integration only tracks *presence*
(home/away); it doesn't expose traffic. This integration adds that.

## Requirements

- Home Assistant 2025.1 or newer.
- A Ruckus **Unleashed** network (or ZoneDirector) and an admin login.
- Optional: the built-in [Ruckus integration](https://www.home-assistant.io/integrations/ruckus_unleashed/).
  If it's set up, the address and user are filled in for you and the password can be left empty.

## Install

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/VibeOps-ZA/ruckus_client_throughput`, type **Integration**.
3. Install **Ruckus Client Throughput**, then restart Home Assistant.

### Manual

Copy `custom_components/ruckus_client_throughput` into your
`config/custom_components/` folder and restart Home Assistant.

## Set up

1. **Settings → Devices & services → Add integration → Ruckus Client Throughput.**
2. Enter the controller address, user and password (or accept the pre-filled
   values and leave the password empty to reuse the built-in integration's).
3. Pick the clients to measure. Only connected clients are listed; you can also
   type a MAC address (e.g. a TV that's off right now).
4. Done. Each client gets a device named `<name> Ruckus` with two sensors:
   a **Wi-Fi throughput** sensor (e.g. `sensor.study_tv_ruckus_wi_fi_throughput`)
   and a **Wi-Fi data today** sensor.

Change the clients or update interval later under **Configure** on the
integration card.

## The sensors

**Wi-Fi throughput** (kbit/s):

| | |
|---|---|
| State | Download + upload in kbit/s (`data_rate` device class, so you can show it in Mbit/s). |
| `download_kbps` / `upload_kbps` | The two directions separately. |
| `connected` | Whether the client is on the Wi-Fi right now (0 kbit/s when it isn't). |
| `access_point`, `ssid`, `mac` | Where the client is connected. |
| `counter_age_seconds` | How long ago the AP counters last moved. Up to ~60s is normal; a larger value means the client is idle or the reading is stale. |

**Wi-Fi data today** (MB, `data_size`): total data the client has used since local
midnight, as a `total_increasing` sensor, so Home Assistant also builds a per-day
history. It resets to 0 at midnight and after the client re-associates.

**Good to know:** the Ruckus access points only refresh their counters about
**once a minute**. The sensor shows the average rate between the last two
counter updates, so it reacts within about 1 minute and is **not** a
second-by-second meter. It's ideal for "is this TV streaming or idle?", not
for spotting short bursts. If the counters don't move for 2½ minutes the sensor
drops to 0.

## Use with VIDAA Eco

[VIDAA Eco](https://github.com/VibeOps-ZA/vidaa_eco) finds these sensors
automatically (they're `data_rate` sensors on a device with the TV's MAC), so
AirPlay/casting to the TV counts as "in use" for its auto power-off timer.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not log in" | Check the address is the Unleashed master AP and the user is an admin. |
| Sensor is `unknown` | Normal for up to ~1 minute after start-up: it needs two counter updates to work out a rate. |
| Client not in the list | It isn't connected right now; type its MAC address instead. |

Enable debug logging with:

```yaml
logger:
  logs:
    custom_components.ruckus_client_throughput: debug
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Credits

Talks to the controller with [aioruckus](https://github.com/ms264556/aioruckus)
(the same library Home Assistant's Ruckus integration uses). Not affiliated with
or endorsed by Ruckus / CommScope; the logo is an original design.

## License

MIT, see [LICENSE](LICENSE).
