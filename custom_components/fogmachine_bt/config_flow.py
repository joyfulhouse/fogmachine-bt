"""Config flow for FogMachine BT (Bluetooth discovery + manual pick)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DOMAIN, NAME_PREFIX, SERVICE_UUID


def _is_fog_machine(info: BluetoothServiceInfoBleak) -> bool:
    """Match FG-series fog machines: FFE0 service AND an FG* name."""
    name = (info.name or "").upper()
    return SERVICE_UUID in info.service_uuids and name.startswith(NAME_PREFIX)


class FogMachineConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FogMachine BT."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device discovered via Bluetooth."""
        # The manifest matcher is FFE0-only (generic HM-10); narrow to FG* here
        # (HA rejects local_name matchers with a wildcard in the first 3 chars).
        if not (discovery_info.name or "").upper().startswith(NAME_PREFIX):
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a single discovered device."""
        assert self._discovery is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery.name or self._discovery.address, data={}
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={
                "name": self._discovery.name or self._discovery.address,
                "address": self._discovery.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual pick from currently-visible FG* devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            info = self._discovered[address]
            return self.async_create_entry(title=info.name or address, data={})

        current = self._async_current_ids()
        for info in async_discovered_service_info(self.hass, connectable=True):
            if info.address in current or info.address in self._discovered:
                continue
            if _is_fog_machine(info):
                self._discovered[info.address] = info

        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{info.name or 'FG device'} ({address})"
                            for address, info in self._discovered.items()
                        }
                    )
                }
            ),
        )
