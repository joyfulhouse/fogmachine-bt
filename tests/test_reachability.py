"""Reachability gating + advertisement-driven recovery (issue #5).

- Only connect when a proxy heard the device advertise recently. HA restores
  cached advertisements at startup, and the device goes silent while any
  central holds it, so "HA knows a BLEDevice" is not the same as "connectable".
- When a poll finds the device silent, the next fresh advertisement triggers an
  immediate poll instead of waiting out the backoff (up to 30 min).
- A connect *failure* to an advertising device does not arm that trigger, so a
  flaky unit is not hammered.
- The client never leaks a GATT link if a post-connect step fails.
"""

from __future__ import annotations

import asyncio
import importlib.util
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.fogmachine_bt.const import (
    DEFAULT_SCAN_INTERVAL,
    FRESH_ADVERTISEMENT_SECONDS,
)
from custom_components.fogmachine_bt.coordinator import FogMachineCoordinator
from custom_components.fogmachine_bt.fogmachine import client as client_mod
from custom_components.fogmachine_bt.fogmachine import protocol as p
from custom_components.fogmachine_bt.fogmachine.client import (
    FogMachineBLEClient,
    FogMachineError,
)

ADDRESS = "B0:7E:11:DE:A1:91"


def _real_ha_installed() -> bool:
    try:
        return importlib.util.find_spec("homeassistant") is not None
    except ValueError:  # stub module in sys.modules has no __spec__
        return False


stub_only = pytest.mark.skipif(
    _real_ha_installed(), reason="coordinator tests target the conftest HA stubs"
)


class FakeEntry:
    title = "FG11777"

    def __init__(self) -> None:
        self.unloads: list = []
        self.tasks: list = []

    def async_on_unload(self, func) -> None:  # noqa: ANN001
        self.unloads.append(func)

    def async_create_background_task(self, hass, target, name):  # noqa: ANN001
        self.tasks.append(target)
        target.close()  # not awaited in these tests


class FakeClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.queries = 0

    async def async_query(self) -> p.FogMachineState:
        self.queries += 1
        if self.error is not None:
            raise self.error
        return p.FogMachineState(power_on=True)


def _info(age: float) -> SimpleNamespace:
    return SimpleNamespace(device=object(), time=time.monotonic() - age)


def _make(monkeypatch, info, client: FakeClient | None = None):  # noqa: ANN001
    monkeypatch.setattr(
        bluetooth, "async_last_service_info", lambda *_a, **_k: info, raising=False
    )
    entry = FakeEntry()
    coordinator = FogMachineCoordinator(SimpleNamespace(), entry, ADDRESS)
    coordinator._client = client or FakeClient()
    refreshes: list[int] = []

    async def request_refresh() -> None:
        refreshes.append(1)

    coordinator.async_request_refresh = request_refresh
    return coordinator, entry, refreshes


# --- freshness gate -------------------------------------------------------- #
@stub_only
async def test_get_device_requires_fresh_advert(monkeypatch):
    fresh = _info(1)
    coordinator, _, _ = _make(monkeypatch, fresh)
    assert coordinator._get_device() is fresh.device

    coordinator, _, _ = _make(monkeypatch, _info(FRESH_ADVERTISEMENT_SECONDS + 5))
    assert coordinator._get_device() is None

    coordinator, _, _ = _make(monkeypatch, None)
    assert coordinator._get_device() is None


@stub_only
async def test_stale_advert_skips_connect_and_arms_recovery(monkeypatch):
    client = FakeClient()
    coordinator, _, _ = _make(monkeypatch, _info(600), client)
    with pytest.raises(UpdateFailed, match="not currently reachable"):
        await coordinator._async_update_data()
    assert client.queries == 0  # never tried to connect to a silent device
    assert coordinator._awaiting_advert


@stub_only
async def test_connect_failure_does_not_arm_recovery(monkeypatch):
    client = FakeClient(error=FogMachineError("ESP_GATT_ERROR status=133"))
    coordinator, _, _ = _make(monkeypatch, _info(1), client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert client.queries == 1
    assert not coordinator._awaiting_advert  # stays on backoff, no hammering
    assert coordinator.update_interval > timedelta(seconds=DEFAULT_SCAN_INTERVAL)


# --- advertisement-driven recovery ----------------------------------------- #
@stub_only
async def test_advert_after_unreachable_polls_once_and_resets_backoff(monkeypatch):
    coordinator, entry, refreshes = _make(monkeypatch, _info(600))
    for _ in range(3):  # pile up backoff while the device is silent
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
    assert coordinator.update_interval > timedelta(seconds=DEFAULT_SCAN_INTERVAL)

    adv = bluetooth.BluetoothChange.ADVERTISEMENT
    coordinator._async_on_advert(_info(0), adv)
    coordinator._async_on_advert(_info(0), adv)  # steady adverts: no re-trigger

    assert len(entry.tasks) == 1
    assert not coordinator._awaiting_advert
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


@stub_only
async def test_advert_ignored_when_reachable_or_stale(monkeypatch):
    coordinator, entry, _ = _make(monkeypatch, _info(1))
    adv = bluetooth.BluetoothChange.ADVERTISEMENT
    coordinator._async_on_advert(_info(0), adv)  # not waiting: no-op
    coordinator._awaiting_advert = True
    coordinator._async_on_advert(_info(600), adv)  # replayed cached advert
    assert entry.tasks == []
    assert coordinator._awaiting_advert


@stub_only
async def test_async_start_registers_passive_listener_and_unload(monkeypatch):
    calls = []

    def register(hass, cb, matcher, mode):  # noqa: ANN001
        calls.append((matcher, mode))
        return "unsub"

    monkeypatch.setattr(bluetooth, "async_register_callback", register, raising=False)
    coordinator, entry, _ = _make(monkeypatch, None)
    coordinator.async_start()
    assert calls == [
        (
            {"address": ADDRESS, "connectable": True},
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    ]
    assert entry.unloads == ["unsub"]


# --- client: no leaked GATT link ------------------------------------------- #
class FakeBleak:
    def __init__(self, notify_error: BaseException) -> None:
        self.notify_error = notify_error
        self.disconnects = 0

    async def start_notify(self, *_a) -> None:
        raise self.notify_error

    async def disconnect(self) -> None:
        self.disconnects += 1


@pytest.mark.parametrize(
    "error", [BleakError("notify failed"), asyncio.CancelledError()]
)
async def test_post_connect_failure_disconnects(monkeypatch, error):
    fake = FakeBleak(error)

    async def establish(*_a, **_k):
        return fake

    monkeypatch.setattr(client_mod, "establish_connection", establish)
    client = FogMachineBLEClient(lambda: SimpleNamespace(address=ADDRESS), "FG11777")
    with pytest.raises(type(error)):
        await client._ensure_connected()
    assert fake.disconnects == 1
    assert client._client is None
