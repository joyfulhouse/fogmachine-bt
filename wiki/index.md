# fogmachine-bt — wiki index

Reverse-engineering the **FG53850** BLE fog / patio-misting machine (controlled
by the Android app `com.spw.mistingapp2`, "SPW Misting") to build a **local
Home Assistant Bluetooth integration** — no cloud, controllable via HA's
ESPHome BLE proxies.

> Read [SCHEMA](SCHEMA.md) first if you're going to edit the wiki.

## Effort status (2026-08-24)

| Workstream | State |
|---|---|
| APK acquired + decompiled (jadx + apktool) | ✅ done — see [sources](sources.md) |
| BLE protocol reverse-engineered from source | ✅ done — see [ble-protocol](ble-protocol.md) |
| Independent Codex protocol analysis | ✅ done + cross-checked — `sources/codex-analysis/PROTOCOL_CODEX.md` (caught the `EE0c0.` connect-frame nuance) |
| Reachable over an HA Bluetooth proxy | ✅ yes (often marginal RSSI) — see [ha-proxy-coverage](ha-proxy-coverage.md) |
| HA custom integration (protocol + switch/sensor) | ✅ built; 12 unit tests + HA-import check pass |
| Live validation on real device | ✅ done — connect → query decoded (power/mode/running-time). Live fixes folded in: FFE0-only matcher, FFE1 write-without-response, connect-per-poll for weak links. |

## The 30-second summary

- The machine is a cheap Chinese BLE device (hardware ≈ thepatiomistingsystem.com)
  using an **HM-10-class serial-UART module**: GATT service **`FFE0`**,
  characteristic **`FFE1`** (write + notify). See [ble-transport](ble-transport.md).
- The wire protocol is a **plain-ASCII, checksum-less** frame:
  `EE <phase> <cmdId> <code> <payload> .` — trivial to reimplement. Full spec in
  [ble-protocol](ble-protocol.md). **On/off is inverted: `0`=ON, `1`=OFF.**
- No pairing, no auth, no encryption. After GATT connect + notifications, the
  app sends a trivial `EE0c0.` handshake (reply `EE1c0.`), then a first query
  that also syncs the clock. No secret/login anywhere.
- The device is **connectable over an HA Bluetooth proxy**, but RSSI is often
  weak and it **stops advertising while connected** — so the integration connects
  per-poll and disconnects immediately. Details in
  [ha-proxy-coverage](ha-proxy-coverage.md).
- Device state exposed over BLE: **power, cumulative running time, schedule
  windows, work/pause "frequency" cycles, weekdays, customization mode, clock.**
  There is **no** water/temperature/humidity over BLE (those were Moogo-cloud
  concepts; unrelated to this device).

## Pages

- [device-fg53850](device-fg53850.md) — the physical machine + its BLE identity
- [ble-transport](ble-transport.md) — GATT / connection / chunking / notifications
- [ble-protocol](ble-protocol.md) — **the command spec** (authoritative)
- [ha-proxy-coverage](ha-proxy-coverage.md) — proxy scan results + recommendations
- [integration-plan](integration-plan.md) — HA integration architecture & entities (**Phase 1 built**)
- [sources](sources.md) — raw evidence registry

## The integration

Code lives in [`../custom_components/fogmachine_bt/`](../custom_components/fogmachine_bt/).
Protocol lib is framework-free + unit-tested (`uv run pytest`). See the
[README](../README.md) for install/dev. First HA connection is the live test.
