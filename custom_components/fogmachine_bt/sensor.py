"""Sensor platform: running time + diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import FogMachineConfigEntry
from .entity import FogMachineEntity
from .fogmachine.protocol import FogMachineState


@dataclass(frozen=True, kw_only=True)
class FogMachineSensorDescription(SensorEntityDescription):
    """Describes a fog-machine sensor."""

    value_fn: Callable[[FogMachineState], int | float | str | None]


def _running_hours(s: FogMachineState) -> float | None:
    # The device reports cumulative running time as HH:MM:SS; surface it in
    # hours, which is the meaningful unit for an operating-time meter.
    if s.running_seconds is None:
        return None
    return round(s.running_seconds / 3600, 2)


SENSORS: tuple[FogMachineSensorDescription, ...] = (
    FogMachineSensorDescription(
        key="running_time",
        translation_key="running_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=2,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_running_hours,
    ),
    FogMachineSensorDescription(
        key="mode",
        translation_key="mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=["always", "nimble", "advanced"],
        value_fn=lambda s: s.mode,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FogMachineConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(FogMachineSensor(coordinator, desc) for desc in SENSORS)


class FogMachineSensor(FogMachineEntity, SensorEntity):
    """A fog-machine sensor backed by query-all state."""

    entity_description: FogMachineSensorDescription

    def __init__(self, coordinator, description: FogMachineSensorDescription) -> None:  # noqa: ANN001
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def native_value(self) -> int | float | str | None:
        data = self.coordinator.data
        return None if data is None else self.entity_description.value_fn(data)
