# Ruckus Client Throughput

<img src="custom_components/ruckus_client_throughput/brand/icon.png" width="96" align="right" alt="logo">

A small Home Assistant integration that turns the traffic counters of a
**Ruckus Unleashed / ZoneDirector** Wi-Fi network into a live
**throughput sensor (kbit/s) per Wi-Fi client** you choose, e.g. your TVs, and a
**"data used today"** sensor per client.

## Contents

1. [Why?](#why)
2. [What you need](#what-you-need)
3. [Where the numbers come from: gateway or own login](#where-the-numbers-come-from-gateway-or-own-login)
4. [Install](#install) (HACS, manual, or the private-repository route)
5. [Set up, step by step](#set-up-step-by-step)
6. [Every option explained](#every-option-explained)
7. [The sensors](#the-sensors)
8. [Upgrading from 0.1 / 0.2](#upgrading-from-01--02)
9. [Safety built in](#safety-built-in)
10. [Troubleshooting](#troubleshooting)
11. [Uninstall](#uninstall)
12. [Tests and development](#tests-and-development)

## Why?

Your router (UniFi, pfSense, ...) only sees traffic that passes **through** it.
When your phone AirPlays or casts to a TV on the same Wi-Fi, that traffic stays
inside the Ruckus access points and the router never sees it. The access points
do count every byte, so this integration reads those counters.

Home Assistant's built-in **Ruckus** integration only tracks *presence*
(home/away); it doesn't expose traffic. This integration adds that.

## What you need

| Requirement | What it is and where to get it |
|---|---|
| **Home Assistant 2025.1 or newer** | The home automation software this plugs into. [Installation guide](https://www.home-assistant.io/installation/). |
| **A Ruckus Unleashed network** (or ZoneDirector) | The Wi-Fi system whose access points count the traffic. The "controller" is the one access point that manages the others (the *master* AP). |
| **One way to read the counters** (pick one, see next section) | Either a **Ruckus gateway** (a small helper service on your network) **or** an **admin login** for the controller. |
| Optional: the built-in [Ruckus integration](https://www.home-assistant.io/integrations/ruckus_unleashed/) | If it is set up, the controller address and user name are filled in for you. |
| Optional: [HACS](https://hacs.xyz/docs/use/) | Only needed for the HACS install route below. HACS cannot install *private* GitHub repositories; use the manual route for those. |

## Where the numbers come from: gateway or own login

The integration needs the byte counters of the clients you picked. It can get them two ways:

| Source | What happens | When to use it |
|---|---|---|
| **Gateway** (recommended) | Home Assistant sends **one small web request per minute** to your Ruckus gateway's read-only "front door" and gets the counters of all your chosen clients back. The gateway keeps the single admin session to the controller, caches and rate-limits, so the controller sees no extra login from Home Assistant. No controller password is stored in Home Assistant. | You run the ruckus-gateway (version 2.2.0 or newer) on your network. |
| **Own login** (the old way) | The integration logs in to the controller itself with an admin account and asks it directly every minute. | You have no gateway. |
| **Automatic** (default) | Gateway first. Only if the gateway fails **three polls in a row**, it uses the own login (if you set one up) and goes back to the gateway as soon as that answers again. | Safe choice: works even while the gateway is being updated. |

Why not always use the own login? A Ruckus controller allows only a few admin sessions. Every extra login is a risk
of locking out other tools. The gateway shares one session between everything.

## Install

### HACS (custom repository, public repositories)

1. In Home Assistant open **HACS**, click the three dots (top right) and choose **Custom repositories**.
2. Add `https://github.com/VibeOps-ZA/ruckus_client_throughput` as type **Integration**.
3. Open **Ruckus Client Throughput** in HACS and click **Download**.
4. **Restart Home Assistant** (Settings -> System -> top-right power icon -> Restart Home Assistant).

### Manual (public repositories or a downloaded copy)

1. Download the repository (green **Code** button -> *Download ZIP*) or copy the folder.
2. Copy the folder `custom_components/ruckus_client_throughput` into the `custom_components` folder inside your
   Home Assistant configuration folder (the one that contains `configuration.yaml`). Create `custom_components` if
   it does not exist. Guide: [Home Assistant configuration folder](https://www.home-assistant.io/docs/configuration/).
3. **Restart Home Assistant.** Integration code is only loaded at start, so a restart is needed after every
   install or update.

### Private repository: install or update by copying the folder (how the owner does it)

This repository is **private**. [HACS](https://hacs.xyz/docs/use/) can *track* a private repository (it shows that a
new version exists) but **cannot download** it: its downloads use anonymous GitHub addresses, which answer "404" for
a private repository. "Download ZIP" and release links also need a GitHub login. So install by copying the integration
folder onto Home Assistant yourself. Never switch the repository to public just to make HACS work.

1. **Make a backup first:** **Settings -> System -> Backups** ([Home Assistant backup docs](https://www.home-assistant.io/integrations/backup/)).
2. **Get the code** on a computer you trust that has access to the `VibeOps-ZA` GitHub account. The version running at the
   owner's home is the branch `feature/gateway-source`:
   ```bash
   git clone --branch feature/gateway-source https://github.com/VibeOps-ZA/ruckus_client_throughput.git
   ```
   GitHub asks for a user name and a **personal access token** as the password (a token with read-only access to this
   repository is enough; [how to create one](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)).
   Never paste the token into a file in this repository.
3. **Make Home Assistant reachable over SSH** (a command-line login) with the
   [Advanced SSH & Web Terminal app](https://github.com/hassio-addons/addon-ssh) (add it from the app store and give it
   your public key in its configuration), or the operating system's own SSH described in the
   [Home Assistant developer docs](https://developers.home-assistant.io/docs/operating-system/debugging/).
   In the commands below replace `HA_USER` and `HA_HOST` with your SSH user and Home Assistant's address.
4. **Copy the folder** (the old copy is removed first so deleted files do not linger; check the path twice, the
   `rm` removes only this one integration's folder):
   ```bash
   ssh HA_USER@HA_HOST 'rm -rf /config/custom_components/ruckus_client_throughput'
   scp -r ruckus_client_throughput/custom_components/ruckus_client_throughput HA_USER@HA_HOST:/config/custom_components/
   ```
   `/config` is Home Assistant's configuration folder (the one containing `configuration.yaml`). Your devices,
   entities and settings are stored inside Home Assistant, not in this folder, so nothing is lost.
5. **Restart Home Assistant** (**Settings -> System -> power icon -> Restart Home Assistant**). Home Assistant loads
   integration code only when it starts, so a restart is needed after every install or update.
6. **Check the version:** open `/config/custom_components/ruckus_client_throughput/manifest.json` (`"version": "0.3.1"` for this
   release) or look under **Settings -> Devices & services**.

**At the owner's home** steps 2-4 are run from the AI Pi host (`ai-pi`), which already holds the GitHub token and the SSH
access to Home Assistant, so nothing secret is typed or stored in this repository. Changes are made on a branch,
installed from it for testing, and merged to `main` only after the owner's OK.

## Set up, step by step

1. **Settings -> Devices & services -> Add integration**, search for **Ruckus Client Throughput**.
2. **Source:** pick *Automatic*, *Gateway only* or *Own login only* (see above).
3. **Gateway** (Automatic and Gateway only): enter the gateway address and the gateway key, then **Submit**.
   The integration reads the client list once to prove the address and key work.
4. **Controller login** (Own login only, or optional fallback in Automatic): enter the controller address, user
   and password. In Automatic you can leave the address empty to skip the fallback.
5. **Clients:** tick the Wi-Fi clients (for example your TVs) to measure. Only clients connected right now are
   listed; you can also type a MAC address (for a TV that is off at the moment).
6. Done. Each client gets a device named `<name> Ruckus` with two sensors, for example
   `sensor.study_tv_ruckus_wi_fi_throughput` and `sensor.study_tv_ruckus_wi_fi_data_today`.

Change anything later under **Settings -> Devices & services -> Ruckus Client Throughput -> Configure**.

## Every option explained

| Option | Where | Meaning |
|---|---|---|
| **Source** | setup and Configure | `Automatic` (gateway first, own login only as a fallback), `Gateway only` (never logs in to the controller), `Own login only` (only the old direct login). |
| **Gateway address** | setup and Configure | Full address of the gateway's front door including its path, e.g. `https://your-gateway-host/ruckus`. A trailing `/` is ignored. |
| **Gateway key** | setup and Configure | The secret key of the gateway's front door (set on the gateway as `RKUS_HTTP_KEY`). Stored in Home Assistant. In Configure, leave it empty to keep the stored key. |
| **Controller address** | setup and Configure | IP address or host name of the Unleashed master AP (or ZoneDirector). Needed for *Own login only*; optional for *Automatic* (empty = no fallback). |
| **Username / Password** | setup and Configure | An admin login of the controller. Left-empty password = reuse the built-in Ruckus integration's password at setup, or keep the stored one in Configure. |
| **Clients** | setup and Configure | The Wi-Fi clients to measure (their MAC addresses). Each gets the two sensors. |
| **Update interval** | setup and Configure | Seconds between reads, 10 to 300, default **60**. The access points refresh their counters only about once a minute, so a faster interval adds load but no detail. |

Fixed safety limits (not options): request timeout 20 s; counters older than 5 minutes are refused; fallback after 3
failed gateway polls; direct login back-off 30 s doubling up to 10 minutes (+-20 % jitter).

## The sensors

**Wi-Fi throughput** (kbit/s):

| | |
|---|---|
| State | Download + upload in kbit/s (`data_rate` device class, so you can show it in Mbit/s). |
| `download_kbps` / `upload_kbps` | The two directions separately. |
| `connected` | Whether the client is on the Wi-Fi right now (0 kbit/s when it isn't). |
| `access_point`, `ssid`, `mac` | Where the client is connected. |
| `counter_age_seconds` | How long ago the AP counters last moved. Up to ~60 s is normal; a larger value means the client is idle or the reading is stale. |

**Wi-Fi data today** (MB, `data_size`): data the client has used since **local midnight**, a `total_increasing`
sensor, so Home Assistant also builds a per-day history.

- It **survives Home Assistant restarts** and changing options (the value is restored, and only if it is from today).
- A client that **leaves the Wi-Fi and comes back** (a TV in standby) keeps today's total.
- It resets to 0 **at local midnight**; traffic after midnight counts for the new day.
- Attribute `date`: the day the total belongs to.
- After a client re-associates, the access point's counter restarts; the new traffic is added, nothing is lost.

**Good to know:** the Ruckus access points only refresh their counters about **once a minute**. The sensor shows
the average rate between the last two counter updates, so it reacts within about a minute and is **not** a
second-by-second meter. It's ideal for "is this TV streaming or idle?", not for spotting short bursts. If the
counters don't move for 2.5 polls (at least 2.5 minutes) the sensor drops to 0.

**Use with VIDAA Eco:** [VIDAA Eco](https://github.com/VibeOps-ZA/vidaa_eco) finds these sensors automatically
(they're `data_rate` sensors on a device with the TV's MAC), so AirPlay/casting to the TV counts as "in use" for
its auto power-off timer.

## Upgrading from 0.1 / 0.2

Copy the new files over the old ones and restart Home Assistant. Your entry is **migrated automatically** and keeps
working exactly as before (its own login, mode *Automatic* with no gateway set up). Entity ids, unique ids and
devices do not change, so dashboards and automations keep working. To switch to the gateway: **Configure** -> keep
*Automatic*, then enter the gateway address and key. Take a copy of your Home Assistant backup first
(Settings -> System -> Backups) if you like a safety net.

## Safety built in

- **No login storms (own login):** after a failed login or request the next login waits 30 s, then 60 s, 120 s ...
  up to 10 minutes, with random spread. A wrong password is reported once (Home Assistant asks you for the new one)
  instead of being retried. A single poll never logs in twice.
- **Gateway path:** one read-only request per poll for all clients (never one per client); the gateway applies its
  own login cap, cache, rate limit and retry. A wrong key is reported for re-authentication, never hidden by the
  fallback.
- **Stale data is refused:** counters older than 5 minutes are not shown.
- **Your daily totals are kept** across restarts, reloads and standby.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not read the counters" at setup | Check the gateway address (including the path) opens in a browser-like tool, or the controller address is the Unleashed master AP. |
| "The key or password was refused" | Wrong gateway key / controller password. After setup Home Assistant shows a **Repair/Re-authenticate** prompt: enter the new one. |
| Sensor is `unknown` | Normal for up to ~1 minute after start-up: it needs two counter updates to work out a rate. |
| Sensor `unavailable` for a few minutes | The gateway did not answer. In *Automatic* mode the own login takes over after 3 failed polls (if set up). |
| Client not in the list | It isn't connected right now; type its MAC address instead. |
| "waiting ... before the next login (back-off)" in the log | The own login failed recently; it retries by itself after the wait. |

Enable debug logging with:

```yaml
logger:
  logs:
    custom_components.ruckus_client_throughput: debug
```

## Uninstall

**Settings -> Devices & services -> Ruckus Client Throughput -> three dots -> Delete.** Then remove the folder
`custom_components/ruckus_client_throughput` (or uninstall in HACS) and restart Home Assistant.

## Tests and development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m ruff check . && .venv/bin/python -m pytest -q
```

The tests run without Home Assistant (small stand-ins in `tests/conftest.py`) and cover the rate and daily-total
maths, restore and midnight, the back-off, the gateway and direct sources, the automatic fallback, the migration and
that the unique ids did not change. CI runs hassfest, ruff and the tests on every push.

Files: `tracker.py` (rate and daily-total maths), `backoff.py`, `api.py` (gateway / direct / automatic sources),
`coordinator.py`, `sensor.py`, `config_flow.py`, `entry_data.py` (reading and migrating an entry).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Credits

Talks to the controller (own-login mode) with [aioruckus](https://github.com/ms264556/aioruckus)
(the same library Home Assistant's Ruckus integration uses). Not affiliated with
or endorsed by Ruckus / CommScope; the logo is an original design.

## License

MIT, see [LICENSE](LICENSE).
