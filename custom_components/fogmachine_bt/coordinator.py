"""Data update coordinator for FogMachine BT."""

from __future__ import annotations

import logging
from datetime import timedelta

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAILURES_BEFORE_UNAVAILABLE,
    MAX_BACKOFF_INTERVAL,
)
from .fogmachine.client import FogMachineBLEClient, FogMachineError
from .fogmachine.protocol import FogMachineState

_LOGGER = logging.getLogger(__name__)

type FogMachineConfigEntry = ConfigEntry[FogMachineCoordinator]


class FogMachineCoordinator(DataUpdateCoordinator[FogMachineState]):
    """Polls a fog machine over BLE (via HA proxies) and issues commands.

    Tuned for a weak, single-proxy link: the client connects-per-poll and
    disconnects immediately (so the device keeps advertising), the interval
    backs off exponentially while the device is unreachable, and the last-known
    state is held through a few consecutive failures so entities don't flap to
    ``unavailable`` on an intermittent link.
    """

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
        self._failures = 0

    def _get_device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )

    def _on_success(self) -> None:
        self._failures = 0
        self.update_interval = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

    def _on_failure(self) -> None:
        self._failures += 1
        backoff = min(DEFAULT_SCAN_INTERVAL * 2**self._failures, MAX_BACKOFF_INTERVAL)
        self.update_interval = timedelta(seconds=backoff)

    async def _async_update_data(self) -> FogMachineState:
        try:
            if self._get_device() is None:
                raise FogMachineError(
                    f"{self.address} not currently reachable by any Bluetooth proxy"
                )
            data = await self._client.async_query()
            self._on_success()
            return data
        except (FogMachineError, BleakError) as err:
            self._on_failure()
            # Ride out brief dropouts on a marginal link: keep the last-known
            # state (entities stay available) until failures pile up.
            if self.data is not None and self._failures < FAILURES_BEFORE_UNAVAILABLE:
                _LOGGER.debug(
                    "%s: poll failed (%s); holding last state, retry in %ss",
                    self.address,
                    err,
                    int(self.update_interval.total_seconds()),
                )
                return self.data
            raise UpdateFailed(str(err)) from err

    async def async_set_power(self, on: bool) -> None:
        """Turn the fogger on/off and reflect the new state optimistically.

        The device acknowledges the command (return code OK), so we trust it and
        update state immediately. We deliberately do NOT re-query right away: on a
        weak link the reconnect-and-read can return the device's stale pre-change
        state and bounce the switch back. The next scheduled poll reconciles.
        """
        try:
            await self._client.async_set_power(on)
        except (FogMachineError, BleakError) as err:
            raise HomeAssistantError(str(err)) from err
        if self.data is not None:
            self.data.power_on = on
            self.async_update_listeners()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self._client.disconnect()
