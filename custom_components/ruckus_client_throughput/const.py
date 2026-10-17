"""Constants for Ruckus Client Throughput."""
from typing import Final

DOMAIN: Final = "ruckus_client_throughput"
CONF_CLIENTS: Final = "clients"            # list of client MACs to measure
CONF_SCAN_INTERVAL: Final = "scan_interval"
# The access points refresh each client's byte counters only about once a minute,
# so polling faster than that just loads the controller without adding resolution.
DEFAULT_SCAN_INTERVAL: Final = 60          # seconds
RUCKUS_DOMAIN: Final = "ruckus_unleashed"  # HA's built-in Ruckus integration (credentials reuse)
