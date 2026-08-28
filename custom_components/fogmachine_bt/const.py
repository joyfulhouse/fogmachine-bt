"""Constants for the FogMachine BT integration."""

from __future__ import annotations

from .fogmachine.protocol import (  # re-export protocol-level GATT constants
    CHAR_UUID,
    ENCODING,
    SERVICE_UUID,
    WRITE_CHUNK,
)

DOMAIN = "fogmachine_bt"

# Advertised name prefix for FG-series fog machines (e.g. "FG53850").
NAME_PREFIX = "FG"

# --- weak-link tuning ---
# These devices are cheap HM-10 modules that may be reachable by only a single,
# distant Bluetooth proxy at marginal RSSI (-80..-90 dBm). Two consequences shape
# the polling strategy (see wiki/ha-proxy-coverage.md):
#   1. The device allows ONE central connection and STOPS ADVERTISING while
#      connected — so a persistently-held GATT link hides it from every proxy and
#      makes reconnection impossible once the marginal link drops. We therefore
#      connect-per-poll and disconnect immediately, maximising advertise time.
#   2. State changes slowly (schedules/duty cycles), so a long base interval is
#      fine and reduces link churn.
DEFAULT_SCAN_INTERVAL = 180  # seconds between query-all polls (base)
MAX_BACKOFF_INTERVAL = 1800  # cap for exponential backoff on repeated failure
# Keep the last-known state (entities stay available) through this many
# consecutive poll failures before surfacing as unavailable — avoids flapping on
# a marginal link that succeeds intermittently.
FAILURES_BEFORE_UNAVAILABLE = 4

# --- config-write validation limits (choke point: coordinator) ---
# Mirror the OEM app's input limits (wiki/ble-protocol.md): spray duty cycle
# work 3–84600 s / pause 5–84600 s; schedule windows start no later than 23:58
# and end no earlier than 00:01. Out-of-range values are rejected, never clamped.
MIN_WORK_SECONDS = 3
MAX_WORK_SECONDS = 84600
MIN_PAUSE_SECONDS = 5
MAX_PAUSE_SECONDS = 84600
MAX_WINDOW_FROM_MINUTES = 23 * 60 + 58  # latest window start: 23:58
MIN_WINDOW_TO_MINUTES = 1  # earliest window end: 00:01

__all__ = [
    "DOMAIN",
    "SERVICE_UUID",
    "CHAR_UUID",
    "WRITE_CHUNK",
    "ENCODING",
    "NAME_PREFIX",
    "DEFAULT_SCAN_INTERVAL",
    "MAX_BACKOFF_INTERVAL",
    "FAILURES_BEFORE_UNAVAILABLE",
    "MIN_WORK_SECONDS",
    "MAX_WORK_SECONDS",
    "MIN_PAUSE_SECONDS",
    "MAX_PAUSE_SECONDS",
    "MAX_WINDOW_FROM_MINUTES",
    "MIN_WINDOW_TO_MINUTES",
]
