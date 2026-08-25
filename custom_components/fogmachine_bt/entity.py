"""Base entity for FogMachine BT."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FogMachineCoordinator


class FogMachineEntity(CoordinatorEntity[FogMachineCoordinator]):
    """Common device info + availability for all entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FogMachineCoordinator) -> None:
        super().__init__(coordinator)
        address = coordinator.address
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, address)},
            name=coordinator.config_entry.title,
            manufacturer="SPW",
            model="FG-series fog machine",
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None
