# Installing FogMachine BT

## Prerequisites

- Home Assistant 2024.8.0 or newer.
- A **connectable** Bluetooth path to the machine: a local adapter or an
  **ESPHome BLE proxy** (`active`) within range. FG-series units are weak
  transmitters — put a proxy near the machine. See
  [`wiki/ha-proxy-coverage.md`](wiki/ha-proxy-coverage.md).

## Option A — HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/joyfulhouse/fogmachine-bt` with category
   **Integration**.
3. Search for **FogMachine BT**, download it.
4. **Restart Home Assistant.**

## Option B — Manual

1. Copy `custom_components/fogmachine_bt/` into your Home Assistant
   `config/custom_components/` directory.
2. **Restart Home Assistant.**

## Add the device

After restart, the machine is auto-discovered (**Settings → Devices &
Services**) once it is heard by a Bluetooth proxy. Otherwise click **Add
Integration**, search **FogMachine BT**, and pick the `FG…` device.

## Entities

- `switch` — power (start/stop misting).
- `sensor` — running time (cumulative) and a diagnostic mode sensor.

## Troubleshooting

- **Not discovered / unavailable:** confirm a proxy hears it — run
  `sources/ha-scan/ble_scan.py` (`FILTER=FG SCAN_SECONDS=60`). RSSI weaker than
  about −85 dBm makes connections unreliable; add a closer proxy.
- **Debug logs:**

  ```yaml
  logger:
    logs:
      custom_components.fogmachine_bt: debug
  ```
