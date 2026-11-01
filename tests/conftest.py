"""Shared fixtures: minimal Home Assistant stubs for coordinator tests.

CI runs pytest without a Home Assistant install (see
``.github/workflows/lint-test.yml``), so the few HA symbols
``coordinator.py`` imports are stubbed here before any test module imports
the component. Compatibility with a *real* HA install is covered separately
by ``tests/_import_check.py`` / ``tests/_import_smoke.py``.
"""

from __future__ import annotations

import enum
import importlib.util
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
    if importlib.util.find_spec("homeassistant") is not None:
        return  # a real HA install is present — use it, never shadow it

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

    def callback(func):
        return func

    core.HomeAssistant = HomeAssistant
    core.callback = callback

    config_entries = _register("homeassistant.config_entries")

    class ConfigEntry(Generic[_T]):
        """Stub of homeassistant.config_entries.ConfigEntry."""

        title = ""

    config_entries.ConfigEntry = ConfigEntry

    components = _register("homeassistant.components")
    bluetooth = _register("homeassistant.components.bluetooth")

    def async_ble_device_from_address(*_args, **_kwargs):
        return None

    def async_last_service_info(*_args, **_kwargs):
        return None

    def async_register_callback(*_args, **_kwargs):
        return lambda: None

    class BluetoothScanningMode(enum.Enum):
        PASSIVE = "passive"
        ACTIVE = "active"

    class BluetoothChange(enum.Enum):
        ADVERTISEMENT = 1

    def BluetoothCallbackMatcher(**kwargs):  # noqa: N802 - mirrors HA TypedDict
        return dict(kwargs)

    class BluetoothServiceInfoBleak:
        """Stub; tests use SimpleNamespace(device=..., time=...)."""

    bluetooth.async_ble_device_from_address = async_ble_device_from_address
    bluetooth.async_last_service_info = async_last_service_info
    bluetooth.async_register_callback = async_register_callback
    bluetooth.BluetoothScanningMode = BluetoothScanningMode
    bluetooth.BluetoothChange = BluetoothChange
    bluetooth.BluetoothCallbackMatcher = BluetoothCallbackMatcher
    bluetooth.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak

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


def _install_bluetooth_data_tools_stub() -> None:
    """bluetooth-data-tools ships with HA's bluetooth stack; stub it for CI."""
    if importlib.util.find_spec("bluetooth_data_tools") is not None:
        return
    import time

    mod = _register("bluetooth_data_tools")
    mod.monotonic_time_coarse = time.monotonic


_install_homeassistant_stubs()
_install_bluetooth_data_tools_stub()
