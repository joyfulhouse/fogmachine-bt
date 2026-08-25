"""BLE client for FG-series fog machines (bleak + bleak-retry-connector).

HA-agnostic: give it a callable that returns the current ``BLEDevice`` and it
handles connect/reconnect, notification reassembly and command serialisation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from . import protocol as p

_LOGGER = logging.getLogger(__name__)

DEFAULT_COMMAND_TIMEOUT = 15.0


class FogMachineError(Exception):
    """Communication error talking to the fog machine."""


class FogMachineBLEClient:
    """Connection-managed client for one FG fog machine."""

    def __init__(
        self,
        device_getter: Callable[[], BLEDevice | None],
        name: str,
    ) -> None:
        self._device_getter = device_getter
        self._name = name
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()  # serialise commands (single-central device)
        self._connect_lock = asyncio.Lock()
        self._buffer = bytearray()
        self._response: asyncio.Future[str] | None = None
        self._loop = asyncio.get_running_loop()

    # -- connection ------------------------------------------------------- #
    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def _ensure_connected(self) -> BleakClientWithServiceCache:
        if self.is_connected:
            return self._client  # type: ignore[return-value]
        async with self._connect_lock:
            if self.is_connected:
                return self._client  # type: ignore[return-value]
            device = self._device_getter()
            if device is None:
                raise FogMachineError(f"{self._name}: no BLE device available (out of range?)")
            _LOGGER.debug("%s: connecting to %s", self._name, device.address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self._name,
                self._on_disconnected,
                use_services_cache=True,
            )
            await client.start_notify(p.CHAR_UUID, self._on_notify)
            self._client = client
            # Protocol init handshake: the app writes EE0c0. once services are
            # discovered and expects EE1c0. back. Best-effort (some units may
            # not reply); the following query is the real readiness check.
            try:
                await self._txn(client, p.build_connect(), True, DEFAULT_COMMAND_TIMEOUT)
            except FogMachineError:
                _LOGGER.debug("%s: connect handshake had no reply; continuing", self._name)
            _LOGGER.debug("%s: connected + notifications enabled", self._name)
            return client

    def _on_disconnected(self, _client: BleakClientWithServiceCache) -> None:
        _LOGGER.debug("%s: disconnected", self._name)
        self._client = None
        if self._response and not self._response.done():
            self._response.set_exception(FogMachineError("disconnected mid-command"))

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except BleakError as err:  # pragma: no cover - best effort
                _LOGGER.debug("%s: error on disconnect: %s", self._name, err)

    # -- notification reassembly ----------------------------------------- #
    def _on_notify(self, _char: BleakGATTCharacteristic, data: bytearray) -> None:
        self._buffer.extend(data)
        # A frame is complete once the end terminator '.' is present.
        if p.END.encode() in self._buffer and self._response and not self._response.done():
            frame = self._buffer.decode("latin1")
            self._buffer = bytearray()
            self._response.set_result(frame)

    # -- command core ----------------------------------------------------- #
    async def _txn(
        self,
        client: BleakClientWithServiceCache,
        request: bytes,
        expect_response: bool,
        timeout: float,
    ) -> str:
        """One request/response transaction on an already-connected client.

        Caller must serialise (hold ``self._lock`` or ``self._connect_lock``).
        """
        self._buffer = bytearray()
        self._response = self._loop.create_future() if expect_response else None
        _LOGGER.debug("%s: -> %s", self._name, request)
        for i in range(0, len(request), p.WRITE_CHUNK):
            await client.write_gatt_char(p.CHAR_UUID, request[i : i + p.WRITE_CHUNK], response=True)
        if not expect_response:
            return ""
        try:
            frame = await asyncio.wait_for(self._response, timeout)
        except TimeoutError as err:
            raise FogMachineError(f"{self._name}: timed out waiting for response") from err
        finally:
            self._response = None
        _LOGGER.debug("%s: <- %s", self._name, frame)
        return frame

    async def _send(self, request: bytes, expect_response: bool, timeout: float) -> str:
        async with self._lock:
            client = await self._ensure_connected()
            return await self._txn(client, request, expect_response, timeout)

    # -- high level ops --------------------------------------------------- #
    async def async_query(self, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> p.FogMachineState:
        """Read all device state (read-only)."""
        frame = await self._send(p.build_query_all(), True, timeout)
        return p.parse_query_all(frame)

    async def async_set_power(self, on: bool, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> None:
        frame = await self._send(p.build_power(on), True, timeout)
        _cmd, rc, _payload = p.parse_simple_response(frame)
        if rc != p.RC_OK:
            raise FogMachineError(f"{self._name}: power command rejected (rc={rc})")

    async def async_sync_clock(
        self, now: datetime, timeout: float = DEFAULT_COMMAND_TIMEOUT
    ) -> p.FogMachineState:
        """Push the device clock (production first-query form) and return state."""
        frame = await self._send(p.build_first_query(now), True, timeout)
        return p.parse_query_all(frame)
