"""The FogMachine BT integration (local BLE control of FG-series fog machines)."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import FogMachineConfigEntry, FogMachineCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: FogMachineConfigEntry) -> bool:
    """Set up FogMachine BT from a config entry.

    Setup must NOT block on the first BLE poll. When the user confirms the config
    flow, HA awaits this function inside the flow's HTTP request, and HA's HTTP
    server cancels a request's handler if the client goes away. A first poll
    over a weak proxy link can take ~2 minutes (connect retries + handshake +
    query timeouts), so blocking here let a closed dialog / mobile-app background
    / reverse-proxy timeout cancel setup into SETUP_ERROR, which HA never retries
    (issue #3). Instead: register entities now (unavailable until data arrives)
    and run the first poll in the background; the coordinator's normal
    interval + backoff keeps retrying from there.
    """
    address = entry.unique_id
    assert address is not None
    coordinator = FogMachineCoordinator(hass, entry, address)
    entry.runtime_data = coordinator
    # Forward first so the entities register as coordinator listeners — the
    # coordinator only schedules follow-up polls while it has listeners.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        name=f"{DOMAIN} first refresh {address}",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FogMachineConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
