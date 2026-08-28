"""Write + read-back-verify paths of FogMachineBLEClient (no real BLE).

The BLE transport (``_ensure_connected`` / ``_txn`` / ``disconnect``) is
replaced with a scripted fake; the verify/retry logic under test is the real
client code. Frames follow the wire spec in ``wiki/ble-protocol.md``.
"""

from __future__ import annotations

import pytest

from custom_components.fogmachine_bt.fogmachine import client as client_mod
from custom_components.fogmachine_bt.fogmachine import protocol as p
from custom_components.fogmachine_bt.fogmachine.client import (
    FogMachineBLEClient,
    FogMachineError,
)


def _block(sub_id: str, data: str) -> str:
    """One query-all sub-block: EE 1 0 <rc> <subId> <data> ,."""
    return f"{p.HEADER}{p.PHASE_RESPONSE}{p.CMD_QUERY}{p.RC_OK}{sub_id}{data}{p.PART}"


def _query_reply(
    mode_char: str = p.MODE_ALWAYS,
    weekdays: str = "1111111",
    time_cust: str = "1",
    freq_cust: str = "1",
    time_entry: str = "01006002230",
    freq_entry: str = "0100000300005",
) -> str:
    return (
        _block(p.CMD_MODE, mode_char)
        + _block(p.CMD_WEEKDAY, weekdays)
        + _block(p.CMD_TIME_CUSTOMIZABLE, time_cust)
        + _block(p.CMD_FREQ_CUSTOMIZABLE, freq_cust)
        + _block(p.CMD_TIME_CUSTOMIZE, time_entry)
        + _block(p.CMD_FREQ_CUSTOMIZE, freq_entry)
        + p.END
    )


def _ack(cmd_id: str, rc: str = p.RC_OK) -> str:
    """A simple write acknowledgement: EE 1 <cmd> <rc> ."""
    return f"{p.HEADER}{p.PHASE_RESPONSE}{cmd_id}{rc}{p.END}"


class ScriptedLink:
    """Replace a client's BLE transport with canned response frames."""

    def __init__(self, client: FogMachineBLEClient, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[bytes] = []
        self.disconnects = 0
        client._ensure_connected = self._ensure_connected
        client._txn = self._txn
        client.disconnect = self._disconnect

    async def _ensure_connected(self) -> object:
        return object()

    async def _txn(self, _client, request, _expect_response, _timeout) -> str:
        self.requests.append(bytes(request))
        return self.responses.pop(0)

    async def _disconnect(self) -> None:
        self.disconnects += 1


def _make_client() -> FogMachineBLEClient:
    return FogMachineBLEClient(lambda: None, "unit-test")


async def test_set_mode_success_write_then_verify_on_same_connection():
    client = _make_client()
    link = ScriptedLink(
        client, [_ack(p.CMD_MODE), _query_reply(mode_char=p.MODE_ADVANCED)]
    )
    state = await client.async_set_mode(p.MODE_ADVANCED)
    assert state.mode == "advanced"
    # exactly one write + one query, then the connection is released
    assert link.requests == [b"EE0202.", b"EE000."]
    assert link.disconnects == 1


async def test_set_mode_mismatch_retries_read_once_then_succeeds(monkeypatch):
    monkeypatch.setattr(client_mod, "VERIFY_RETRY_DELAY", 0.0)
    client = _make_client()
    link = ScriptedLink(
        client,
        [
            _ack(p.CMD_MODE),
            _query_reply(mode_char=p.MODE_ALWAYS),  # stale on first read-back
            _query_reply(mode_char=p.MODE_ADVANCED),
        ],
    )
    state = await client.async_set_mode(p.MODE_ADVANCED)
    assert state.mode == "advanced"
    assert link.requests == [b"EE0202.", b"EE000.", b"EE000."]
    assert link.disconnects == 1


async def test_set_mode_persistent_mismatch_raises(monkeypatch):
    monkeypatch.setattr(client_mod, "VERIFY_RETRY_DELAY", 0.0)
    client = _make_client()
    link = ScriptedLink(
        client,
        [
            _ack(p.CMD_MODE),
            _query_reply(mode_char=p.MODE_ALWAYS),
            _query_reply(mode_char=p.MODE_ALWAYS),  # still stale after retry
        ],
    )
    with pytest.raises(FogMachineError):
        await client.async_set_mode(p.MODE_ADVANCED)
    assert len(link.requests) == 3  # write + two read-backs, then give up
    assert link.disconnects == 1


async def test_write_rejected_by_device_raises_without_read_back():
    client = _make_client()
    link = ScriptedLink(client, [_ack(p.CMD_MODE, rc=p.RC_FAIL)])
    with pytest.raises(FogMachineError):
        await client.async_set_mode(p.MODE_ADVANCED)
    assert link.requests == [b"EE0202."]  # no query after a rejected write
    assert link.disconnects == 1


async def test_set_weekday_verifies_day_bit():
    client = _make_client()
    # Saturday (idx 5) turned ON -> inverted char '0' at position 5
    link = ScriptedLink(client, [_ack(p.CMD_WEEKDAY), _query_reply(weekdays="1111101")])
    state = await client.async_set_weekday(5, True)
    assert state.weekdays is not None
    assert state.weekdays[5] is True
    assert link.requests[0] == b"EE03050."


async def test_set_time_entry_verifies_whole_entry():
    client = _make_client()
    entry = p.TimeEntry(seq=1, enabled=True, from_h=6, from_m=0, to_h=22, to_m=30)
    link = ScriptedLink(
        client, [_ack(p.CMD_TIME_CUSTOMIZE), _query_reply(time_entry="01006002230")]
    )
    state = await client.async_set_time_entry(entry)
    assert state.time_entries[1] == entry
    assert link.requests[0] == b"EE06001006002230."


async def test_set_freq_entry_mismatch_raises(monkeypatch):
    monkeypatch.setattr(client_mod, "VERIFY_RETRY_DELAY", 0.0)
    client = _make_client()
    entry = p.FreqEntry(seq=1, enabled=True, work_s=3, pause_s=5)
    stale = _query_reply(freq_entry="0110000300005")  # device kept it disabled
    link = ScriptedLink(client, [_ack(p.CMD_FREQ_CUSTOMIZE), stale, stale])
    with pytest.raises(FogMachineError):
        await client.async_set_freq_entry(entry)
    assert link.requests[0] == b"EE0700100000300005."
    assert link.disconnects == 1


async def test_set_customizable_toggles_verify():
    client = _make_client()
    link = ScriptedLink(
        client, [_ack(p.CMD_TIME_CUSTOMIZABLE), _query_reply(time_cust="0")]
    )
    state = await client.async_set_time_customizable(True)
    assert state.time_customizable is True
    assert link.requests == [b"EE0400.", b"EE000."]

    link = ScriptedLink(
        client, [_ack(p.CMD_FREQ_CUSTOMIZABLE), _query_reply(freq_cust="1")]
    )
    state = await client.async_set_freq_customizable(False)
    assert state.freq_customizable is False
    assert link.requests == [b"EE0501.", b"EE000."]
