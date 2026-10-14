"""Constants for Ruckus Client Throughput."""
from typing import Final

DOMAIN: Final = "ruckus_client_throughput"
CONF_CLIENTS: Final = "clients"            # list of client MACs to measure
CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 30          # seconds
RUCKUS_DOMAIN: Final = "ruckus_unleashed"  # HA's built-in Ruckus integration (credentials reuse)
