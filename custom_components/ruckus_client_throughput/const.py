"""Constants for Ruckus Client Throughput."""
from typing import Final

DOMAIN: Final = "ruckus_client_throughput"
CONFIG_VERSION: Final = 2                  # 1 = direct login only (0.1/0.2); 2 = adds the counter source (0.3)

CONF_CLIENTS: Final = "clients"            # list of client MACs to measure
CONF_SCAN_INTERVAL: Final = "scan_interval"
# The access points refresh each client's byte counters only about once a minute,
# so polling faster than that just loads the controller without adding resolution.
DEFAULT_SCAN_INTERVAL: Final = 60          # seconds
RUCKUS_DOMAIN: Final = "ruckus_unleashed"  # HA's built-in Ruckus integration (address/user prefill)

# Where the byte counters come from.
CONF_SOURCE: Final = "source"
SOURCE_AUTO: Final = "auto"                # gateway when it is set up and answering, else direct login
SOURCE_GATEWAY: Final = "gateway"          # only through the Ruckus gateway (never logs in to the controller)
SOURCE_DIRECT: Final = "direct"            # only a login of our own (the behaviour of 0.1 / 0.2)
SOURCES: Final = (SOURCE_AUTO, SOURCE_GATEWAY, SOURCE_DIRECT)
CONF_GATEWAY_URL: Final = "gateway_url"    # e.g. https://<gateway host>/ruckus
CONF_GATEWAY_KEY: Final = "gateway_key"    # bearer key of the gateway's HTTP front door (secret)
# CONF_HOST / CONF_USERNAME / CONF_PASSWORD (homeassistant.const) hold the direct login.

# Safety limits (all of them in one place).
REQUEST_TIMEOUT: Final = 20                # seconds before one request to the gateway / controller is abandoned
MAX_DATA_AGE: Final = 300                  # seconds; counters older than this are refused ("stale"), not shown
GATEWAY_FAILS_BEFORE_FALLBACK: Final = 3   # auto mode: failed polls in a row before the direct login is tried
LOGIN_BACKOFF_MIN: Final = 30              # seconds to wait after the first failed direct login ...
LOGIN_BACKOFF_MAX: Final = 600             # ... doubling each time, but never more than this
LOGIN_BACKOFF_JITTER: Final = 0.2          # +-20 % random spread so retries never line up
