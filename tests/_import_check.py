"""Validate the component's Home Assistant API usage against an installed HA.

HA's `homeassistant.components.bluetooth` blocks at import on macOS (adapter/dbus
enumeration), so we stub *only that one module* with the exact names this
integration imports from it. Every other HA symbol our code uses is resolved
against the real installed Home Assistant, so a renamed/removed API elsewhere
still fails loudly here.
"""

import importlib
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import homeassistant.const as ha_const

print("homeassistant", ha_const.__version__)

# --- stub homeassistant.components.bluetooth (names our code imports) ---
bt = types.ModuleType("homeassistant.components.bluetooth")


class BluetoothServiceInfoBleak:  # noqa: D401 - stub
    """Stub."""


def async_ble_device_from_address(*_a, **_k):  # noqa: D401 - stub
    return None


def async_discovered_service_info(*_a, **_k):  # noqa: D401 - stub
    return []


bt.BluetoothServiceInfoBleak = BluetoothServiceInfoBleak
bt.async_ble_device_from_address = async_ble_device_from_address
bt.async_discovered_service_info = async_discovered_service_info
sys.modules["homeassistant.components.bluetooth"] = bt

MODULES = [
    "custom_components.fogmachine_bt.const",
    "custom_components.fogmachine_bt.fogmachine.protocol",
    "custom_components.fogmachine_bt.fogmachine.client",
    "custom_components.fogmachine_bt.coordinator",
    "custom_components.fogmachine_bt.entity",
    "custom_components.fogmachine_bt.config_flow",
    "custom_components.fogmachine_bt.switch",
    "custom_components.fogmachine_bt.sensor",
    "custom_components.fogmachine_bt",
]

failed = 0
for m in MODULES:
    try:
        importlib.import_module(m)
        print("OK  ", m)
    except Exception as err:  # noqa: BLE001
        failed += 1
        print("FAIL", m, "->", type(err).__name__, err)

print("RESULT", "PASS" if not failed else f"{failed} FAILED")
sys.exit(1 if failed else 0)
