# Home Assistant integration plan

Purpose: design for the local BLE HA integration for FG53850-class fog machines.
Status: **Phase 1 built** — `custom_components/fogmachine_bt/` exists; protocol
lib has 12 passing unit tests and all modules import against HA 2026.2.3. Not
yet run against a live device. Phase 2 (scheduling) still design-only.

## Implementation status (2026-08-24)

Built: framework-free protocol lib (`fogmachine/protocol.py`), BLE client
(`fogmachine/client.py`) that does **connect → notify → `EE0c0.` handshake →
query**, a `DataUpdateCoordinator`, config flow (BT discovery + manual), and
**power switch + running-time/mode sensors**. The connect-handshake and
first-query clock-sync are implemented (client `_ensure_connected` /
`async_sync_clock`). Validation: `uv run pytest` (protocol), `tests/_import_check.py`
(HA API surface).

## Goal

A HACS-installable custom integration `fogmachine_bt` that controls one or more
FG-series fog/misting machines **locally over BLE**, using HA's Bluetooth stack
and ESPHome BLE proxies. No cloud. Automatable (start/stop, schedules).

## Why a new integration (not moogo)

`../moogo` is a **cloud** integration (`api.moogo.com`) for a different product.
This device speaks a **local BLE** protocol ([ble-protocol](ble-protocol.md))
and has no cloud. Entirely separate codebase.

## HA building blocks

- Domain: `bluetooth` (proxy-aware). Depend on `bluetooth` + `bluetooth_adapters`.
- Connections via `bleak` + **`bleak-retry-connector`** + `habluetooth`
  (`async_ble_device_from_address`, `establish_connection`) so it works
  transparently over ESPHome proxies.
- Config flow: **Bluetooth discovery** + manual add.

### Discovery matcher (`manifest.json`)

```json
"bluetooth": [
  { "service_uuid": "0000ffe0-0000-1000-8000-00805f9b34fb",
    "local_name": "FG*" }
]
```

`FFE0` alone is too generic (all HM-10 clones) — pair it with the `FG` name
prefix. See [device-fg53850](device-fg53850.md). unique_id = BLE MAC.

## Architecture

```
custom_components/fogmachine_bt/
├── manifest.json          # bluetooth matcher, deps: bleak-retry-connector
├── __init__.py            # setup entry, create coordinator
├── config_flow.py         # bluetooth discovery + manual
├── coordinator.py         # connect, query-all poll, parse, reconnect
├── fogmachine/            # pure-python protocol lib (no HA imports)
│   ├── protocol.py        # frame build/parse (EE…. , inverted bools)
│   └── client.py          # BleakClient wrapper: connect, notify, command
├── switch.py              # power (cmd 1)
├── sensor.py              # running time (query sub 0); RSSI/last-seen
├── number.py / select.py  # (phase 2) work/pause secs, mode, schedule windows
└── strings.json / translations
```

Keep `fogmachine/` framework-free so it can be unit-tested and reused (mirrors
the app's clean `cmd/` layering).

## Entities

**Phase 1 (MVP)**
- `switch.fogmachine_power` — write `EE0100.`/`EE0101.` (remember inverted).
- `sensor.fogmachine_running_time` — parse query sub `0` (HHMMSS → duration).
- `sensor.fogmachine_signal` — proxy RSSI (diagnostic) + connectivity/last-seen.

**Phase 2 (scheduling)**
- `select.fogmachine_mode` — AlwaysSpray / Nimble / AdvancedSet (cmd `2`).
- `number` work-seconds / pause-seconds for the active freq entry (cmd `7`).
- time/weekday schedule editors (cmds `6`/`3`); `switch` for time/freq-
  customizable toggles (cmds `4`/`5`).
- Button to push HA clock to the device (`+` datetime sync).

## Connection strategy

Given marginal RF ([ha-proxy-coverage](ha-proxy-coverage.md)):

- **Connect-on-demand** for commands, plus a periodic **query-all poll** (e.g.
  30–60 s) while a connection can be held; fall back to on-demand if it drops.
- Wrap every op in `bleak-retry-connector` with generous retries.
- Reassemble notifications until the expected `.`-terminator count
  ([ble-transport](ble-transport.md)); enforce a per-command timeout.
- Surface availability from last successful query, not from mere advert presence.
- Strongly recommend a closer proxy before relying on automations.

## Open items to resolve with a live device

1. Confirm CCCD (`0x2902`) notify enable works via `start_notify` over the proxy.
2. Capture a **real** query-all response to nail exact sub-block framing/widths
   (the app's test stub is inconsistent — see [ble-protocol](ble-protocol.md)).
3. Confirm power/echo responses and the first-query datetime-sync behaviour.
4. Verify the BLE MAC is stable across power cycles (unique_id safety).
5. Confirm the second unit's advertised name matches `FG*`.

A safe first step is a **read-only live probe** (connect via a Bluetooth proxy,
`start_notify` FFE1, send `EE000.` query-all, log raw bytes) before writing any
control code.
