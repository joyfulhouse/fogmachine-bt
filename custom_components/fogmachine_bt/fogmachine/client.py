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
        # Determined from the FFE1 characteristic at connect time. HM-10 clones
        # are commonly write-without-response only (write-with-response returns
        # GATT error 3 "write not permitted").
        self._write_response = False

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
                raise FogMachineError(
                    f"{self._name}: no BLE device available (out of range?)"
                )
            _LOGGER.debug("%s: connecting to %s", self._name, device.address)
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                self._name,
                self._on_disconnected,
                use_services_cache=True,
            )
            await client.start_notify(p.CHAR_UUID, self._on_notify)
            # Pick write type from the characteristic's advertised properties:
            # prefer write-without-response (HM-10 serial pipe) to avoid GATT
            # error 3 on write-without-response-only clones.
            char = client.services.get_characteristic(p.CHAR_UUID)
            props = list(char.properties) if char else []
            self._write_response = (
                "write-without-response" not in props and "write" in props
            )
            _LOGGER.debug(
                "%s: FFE1 properties=%s -> write_response=%s",
                self._name,
                props,
                self._write_response,
            )
            self._client = client
            # Protocol init handshake: the app writes EE0c0. once services are
            # discovered and expects EE1c0. back. Best-effort (some units may
            # not reply); the following query is the real readiness check.
            try:
                await self._txn(
                    client, p.build_connect(), True, DEFAULT_COMMAND_TIMEOUT
                )
            except FogMachineError:
                _LOGGER.debug(
                    "%s: connect handshake had no reply; continuing", self._name
                )
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
        if (
            p.END.encode() in self._buffer
            and self._response
            and not self._response.done()
        ):
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
            await client.write_gatt_char(
                p.CHAR_UUID,
                request[i : i + p.WRITE_CHUNK],
                response=self._write_response,
            )
        if not expect_response:
            return ""
        try:
            frame = await asyncio.wait_for(self._response, timeout)
        except TimeoutError as err:
            raise FogMachineError(
                f"{self._name}: timed out waiting for response"
            ) from err
        finally:
            self._response = None
        _LOGGER.debug("%s: <- %s", self._name, frame)
        return frame

    async def _send(
        self,
        request: bytes,
        expect_response: bool,
        timeout: float,
        disconnect_after: bool = False,
    ) -> str:
        async with self._lock:
            try:
                client = await self._ensure_connected()
                return await self._txn(client, request, expect_response, timeout)
            finally:
                # On a weak single-proxy link we release the connection slot after
                # every operation so the device resumes advertising and stays
                # discoverable/reconnectable (it stops advertising while a central
                # is connected). See const.py / wiki/ha-proxy-coverage.md.
                if disconnect_after:
                    await self.disconnect()

    # -- high level ops --------------------------------------------------- #
    async def async_query(
        self,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
        disconnect_after: bool = True,
    ) -> p.FogMachineState:
        """Read all device state (read-only). Disconnects after by default."""
        frame = await self._send(
            p.build_query_all(), True, timeout, disconnect_after=disconnect_after
        )
        return p.parse_query_all(frame)

    async def async_set_power(
        self,
        on: bool,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
        disconnect_after: bool = True,
    ) -> None:
        frame = await self._send(
            p.build_power(on), True, timeout, disconnect_after=disconnect_after
        )
        _cmd, rc, _payload = p.parse_simple_response(frame)
        if rc != p.RC_OK:
            raise FogMachineError(f"{self._name}: power command rejected (rc={rc})")

    async def async_sync_clock(
        self,
        now: datetime,
        timeout: float = DEFAULT_COMMAND_TIMEOUT,
        disconnect_after: bool = True,
    ) -> p.FogMachineState:
        """Push the device clock (production first-query form) and return state."""
        frame = await self._send(
            p.build_first_query(now), True, timeout, disconnect_after=disconnect_after
        )
        return p.parse_query_all(frame)

    async def async_explore(self, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> dict:
        """Dump everything the device exposes over BLE, for diagnostics.

        Enumerates every GATT service + characteristic, reads every readable
        characteristic (hex + ascii), and captures the raw query-all response.
        Useful for discovering data the OEM app never surfaces (e.g. a water /
        low-water status on a characteristic the app does not read).
        """
        async with self._lock:
            client = await self._ensure_connected()
            try:
                services: list[dict] = []
                for svc in client.services:
                    chars: list[dict] = []
                    for ch in svc.characteristics:
                        props = list(ch.properties)
                        entry: dict = {
                            "uuid": str(ch.uuid),
                            "handle": ch.handle,
                            "properties": props,
                        }
                        if "read" in props:
                            try:
                                val = bytes(await client.read_gatt_char(ch))
                                entry["value_hex"] = val.hex()
                                entry["value_ascii"] = val.decode("latin1", "replace")
                            except Exception as err:  # noqa: BLE001
                                entry["read_error"] = f"{type(err).__name__}: {err}"
                        chars.append(entry)
                    services.append(
                        {"service": str(svc.uuid), "characteristics": chars}
                    )
                raw = await self._txn(client, p.build_query_all(), True, timeout)
                return {"services": services, "query_all_raw": raw}
            finally:
                await self.disconnect()
