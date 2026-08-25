"""Data update coordinator for FogMachine BT."""

from __future__ import annotations

import logging
from datetime import timedelta

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .fogmachine.client import FogMachineBLEClient, FogMachineError
from .fogmachine.protocol import FogMachineState

_LOGGER = logging.getLogger(__name__)

type FogMachineConfigEntry = ConfigEntry[FogMachineCoordinator]


class FogMachineCoordinator(DataUpdateCoordinator[FogMachineState]):
    """Polls a fog machine over BLE (via HA proxies) and issues commands."""

    def __init__(
        self, hass: HomeAssistant, entry: FogMachineConfigEntry, address: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {address}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            config_entry=entry,
        )
        self.address = address
        self._client = FogMachineBLEClient(self._get_device, entry.title or address)

    def _get_device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)

    async def _async_update_data(self) -> FogMachineState:
        if self._get_device() is None:
            raise UpdateFailed(f"{self.address} not currently reachable by any Bluetooth proxy")
        try:
            return await self._client.async_query()
        except (FogMachineError, BleakError) as err:
            raise UpdateFailed(str(err)) from err

    async def async_set_power(self, on: bool) -> None:
        """Turn the fogger on/off, then refresh state."""
        try:
            await self._client.async_set_power(on)
        except (FogMachineError, BleakError) as err:
            raise UpdateFailed(str(err)) from err
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self._client.disconnect()
