"""async_setup_entry must not block on the first BLE poll (issue #3).

HA awaits ``async_setup_entry`` inside the config flow's HTTP request and
cancels it if the client disconnects. A slow first poll over a weak proxy link
therefore got cancelled into SETUP_ERROR (never retried). Setup now forwards the
platforms and runs the first refresh as a background task.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import custom_components.fogmachine_bt as integration


class FakeCoordinator:
    """Coordinator whose first refresh hangs like a slow BLE connect."""

    instances: list[FakeCoordinator] = []

    def __init__(self, hass, entry, address) -> None:  # noqa: ANN001
        self.address = address
        self.refresh_started = asyncio.Event()
        self.release = asyncio.Event()
        self.refreshed = False
        self.entry = entry
        FakeCoordinator.instances.append(self)

    def async_start(self) -> None:
        self.entry.events.append("start")

    async def async_refresh(self) -> None:
        self.refresh_started.set()
        await self.release.wait()
        self.refreshed = True


class FakeEntry:
    unique_id = "02:11:23:34:5A:17"
    title = "FG11777"

    def __init__(self) -> None:
        self.runtime_data = None
        self.tasks: list[asyncio.Task] = []
        self.events: list[str] = []

    def async_create_background_task(self, hass, target, name, eager_start=True):  # noqa: ANN001
        self.events.append("background_task")
        task = asyncio.ensure_future(target)
        self.tasks.append(task)
        return task


async def test_setup_returns_without_waiting_for_first_poll(monkeypatch):
    monkeypatch.setattr(integration, "FogMachineCoordinator", FakeCoordinator)
    entry = FakeEntry()

    async def forward(e, platforms):  # noqa: ANN001
        entry.events.append("forward")

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_forward_entry_setups=forward)
    )

    # Would hang forever if setup awaited the (never-completing) first refresh.
    result = await asyncio.wait_for(integration.async_setup_entry(hass, entry), 1)

    assert result is True
    coordinator = FakeCoordinator.instances[-1]
    assert entry.runtime_data is coordinator
    # Platforms (coordinator listeners) must exist before the first poll runs,
    # otherwise the coordinator never schedules follow-up polls.
    # The advertisement listener is registered before anything else (#5).
    assert entry.events == ["start", "forward", "background_task"]

    await coordinator.refresh_started.wait()
    assert not coordinator.refreshed
    coordinator.release.set()
    await asyncio.gather(*entry.tasks)
    assert coordinator.refreshed
