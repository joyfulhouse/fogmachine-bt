"""Import every component module against a real Home Assistant install.

Catches HA-version API mismatches (wrong import paths, renamed symbols) without
needing the full HA test harness. Run via:
    uv run --with homeassistant --with habluetooth --with bleak-retry-connector \
        python tests/_import_smoke.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import homeassistant.const as ha_const  # noqa: E402

print("homeassistant", ha_const.__version__)

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

import importlib  # noqa: E402

failed = 0
for m in MODULES:
    try:
        importlib.import_module(m)
        print("OK  ", m)
    except Exception as err:  # noqa: BLE001
        failed += 1
        print("FAIL", m, "->", type(err).__name__, err)

sys.exit(1 if failed else 0)
