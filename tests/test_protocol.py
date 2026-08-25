"""Unit tests for the FG fog-machine wire protocol.

These validate the reverse-engineered framing without a physical device. Run:
    uv run pytest
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

# Import the framework-free protocol lib directly from the component.
_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "custom_components", "fogmachine_bt"))

from fogmachine import protocol as p  # noqa: E402


def _block(sub_id: str, data: str, rc: str = "0") -> str:
    """Build one query-all sub-block: EE 1 0 <rc> <subId> <data> ,."""
    return f"{p.HEADER}{p.PHASE_RESPONSE}{p.CMD_QUERY}{rc}{sub_id}{data}{p.PART}"


# --- request builders ------------------------------------------------------ #
def test_build_power_inverted():
    assert p.build_power(True) == b"EE0100."  # ON  = '0'
    assert p.build_power(False) == b"EE0101."  # OFF = '1'


def test_build_query_all():
    assert p.build_query_all() == b"EE000."


def test_build_connect_handshake():
    # Init frame written after GATT connect+discovery (device replies EE1c0.)
    assert p.build_connect() == b"EE0c0."


def test_build_first_query_embeds_clock():
    # Production clock sync = query-all carrying "+yyyyMMddHHmmssW"
    frame = p.build_first_query(datetime(2026, 8, 24, 13, 5, 9))  # Monday -> 0
    assert frame == b"EE000+202608241305090."


def test_build_request_shape():
    # EE + phase0 + cmd + code0 + payload + '.'
    assert p.build_request(p.CMD_MODE, "2") == b"EE0202."


def test_build_weekday_and_bounds():
    assert p.build_weekday(2, True) == b"EE03020."  # Wed ON  -> idx 2 + '0'
    assert p.build_weekday(2, False) == b"EE03021."  # Wed OFF -> idx 2 + '1'
    for bad in (-1, 7):
        try:
            p.build_weekday(bad, True)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


def test_build_freq_and_time_widths():
    # frame = EE 0 <cmd> 0 <payload> .
    # freq: seq(2)+en(1)+work(5)+pause(5) = 13-char payload
    assert p.build_freq_entry(1, True, 3, 5) == b"EE0700100000300005."
    # time: seq(2)+en(1)+fromH(2)+fromM(2)+toH(2)+toM(2) = 11-char payload
    assert p.build_time_entry(1, True, 6, 0, 22, 30) == b"EE06001006002230."


def test_build_datetime_sync_weekday_index():
    # 2026-08-24 is a Monday -> datetime.weekday() == 0
    frame = p.build_datetime_sync(datetime(2026, 8, 24, 13, 5, 9))
    assert frame.startswith(b"EE0+0")  # EE + phase0 + cmd'+' + code0
    assert b"20260824130509" in frame
    assert frame.endswith(b"0.")  # Monday index 0 + terminator
    # Sunday -> 6
    assert p.build_datetime_sync(datetime(2026, 8, 23, 0, 0, 0)).endswith(b"6.")


# --- response parsers ------------------------------------------------------ #
def test_parse_simple_response():
    cmd, rc, payload = p.parse_simple_response("EE110.")
    assert (cmd, rc, payload) == ("1", "0", "")
    cmd, rc, payload = p.parse_simple_response(b"EE131A.")  # weekday echo example
    assert cmd == "3" and rc == "1" and payload == "A"


def test_parse_query_all_full():
    resp = (
        _block("0", "010530")  # running 1h05m30s
        + _block("1", "0")  # power ON
        + _block("2", "2")  # advanced mode
        + _block("3", "0000011")  # inverted: Mon-Fri on ('0'), Sat/Sun off ('1')
        + _block("4", "0")  # time customizable ON
        + _block("5", "1")  # freq customizable OFF
        + _block("6", "01006002230")  # window 1: 06:00-22:30 enabled
        + _block("7", "0100000300005")  # freq 1: 3s on / 5s off enabled
        + p.END
    )
    st = p.parse_query_all(resp)
    assert st.power_on is True
    assert st.running_hms == (1, 5, 30)
    assert st.running_seconds == 1 * 3600 + 5 * 60 + 30
    assert st.mode == "advanced"
    assert st.weekdays == [True, True, True, True, True, False, False]
    assert st.time_customizable is True
    assert st.freq_customizable is False
    assert st.time_entries[1] == p.TimeEntry(1, True, 6, 0, 22, 30)
    assert st.freq_entries[1] == p.FreqEntry(1, True, 3, 5)


def test_parse_query_all_partial_stops_on_fail():
    # A failing sub-block (rc=1) stops parsing; earlier fields survive.
    resp = _block("1", "1") + _block("0", "000000", rc="1") + p.END
    st = p.parse_query_all(resp)
    assert st.power_on is False  # '1' = OFF
    assert st.running_seconds is None  # not reached


def test_parse_query_all_rejects_garbage():
    for bad in ("", "ZZ", "XX100.", "EE"):
        try:
            p.parse_query_all(bad)
        except p.ProtocolError:
            continue
        # very short strings (len<6) must raise; longer bad headers must raise
        raise AssertionError(f"expected ProtocolError for {bad!r}")
