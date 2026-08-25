"""The FogMachine BT integration (local BLE control of FG-series fog machines)."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .coordinator import FogMachineConfigEntry, FogMachineCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: FogMachineConfigEntry) -> bool:
    """Set up FogMachine BT from a config entry."""
    address = entry.unique_id
    assert address is not None
    coordinator = FogMachineCoordinator(hass, entry, address)
    await coordinator.async_config_entry_first_refresh()
    if coordinator.data is None:
        raise ConfigEntryNotReady(f"{address} did not respond yet")
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FogMachineConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok
