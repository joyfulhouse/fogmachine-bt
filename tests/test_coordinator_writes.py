"""Coordinator write methods: validation choke point + verified-write flow.

Uses the HA stubs from ``conftest.py`` and a fake client, so only coordinator
logic is under test: range validation (reject, never clamp), partial-delta
merging for cmd 6/7, error translation, and replacing ``coordinator.data``
with the freshly-read device state (no optimistic patching).
"""

from __future__ import annotations

import asyncio
import importlib.util
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.fogmachine_bt.coordinator import FogMachineCoordinator
from custom_components.fogmachine_bt.fogmachine import protocol as p
from custom_components.fogmachine_bt.fogmachine.client import FogMachineError


def _real_ha_installed() -> bool:
    """True only for a real Home Assistant install, never the conftest stubs."""
    try:
        return importlib.util.find_spec("homeassistant") is not None
    except ValueError:  # stub module in sys.modules has no __spec__
        return False


# These tests construct the coordinator against the conftest HA stubs
# (SimpleNamespace hass/config_entry); a real DataUpdateCoordinator needs a
# full hass and would fail loudly. The stubs never shadow a real install, so
# skip here instead.
pytestmark = pytest.mark.skipif(
    _real_ha_installed(),
    reason=(
        "stub-targeted unit tests; real-HA coverage is tests/_import_check.py "
        "+ the pytest-homeassistant-custom-component follow-up"
    ),
)


class FakeClient:
    """Records verified-write calls and returns a canned fresh state."""

    def __init__(
        self,
        state: p.FogMachineState | None = None,
        error: Exception | None = None,
    ) -> None:
        self.state = state if state is not None else p.FogMachineState()
        self.error = error
        self.calls: list[tuple] = []

    async def _result(self) -> p.FogMachineState:
        if self.error is not None:
            raise self.error
        return self.state

    async def async_set_mode(self, mode_char: str) -> p.FogMachineState:
        self.calls.append(("mode", mode_char))
        return await self._result()

    async def async_set_weekday(self, day_index: int, on: bool) -> p.FogMachineState:
        self.calls.append(("weekday", day_index, on))
        return await self._result()

    async def async_set_time_entry(self, entry: p.TimeEntry) -> p.FogMachineState:
        self.calls.append(("time_entry", entry))
        return await self._result()

    async def async_set_freq_entry(self, entry: p.FreqEntry) -> p.FogMachineState:
        self.calls.append(("freq_entry", entry))
        return await self._result()

    async def async_set_time_customizable(self, on: bool) -> p.FogMachineState:
        self.calls.append(("time_customizable", on))
        return await self._result()

    async def async_set_freq_customizable(self, on: bool) -> p.FogMachineState:
        self.calls.append(("freq_customizable", on))
        return await self._result()

    async def disconnect(self) -> None:
        pass


def _make(
    fake: FakeClient | None = None,
) -> tuple[FogMachineCoordinator, FakeClient]:
    fake = fake or FakeClient()
    entry = SimpleNamespace(title="FG-test")
    coordinator = FogMachineCoordinator(SimpleNamespace(), entry, "AA:BB:CC:DD:EE:FF")
    coordinator._client = fake
    return coordinator, fake


# --- mode ------------------------------------------------------------------ #
async def test_set_mode_maps_name_and_adopts_fresh_state():
    fresh = p.FogMachineState(mode="nimble")
    coordinator, fake = _make(FakeClient(state=fresh))
    await coordinator.async_set_mode("nimble")
    assert fake.calls == [("mode", p.MODE_NIMBLE)]
    assert coordinator.data is fresh  # replaced with read-back, not patched


async def test_set_mode_rejects_unknown_name():
    coordinator, fake = _make()
    for bad in ("turbo", "", "Always", 0, None):
        with pytest.raises(ServiceValidationError):
            await coordinator.async_set_mode(bad)
    assert fake.calls == []


async def test_set_mode_rejects_unhashable_value():
    coordinator, fake = _make()
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_mode(["always"])  # unhashable, non-str
    assert fake.calls == []


# --- weekday --------------------------------------------------------------- #
async def test_set_weekday_valid_bounds_pass_through():
    coordinator, fake = _make()
    await coordinator.async_set_weekday(0, True)
    await coordinator.async_set_weekday(6, False)
    assert fake.calls == [("weekday", 0, True), ("weekday", 6, False)]


async def test_set_weekday_rejects_bad_inputs():
    coordinator, fake = _make()
    for bad_day in (-1, 7, "1", True, None):
        with pytest.raises(ServiceValidationError):
            await coordinator.async_set_weekday(bad_day, True)
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_weekday(3, 1)  # non-bool enabled
    assert fake.calls == []


# --- window (cmd 6) -------------------------------------------------------- #
def _seeded_window(fresh: p.FogMachineState | None = None):
    coordinator, fake = _make(FakeClient(state=fresh or p.FogMachineState()))
    coordinator.data = p.FogMachineState(
        time_entries={
            1: p.TimeEntry(seq=1, enabled=True, from_h=6, from_m=0, to_h=22, to_m=30)
        }
    )
    return coordinator, fake


async def test_set_window_partial_delta_merges_current_entry():
    fresh = p.FogMachineState()
    coordinator, fake = _seeded_window(fresh)
    await coordinator.async_set_window(1, enabled=False)
    assert fake.calls == [
        (
            "time_entry",
            p.TimeEntry(seq=1, enabled=False, from_h=6, from_m=0, to_h=22, to_m=30),
        )
    ]
    assert coordinator.data is fresh


async def test_set_window_full_spec_needs_no_current_state():
    coordinator, fake = _make()
    assert coordinator.data is None
    await coordinator.async_set_window(2, from_hm=(0, 0), to_hm=(23, 59), enabled=True)
    assert fake.calls == [
        (
            "time_entry",
            p.TimeEntry(seq=2, enabled=True, from_h=0, from_m=0, to_h=23, to_m=59),
        )
    ]


async def test_set_window_partial_delta_without_known_entry_errors():
    coordinator, fake = _make()
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_window(1, enabled=False)
    assert fake.calls == []


async def test_set_window_range_rejections_never_clamp():
    coordinator, fake = _seeded_window()
    bad_kwargs = (
        {"from_hm": (23, 59)},  # start later than 23:58
        {"to_hm": (0, 0)},  # end earlier than 00:01
        {"from_hm": (24, 0)},  # hour out of range
        {"from_hm": (5, 60)},  # minute out of range
        {"to_hm": (-1, 30)},  # negative hour
        {"from_hm": (6,)},  # malformed pair
        {"enabled": 1},  # non-bool enabled
    )
    for kwargs in bad_kwargs:
        with pytest.raises(ServiceValidationError):
            await coordinator.async_set_window(1, **kwargs)
    with pytest.raises(ServiceValidationError):
        await coordinator.async_set_window(-1, enabled=False)  # bad seq
    assert fake.calls == []
    # boundary values are accepted, not clamped away
    await coordinator.async_set_window(1, from_hm=(23, 58), to_hm=(0, 1))
    assert fake.calls == [
        (
            "time_entry",
            p.TimeEntry(seq=1, enabled=True, from_h=23, from_m=58, to_h=0, to_m=1),
        )
    ]


# --- cycle (cmd 7) --------------------------------------------------------- #
def _seeded_cycle():
    coordinator, fake = _make()
    coordinator.data = p.FogMachineState(
        freq_entries={1: p.FreqEntry(seq=1, enabled=True, work_s=10, pause_s=20)}
    )
    return coordinator, fake


async def test_set_cycle_partial_delta_merges_current_entry():
    coordinator, fake = _seeded_cycle()
    await coordinator.async_set_cycle(1, work_s=30)
    assert fake.calls == [
        ("freq_entry", p.FreqEntry(seq=1, enabled=True, work_s=30, pause_s=20))
    ]


async def test_set_cycle_boundaries_accepted():
    coordinator, fake = _seeded_cycle()
    await coordinator.async_set_cycle(1, work_s=3, pause_s=5, enabled=True)
    await coordinator.async_set_cycle(1, work_s=84600, pause_s=84600, enabled=False)
    assert fake.calls == [
        ("freq_entry", p.FreqEntry(seq=1, enabled=True, work_s=3, pause_s=5)),
        ("freq_entry", p.FreqEntry(seq=1, enabled=False, work_s=84600, pause_s=84600)),
    ]


async def test_set_cycle_range_rejections_never_clamp():
    coordinator, fake = _seeded_cycle()
    bad_kwargs = (
        {"work_s": 2},  # below 3 s minimum
        {"work_s": 84601},  # above maximum
        {"pause_s": 4},  # below 5 s minimum
        {"pause_s": 84601},  # above maximum
        {"work_s": True},  # bool masquerading as int
        {"enabled": "yes"},  # non-bool enabled
    )
    for kwargs in bad_kwargs:
        with pytest.raises(ServiceValidationError):
            await coordinator.async_set_cycle(1, **kwargs)
    assert fake.calls == []


async def test_set_cycle_partial_delta_without_known_entry_errors():
    coordinator, fake = _make()
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_cycle(3, work_s=30)
    assert fake.calls == []


# --- concurrent partial merges (read-modify-write must be atomic) ----------- #
class StatefulFakeClient:
    """Applies whole-entry writes to a device-side state and returns it fresh.

    The await point mimics real BLE I/O, so concurrent coordinator calls can
    interleave — exactly the window the config-write lock must close.
    """

    def __init__(self, initial: p.FogMachineState) -> None:
        self.device = initial

    async def async_set_time_entry(self, entry: p.TimeEntry) -> p.FogMachineState:
        await asyncio.sleep(0)
        self.device = p.FogMachineState(
            time_entries={**self.device.time_entries, entry.seq: entry},
            freq_entries=dict(self.device.freq_entries),
        )
        return self.device

    async def async_set_freq_entry(self, entry: p.FreqEntry) -> p.FogMachineState:
        await asyncio.sleep(0)
        self.device = p.FogMachineState(
            time_entries=dict(self.device.time_entries),
            freq_entries={**self.device.freq_entries, entry.seq: entry},
        )
        return self.device


async def test_concurrent_partial_window_updates_are_not_lost():
    coordinator, _ = _make()
    fake = StatefulFakeClient(
        p.FogMachineState(
            time_entries={
                1: p.TimeEntry(
                    seq=1, enabled=True, from_h=6, from_m=0, to_h=22, to_m=30
                )
            }
        )
    )
    coordinator._client = fake
    coordinator.data = fake.device
    await asyncio.gather(
        coordinator.async_set_window(1, from_hm=(7, 15)),
        coordinator.async_set_window(1, to_hm=(21, 45)),
    )
    final = coordinator.data.time_entries[1]
    assert (final.from_h, final.from_m) == (7, 15)
    assert (final.to_h, final.to_m) == (21, 45)


async def test_concurrent_partial_cycle_updates_are_not_lost():
    coordinator, _ = _make()
    fake = StatefulFakeClient(
        p.FogMachineState(
            freq_entries={1: p.FreqEntry(seq=1, enabled=True, work_s=10, pause_s=20)}
        )
    )
    coordinator._client = fake
    coordinator.data = fake.device
    await asyncio.gather(
        coordinator.async_set_cycle(1, work_s=30),
        coordinator.async_set_cycle(1, pause_s=40),
    )
    final = coordinator.data.freq_entries[1]
    assert final.work_s == 30
    assert final.pause_s == 40


# --- customizable toggles (cmd 4/5) ---------------------------------------- #
async def test_set_customizable_toggles():
    coordinator, fake = _make()
    await coordinator.async_set_time_customizable(True)
    await coordinator.async_set_freq_customizable(False)
    assert fake.calls == [
        ("time_customizable", True),
        ("freq_customizable", False),
    ]
    for bad in (1, "on", None):
        with pytest.raises(ServiceValidationError):
            await coordinator.async_set_time_customizable(bad)
        with pytest.raises(ServiceValidationError):
            await coordinator.async_set_freq_customizable(bad)


# --- error translation ----------------------------------------------------- #
async def test_client_error_becomes_homeassistant_error():
    coordinator, _fake = _make(FakeClient(error=FogMachineError("write lost")))
    with pytest.raises(HomeAssistantError) as excinfo:
        await coordinator.async_set_mode("always")
    assert not isinstance(excinfo.value, ServiceValidationError)
    assert coordinator.data is None  # nothing adopted on failure
