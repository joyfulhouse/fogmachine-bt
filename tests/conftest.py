"""Shared fixtures: minimal Home Assistant stubs for coordinator tests.

CI runs pytest without a Home Assistant install (see
``.github/workflows/lint-test.yml``), so the few HA symbols
``coordinator.py`` imports are stubbed here before any test module imports
the component. Compatibility with a *real* HA install is covered separately
by ``tests/_import_check.py`` / ``tests/_import_smoke.py``.
"""

from __future__ import annotations

import enum
import os
import sys
import types
from typing import Generic, TypeVar

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_T = TypeVar("_T")


def _register(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _install_homeassistant_stubs() -> None:
    if "homeassistant" in sys.modules:  # a real HA install takes precedence
        return

    ha = _register("homeassistant")

    exceptions = _register("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        """Stub of homeassistant.exceptions.HomeAssistantError."""

    class ServiceValidationError(HomeAssistantError):
        """Stub of homeassistant.exceptions.ServiceValidationError."""

    class ConfigEntryNotReady(HomeAssistantError):
        """Stub of homeassistant.exceptions.ConfigEntryNotReady."""

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ServiceValidationError = ServiceValidationError
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady

    const = _register("homeassistant.const")

    class Platform(enum.StrEnum):
        """Stub of homeassistant.const.Platform (members this repo uses)."""

        BINARY_SENSOR = "binary_sensor"
        BUTTON = "button"
        NUMBER = "number"
        SELECT = "select"
        SENSOR = "sensor"
        SWITCH = "switch"
        TIME = "time"

    const.Platform = Platform

    core = _register("homeassistant.core")

    class HomeAssistant:
        """Stub of homeassistant.core.HomeAssistant."""

    core.HomeAssistant = HomeAssistant

    config_entries = _register("homeassistant.config_entries")

    class ConfigEntry(Generic[_T]):
        """Stub of homeassistant.config_entries.ConfigEntry."""

        title = ""

    config_entries.ConfigEntry = ConfigEntry

    components = _register("homeassistant.components")
    bluetooth = _register("homeassistant.components.bluetooth")

    def async_ble_device_from_address(*_args, **_kwargs):
        return None

    bluetooth.async_ble_device_from_address = async_ble_device_from_address

    helpers = _register("homeassistant.helpers")
    update_coordinator = _register("homeassistant.helpers.update_coordinator")

    class UpdateFailed(HomeAssistantError):
        """Stub of homeassistant.helpers.update_coordinator.UpdateFailed."""

    class DataUpdateCoordinator(Generic[_T]):
        """Minimal stand-in for HA's DataUpdateCoordinator."""

        def __init__(
            self,
            hass,
            logger,
            *,
            name: str = "",
            update_interval=None,
            config_entry=None,
        ) -> None:
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval
            self.config_entry = config_entry
            self.data = None

        def async_set_updated_data(self, data) -> None:
            self.data = data

        def async_update_listeners(self) -> None:
            pass

        async def async_shutdown(self) -> None:
            pass

    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator

    ha.exceptions = exceptions
    ha.const = const
    ha.core = core
    ha.config_entries = config_entries
    ha.components = components
    components.bluetooth = bluetooth
    ha.helpers = helpers
    helpers.update_coordinator = update_coordinator


_install_homeassistant_stubs()
