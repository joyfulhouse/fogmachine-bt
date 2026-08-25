"""Switch platform: power control for the fog machine."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FogMachineConfigEntry
from .entity import FogMachineEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FogMachineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the power switch."""
    async_add_entities([FogMachinePowerSwitch(entry.runtime_data)])


class FogMachinePowerSwitch(FogMachineEntity, SwitchEntity):
    """Start/stop misting (protocol command 1; note the device inverts on/off)."""

    _attr_translation_key = "power"
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, coordinator) -> None:  # noqa: ANN001
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_power"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.power_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)
