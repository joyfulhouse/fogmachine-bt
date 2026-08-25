"""Framework-free protocol + client library for FG-series BLE fog machines.

This package has NO Home Assistant imports so it can be unit-tested standalone
and reused. See `protocol` for the wire format and `client` for the BLE wrapper.
"""

from .protocol import (
    FogMachineState,
    FreqEntry,
    ProtocolError,
    TimeEntry,
    build_connect,
    build_datetime_sync,
    build_first_query,
    build_freq_entry,
    build_mode,
    build_power,
    build_query_all,
    build_request,
    build_time_entry,
    build_weekday,
    parse_query_all,
    parse_simple_response,
)

__all__ = [
    "FogMachineState",
    "FreqEntry",
    "TimeEntry",
    "ProtocolError",
    "build_request",
    "build_connect",
    "build_power",
    "build_query_all",
    "build_first_query",
    "build_datetime_sync",
    "build_weekday",
    "build_mode",
    "build_freq_entry",
    "build_time_entry",
    "parse_query_all",
    "parse_simple_response",
]
