# FogMachine BT — Home Assistant integration

Local **Bluetooth** control of **FG-series fog / patio-misting machines** (the
cheap China-sourced units driven by the *SPW Misting* app,
`com.spw.mistingapp2`). No cloud — control happens directly over BLE through
Home Assistant's Bluetooth adapters / ESPHome BLE proxies.

> Reverse-engineered from the OEM app. Protocol, transport, and RF-coverage
> notes live in [`wiki/`](wiki/index.md) (an LLM-maintained knowledge base).
> Start at [`wiki/index.md`](wiki/index.md).

## Status

**v0.1 (early).** The wire protocol is reverse-engineered and unit-tested; the
integration installs and exposes power + running time. It has **not yet been
validated against a live device** (the machine is only reachable from inside HA
— see [`wiki/ha-proxy-coverage.md`](wiki/ha-proxy-coverage.md)). Treat the first
HA connection as the live test and watch debug logs.

## Features (Phase 1)

- **Switch** — power (start/stop misting).
- **Sensor** — cumulative running time; diagnostic mode sensor.
- Bluetooth **auto-discovery** (matches service `FFE0` + name `FG*`) and manual add.

Planned (Phase 2): schedule windows, work/pause "frequency" cycles, weekdays,
customization mode, clock-sync button. Protocol support for these already exists
in `fogmachine/protocol.py`.

## Requirements

- A **connectable** Bluetooth path to the machine: a local adapter or an
  **ESPHome BLE proxy** (`active`) in range. RF from these units is weak — put a
  proxy near the machine. See [`wiki/ha-proxy-coverage.md`](wiki/ha-proxy-coverage.md).

## Install

1. Copy `custom_components/fogmachine_bt/` into your HA `config/custom_components/`
   (or add this repo to HACS as a custom repository).
2. Restart Home Assistant.
3. The machine should be auto-discovered (**Settings → Devices & Services**), or
   add **FogMachine BT** manually.

## How it works

The device is an HM-10-class BLE serial module (service `FFE0`, characteristic
`FFE1`). Commands are plain-ASCII frames `EE <phase> <cmd> <code> <payload> .`
with **no checksum** and **inverted on/off** (`0`=ON). Full spec:
[`wiki/ble-protocol.md`](wiki/ble-protocol.md).

## Development

```bash
uv sync
uv run pytest            # protocol unit tests (no device needed)
uv run ruff check .
```

The protocol layer (`custom_components/fogmachine_bt/fogmachine/`) is
Home-Assistant-agnostic and fully unit-tested.

## License

MIT.
