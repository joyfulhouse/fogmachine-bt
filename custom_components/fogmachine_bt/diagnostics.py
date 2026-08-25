"""Diagnostics for FogMachine BT.

Includes a full live BLE dump — every GATT service/characteristic, the value of
every readable characteristic, and the raw query-all response — so it's possible
to discover any device data the OEM app never surfaces (e.g. a water / low-water
status). Download from Settings → Devices & Services → FogMachine BT → the
three-dot menu → Download diagnostics.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import FogMachineConfigEntry

TO_REDACT = {"address"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FogMachineConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data: dict[str, Any] = {
        "address": coordinator.address,
        "update_interval_s": coordinator.update_interval.total_seconds()
        if coordinator.update_interval
        else None,
        "last_update_success": coordinator.last_update_success,
        "state": asdict(coordinator.data) if coordinator.data is not None else None,
    }
    try:
        data["ble_dump"] = await coordinator.async_explore()
    except Exception as err:  # noqa: BLE001
        data["ble_dump_error"] = f"{type(err).__name__}: {err}"
    return async_redact_data(data, TO_REDACT)
