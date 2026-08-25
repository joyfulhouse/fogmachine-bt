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

DEFAULT_SCAN_INTERVAL = 60  # seconds between query-all polls

__all__ = [
    "DOMAIN",
    "SERVICE_UUID",
    "CHAR_UUID",
    "WRITE_CHUNK",
    "ENCODING",
    "NAME_PREFIX",
    "DEFAULT_SCAN_INTERVAL",
]
