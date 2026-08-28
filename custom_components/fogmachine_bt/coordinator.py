"""Data update coordinator for FogMachine BT."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from datetime import timedelta

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FAILURES_BEFORE_UNAVAILABLE,
    MAX_BACKOFF_INTERVAL,
    MAX_PAUSE_SECONDS,
    MAX_WINDOW_FROM_MINUTES,
    MAX_WORK_SECONDS,
    MIN_PAUSE_SECONDS,
    MIN_WINDOW_TO_MINUTES,
    MIN_WORK_SECONDS,
)
from .fogmachine.client import FogMachineBLEClient, FogMachineError
from .fogmachine.protocol import MODE_CHARS, FogMachineState, FreqEntry, TimeEntry

_LOGGER = logging.getLogger(__name__)

type FogMachineConfigEntry = ConfigEntry[FogMachineCoordinator]


# --- validation helpers (single choke point for config writes) --------------- #
def _validated_int(name: str, value: int, lo: int, hi: int) -> int:
    """Require an int in [lo, hi] — reject (never clamp) anything else."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceValidationError(f"{name} must be an integer, got {value!r}")
    if not lo <= value <= hi:
        raise ServiceValidationError(f"{name} must be {lo}..{hi}, got {value}")
    return value


def _validated_bool(name: str, value: bool) -> bool:
    if not isinstance(value, bool):
        raise ServiceValidationError(f"{name} must be a boolean, got {value!r}")
    return value


def _validated_hm(name: str, value: tuple[int, int]) -> tuple[int, int]:
    """Require an (hour, minute) pair with hour 0-23 and minute 0-59."""
    if not isinstance(value, tuple) or len(value) != 2:
        raise ServiceValidationError(
            f"{name} must be an (hour, minute) pair, got {value!r}"
        )
    hour = _validated_int(f"{name} hour", value[0], 0, 23)
    minute = _validated_int(f"{name} minute", value[1], 0, 59)
    return hour, minute


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

    # -- verified config writes (cmd 2-7) ---------------------------------- #
    # Unlike the power switch above, these are NOT optimistic: the client
    # writes, re-queries on the same connection and raises if the change did
    # not stick; the coordinator then adopts the freshly-read device state.
    # A config write that silently fails must surface as an error, not lie
    # until the next poll.

    async def _async_write_config(self, write: Awaitable[FogMachineState]) -> None:
        """Run a verified client write and adopt the read-back state."""
        try:
            state = await write
        except (FogMachineError, BleakError) as err:
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(state)

    async def async_set_mode(self, mode: str) -> None:
        """Set the customization mode: 'always' | 'nimble' | 'advanced'."""
        if mode not in MODE_CHARS:
            raise ServiceValidationError(
                f"mode must be one of {sorted(MODE_CHARS)}, got {mode!r}"
            )
        await self._async_write_config(self._client.async_set_mode(MODE_CHARS[mode]))

    async def async_set_weekday(self, day_idx: int, enabled: bool) -> None:
        """Enable/disable one scheduled weekday (0=Monday .. 6=Sunday)."""
        _validated_int("day_idx", day_idx, 0, 6)
        _validated_bool("enabled", enabled)
        await self._async_write_config(self._client.async_set_weekday(day_idx, enabled))

    async def async_set_window(
        self,
        seq: int,
        from_hm: tuple[int, int] | None = None,
        to_hm: tuple[int, int] | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Set a schedule time window (cmd 6); ``None`` keeps current values.

        The wire frame always carries the whole entry, so a partial delta is
        merged with the last-polled entry before building the frame.
        """
        _validated_int("seq", seq, 0, 99)
        current = self.data.time_entries.get(seq) if self.data else None
        if (from_hm is None or to_hm is None or enabled is None) and current is None:
            raise HomeAssistantError(
                f"window {seq}: partial update requested but the current entry "
                "is unknown (device not polled yet)"
            )
        if from_hm is None:
            from_h, from_m = current.from_h, current.from_m
        else:
            from_h, from_m = _validated_hm("from", from_hm)
        if to_hm is None:
            to_h, to_m = current.to_h, current.to_m
        else:
            to_h, to_m = _validated_hm("to", to_hm)
        if enabled is not None:
            _validated_bool("enabled", enabled)
        else:
            enabled = current.enabled
        if from_h * 60 + from_m > MAX_WINDOW_FROM_MINUTES:
            raise ServiceValidationError(
                "window start must be no later than 23:58, "
                f"got {from_h:02d}:{from_m:02d}"
            )
        if to_h * 60 + to_m < MIN_WINDOW_TO_MINUTES:
            raise ServiceValidationError(
                f"window end must be no earlier than 00:01, got {to_h:02d}:{to_m:02d}"
            )
        entry = TimeEntry(
            seq=seq,
            enabled=enabled,
            from_h=from_h,
            from_m=from_m,
            to_h=to_h,
            to_m=to_m,
        )
        await self._async_write_config(self._client.async_set_time_entry(entry))

    async def async_set_cycle(
        self,
        seq: int,
        work_s: int | None = None,
        pause_s: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Set a spray work/pause cycle (cmd 7); ``None`` keeps current values.

        The wire frame always carries the whole entry, so a partial delta is
        merged with the last-polled entry before building the frame.
        """
        _validated_int("seq", seq, 0, 99)
        current = self.data.freq_entries.get(seq) if self.data else None
        if (work_s is None or pause_s is None or enabled is None) and current is None:
            raise HomeAssistantError(
                f"cycle {seq}: partial update requested but the current entry "
                "is unknown (device not polled yet)"
            )
        if work_s is not None:
            _validated_int("work_s", work_s, MIN_WORK_SECONDS, MAX_WORK_SECONDS)
        else:
            work_s = current.work_s
        if pause_s is not None:
            _validated_int("pause_s", pause_s, MIN_PAUSE_SECONDS, MAX_PAUSE_SECONDS)
        else:
            pause_s = current.pause_s
        if enabled is not None:
            _validated_bool("enabled", enabled)
        else:
            enabled = current.enabled
        entry = FreqEntry(seq=seq, enabled=enabled, work_s=work_s, pause_s=pause_s)
        await self._async_write_config(self._client.async_set_freq_entry(entry))

    async def async_set_time_customizable(self, enabled: bool) -> None:
        """Enable/disable the schedule-time customization feature (cmd 4)."""
        _validated_bool("enabled", enabled)
        await self._async_write_config(
            self._client.async_set_time_customizable(enabled)
        )

    async def async_set_freq_customizable(self, enabled: bool) -> None:
        """Enable/disable the frequency customization feature (cmd 5)."""
        _validated_bool("enabled", enabled)
        await self._async_write_config(
            self._client.async_set_freq_customizable(enabled)
        )

    async def async_explore(self) -> dict:
        """Return a full BLE dump of the device (for diagnostics)."""
        return await self._client.async_explore()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self._client.disconnect()
