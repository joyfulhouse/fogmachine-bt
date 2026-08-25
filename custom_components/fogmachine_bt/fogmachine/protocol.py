"""Wire protocol for FG-series BLE fog / misting machines.

Reverse-engineered from the OEM app ``com.spw.mistingapp2`` (SPW Misting).
See ``wiki/ble-protocol.md`` for the annotated spec and source citations.

Frame (both directions), plain ASCII, **no checksum**::

    EE <phase> <cmdId> <code> <payload...> <term>

* header  ``EE``
* phase   ``0`` = request (app->device), ``1`` = response (device->app)
* cmdId   1 char (see CMD_*)
* code    request: always ``0``; response: ``0`` = OK / ``1`` = fail
* payload command-specific
* term    ``.`` end-of-frame; within a query-all reply, sub-blocks are
          separated by ``,`` and the whole reply ends with ``.``

**Booleans are inverted: ``0`` = ON/enabled, ``1`` = OFF/disabled.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# --- GATT (HM-10 serial UART); MistingBLEServiceExecutor UUID_SERVICE/UUID_NOTIFY ---
SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"  # write AND notify
WRITE_CHUNK = 20  # bleWriteBufSize
ENCODING = "ascii"  # device uses GB2312, but all protocol bytes are ASCII

# --- frame literals (MistingCmdConstants) ---
HEADER = "EE"
END = "."
PART = ","
PHASE_REQUEST = "0"
PHASE_RESPONSE = "1"
REQUEST_CODE = "0"  # fixed 4th char in a request (return-code slot echoed as 0)
RC_OK = "0"
RC_FAIL = "1"

# --- command ids ---
CMD_QUERY = "0"  # query-all / running time
CMD_POWER = "1"
CMD_MODE = "2"  # customization mode
CMD_WEEKDAY = "3"
CMD_TIME_CUSTOMIZABLE = "4"
CMD_FREQ_CUSTOMIZABLE = "5"
CMD_TIME_CUSTOMIZE = "6"
CMD_FREQ_CUSTOMIZE = "7"
CMD_BATCH = "8"
CMD_CONNECT = "c"
CMD_DATETIME = "+"

# --- inverted boolean chars ---
ON = "0"
OFF = "1"

# customization mode chars
MODE_ALWAYS = "0"
MODE_NIMBLE = "1"
MODE_ADVANCED = "2"
MODE_NAMES = {MODE_ALWAYS: "always", MODE_NIMBLE: "nimble", MODE_ADVANCED: "advanced"}


class ProtocolError(Exception):
    """Raised when a frame cannot be parsed."""


# --------------------------------------------------------------------------- #
#  State model
# --------------------------------------------------------------------------- #
@dataclass
class FreqEntry:
    """A spray work/pause duty cycle ("frequency") entry (cmd 7)."""

    seq: int
    enabled: bool
    work_s: int
    pause_s: int


@dataclass
class TimeEntry:
    """A schedule time-window entry (cmd 6)."""

    seq: int
    enabled: bool
    from_h: int
    from_m: int
    to_h: int
    to_m: int


@dataclass
class FogMachineState:
    """Decoded device state from a query-all response."""

    power_on: bool | None = None
    running_seconds: int | None = None
    running_hms: tuple[int, int, int] | None = None
    mode: str | None = None
    weekdays: list[bool] | None = None  # Monday..Sunday
    time_customizable: bool | None = None
    freq_customizable: bool | None = None
    device_datetime: str | None = None
    freq_entries: dict[int, FreqEntry] = field(default_factory=dict)
    time_entries: dict[int, TimeEntry] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  Request builders
# --------------------------------------------------------------------------- #
def build_request(cmd_id: str, payload: str = "") -> bytes:
    """Build a request frame: ``EE`` + ``0`` + cmd_id + ``0`` + payload + ``.``."""
    return f"{HEADER}{PHASE_REQUEST}{cmd_id}{REQUEST_CODE}{payload}{END}".encode("ascii")


def build_power(on: bool) -> bytes:
    """Power ON (``EE0100.``) or OFF (``EE0101.``). Note inversion."""
    return build_request(CMD_POWER, ON if on else OFF)


def build_connect() -> bytes:
    """Protocol init handshake sent right after GATT connect+discovery.

    The app's ``c`` command writes ``EE0c0.`` once services are discovered and
    expects ``EE1c<rc>.`` back (MistingBLEServiceExecutor.run/inRun via the
    pending connect command). Send this before any query/control command.
    """
    return build_request(CMD_CONNECT, "")


def build_query_all() -> bytes:
    """Query all device state (``EE000.``). Read-only; does not actuate."""
    return build_request(CMD_QUERY, "")


def build_first_query(now: datetime) -> bytes:
    """First query after connect, carrying a clock sync (production path).

    Mirrors ``MistingDevQueryCmd.getCommandString()`` on first use:
    ``EE000+yyyyMMddHHmmssW.`` (W = weekday, Mon=0..Sun=6). Returns the full
    query-all state *and* sets the device clock.
    """
    payload = "+" + now.strftime("%Y%m%d%H%M%S") + str(now.weekday())
    return build_request(CMD_QUERY, payload)


def build_datetime_sync(now: datetime) -> bytes:
    """Direct datetime command ``EE0+0yyyyMMddHHmmssW.`` (cmd ``+``).

    NB: the OEM app does not send this standalone form in production — it embeds
    the clock in the first query (:func:`build_first_query`). Provided for
    completeness; prefer ``build_first_query`` to match the device's expectations.
    """
    payload = now.strftime("%Y%m%d%H%M%S") + str(now.weekday())
    return build_request(CMD_DATETIME, payload)


def build_weekday(day_index: int, on: bool) -> bytes:
    """Enable/disable a single scheduled weekday (cmd 3). day_index 0=Mon..6=Sun."""
    if not 0 <= day_index <= 6:
        raise ValueError("day_index must be 0..6")
    return build_request(CMD_WEEKDAY, f"{day_index}{ON if on else OFF}")


def build_mode(mode_char: str) -> bytes:
    """Set customization mode (cmd 2): '0' always / '1' nimble / '2' advanced."""
    if mode_char not in MODE_NAMES:
        raise ValueError("mode_char must be one of 0/1/2")
    return build_request(CMD_MODE, mode_char)


def build_freq_entry(seq: int, enabled: bool, work_s: int, pause_s: int) -> bytes:
    """Set a freq (work/pause) entry (cmd 7). 13-char payload."""
    payload = f"{seq:02d}{ON if enabled else OFF}{work_s:05d}{pause_s:05d}"
    if len(payload) != 13:
        raise ValueError(f"freq payload must be 13 chars, got {payload!r}")
    return build_request(CMD_FREQ_CUSTOMIZE, payload)


def build_time_entry(
    seq: int, enabled: bool, from_h: int, from_m: int, to_h: int, to_m: int
) -> bytes:
    """Set a schedule time window (cmd 6). 11-char payload."""
    payload = (
        f"{seq:02d}{ON if enabled else OFF}"
        f"{from_h:02d}{from_m:02d}{to_h:02d}{to_m:02d}"
    )
    if len(payload) != 11:
        raise ValueError(f"time payload must be 11 chars, got {payload!r}")
    return build_request(CMD_TIME_CUSTOMIZE, payload)


# --------------------------------------------------------------------------- #
#  Response parsers
# --------------------------------------------------------------------------- #
def _to_text(frame: bytes | str) -> str:
    if isinstance(frame, (bytes, bytearray)):
        return bytes(frame).decode("latin1")
    return frame


def parse_simple_response(frame: bytes | str) -> tuple[str, str, str]:
    """Parse a non-query response frame.

    Returns ``(cmd_id, return_code, payload)``. Mirrors
    ``AbstractMistingDevCmd.unpackResponse``.
    """
    s = _to_text(frame)
    if len(s) < 6:
        raise ProtocolError(f"response too short: {s!r}")
    if s[0:2] != HEADER:
        raise ProtocolError(f"bad header: {s!r}")
    if s[2:3] != PHASE_RESPONSE:
        raise ProtocolError(f"not a response phase: {s!r}")
    cmd_id = s[3:4]
    return_code = s[4:5]
    end = s.find(END, 5)
    if end < 5:
        raise ProtocolError(f"missing terminator: {s!r}")
    return cmd_id, return_code, s[5:end]


def parse_query_all(frame: bytes | str) -> FogMachineState:
    """Parse a query-all response into a :class:`FogMachineState`.

    The reply is a concatenation of ``EE 1 0 <rc> <subId> <data> ,`` blocks
    ending with ``.`` (``MistingDevQueryCmd.unpackResponse``).
    """
    s = _to_text(frame)
    if len(s) < 6:
        raise ProtocolError(f"query response too short: {s!r}")
    st = FogMachineState()
    i = 0
    n = len(s)
    while i < n - 1:
        if s[i : i + 2] != HEADER:
            raise ProtocolError(f"block header error at {i}: {s!r}")
        if s[i + 2 : i + 3] != PHASE_RESPONSE:
            raise ProtocolError(f"block phase error at {i}: {s!r}")
        if s[i + 3 : i + 4] != CMD_QUERY:
            raise ProtocolError(f"block id error at {i}: {s!r}")
        rc = s[i + 4 : i + 5]
        if rc != RC_OK:
            break  # device reported failure; stop (matches app)
        tail = s.find(PART, i + 5)
        if tail < i + 5:
            raise ProtocolError(f"block tail error at {i}: {s!r}")
        sub_id = s[i + 5 : i + 6]
        data = s[i + 6 : tail]
        _apply_sub(st, sub_id, data)
        i = tail + 1
    return st


def _apply_sub(st: FogMachineState, sub_id: str, data: str) -> None:
    """Decode one query-all sub-block into ``st`` (best-effort per field)."""
    try:
        if sub_id == CMD_DATETIME:
            st.device_datetime = data
        elif sub_id == CMD_QUERY:  # "0" running time HHMMSS
            hh, mm, ss = int(data[0:2]), int(data[2:4]), int(data[4:6])
            st.running_hms = (hh, mm, ss)
            st.running_seconds = hh * 3600 + mm * 60 + ss
        elif sub_id == CMD_POWER:  # "1"
            st.power_on = data[0:1] == ON
        elif sub_id == CMD_MODE:  # "2"
            st.mode = MODE_NAMES.get(data[0:1], data[0:1])
        elif sub_id == CMD_WEEKDAY:  # "3" 7 chars Mon..Sun
            st.weekdays = [c == ON for c in data[:7]]
        elif sub_id == CMD_TIME_CUSTOMIZABLE:  # "4"
            st.time_customizable = data[0:1] == ON
        elif sub_id == CMD_FREQ_CUSTOMIZABLE:  # "5"
            st.freq_customizable = data[0:1] == ON
        elif sub_id == CMD_TIME_CUSTOMIZE:  # "6" 11 chars
            st.time_entries[int(data[0:2])] = TimeEntry(
                seq=int(data[0:2]),
                enabled=data[2:3] == ON,
                from_h=int(data[3:5]),
                from_m=int(data[5:7]),
                to_h=int(data[7:9]),
                to_m=int(data[9:11]),
            )
        elif sub_id == CMD_FREQ_CUSTOMIZE:  # "7" 13 chars
            st.freq_entries[int(data[0:2])] = FreqEntry(
                seq=int(data[0:2]),
                enabled=data[2:3] == ON,
                work_s=int(data[3:8]),
                pause_s=int(data[8:13]),
            )
        # unknown sub_ids are ignored (forward-compatible)
    except (ValueError, IndexError) as err:
        raise ProtocolError(f"bad sub-block {sub_id!r} data {data!r}: {err}") from err
