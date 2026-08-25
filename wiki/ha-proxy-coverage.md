# HA Bluetooth proxy coverage for FG53850

Purpose: can Home Assistant's BLE proxies see/reach the fog machine, and which one.
Status: **verified live** 2026-08-24 via `bluetooth/subscribe_advertisements`.
Scanner script: `sources/ha-scan/ble_scan.py`. Raw dumps:
`sources/ha-scan/ble_devices_dump.json` (28 s), `…_60s.json` (60 s).

## Result

FG53850 (`02:11:23:34:5A:17`) **is visible to the HA BLE mesh, but only just.**

| Scan | Proxies that heard FG53850 | Best RSSI |
|---|---|---|
| 28 s | `aiosense-adu-main` only | −88 dBm |
| 60 s | `aiosense-adu-main` only | −78 dBm (oscillates −78…−88) |

- It advertises **connectable** with service `FFE0`, so a proxy-mediated GATT
  connection is possible — and **confirmed working 2026-08-24**: HA connected
  via `adu-main`, discovered FFE0/FFE1, and completed a query (power/mode/
  runtime decoded). So −78…−88 dBm via the single proxy *is* usable for control,
  though a closer proxy would improve reliability.
- **−78…−88 dBm from a single proxy is marginal for a sustained connection.**
  Advertisements are heard at weaker RSSI than a reliable connection needs
  (rule of thumb: want ≳ −80 dBm, ideally −70s, for dependable GATT over a
  proxy). Expect occasional connect/notify failures at this level → the client
  must use retry/reconnect ([integration-plan](integration-plan.md)).

## About `aiosense-adu-bedroom` (Bryan's question)

`adu-bedroom`'s proxy **is enabled and healthy** — it just doesn't hear FG53850.

- The HA `bluetooth` config entry lists it as
  `aiosense-adu-bedroom (70:04:1D:22:77:D8)`, but ESP32 advertises its **BLE**
  MAC as base+2 = `70:04:1D:22:77:DA`. Under that address it appears in the dump
  having heard 6 other devices at best −36 dBm → **its proxy works fine.**
- Over both the 28 s and 60 s scans it **never** heard FG53850. So despite being
  "one wall closer" by intuition, its RF path to the machine is actually worse
  (wall material / angle / the machine's antenna orientation toward adu-main).
- All 15 `aiosense-*` proxies are active BLE scanners (each appears as a source
  for many devices). Config MAC vs BLE-source MAC differ by +2 for most units
  (adu-main is the exception where they coincide).

## The device stops advertising while connected (critical)

Confirmed live 2026-08-25: FG53850 is a single-connection HM-10 module that
**stops broadcasting advertisements whenever a BLE central is connected**. Proof:
with the integration enabled (holding a persistent GATT link via `adu-main`),
FG53850 vanished from a 75 s all-proxy scan; the instant the config entry was
disabled it reappeared within 15 s (`02:11:23:34:5A:17`, connectable, −90 dBm).

Two consequences on a marginal single-proxy link:

- A **persistently-held connection hides the device from every proxy**, so if the
  weak link drops, HA can no longer see an advertisement to reconnect — it's
  stuck `unavailable` until something releases the slot.
- Continuous connection also monopolises the one marginal RF path.

**Integration fix (v0.1.4, since a closer proxy is not deployable):** connect
**per poll and disconnect immediately** (`disconnect_after=True`), so the device
spends almost all its time advertising and stays reconnectable; poll on a long
base interval (180 s) with **exponential backoff** (to 30 min) while unreachable;
and **hold last-known state** through a few failures rather than flapping. See
`const.py` and [integration-plan](integration-plan.md).

## Recommendation

1. **It works today** through `aiosense-adu-main` at −78…−90 dBm — marginal, so
   expect intermittent polls (the v0.1.4 backoff + hold-last-state design is
   built for exactly this).
2. A closer proxy is **not deployable** here (outdoors, nowhere to mount one), so
   optimise the software for the weak link rather than chasing RSSI — done in
   v0.1.4. If a mount ever becomes possible, an ESP32 proxy near the ADU exterior
   would move RSSI into the −60s and make GATT solid.
3. Re-run `sources/ha-scan/ble_scan.py` (set `SCAN_SECONDS`, `FILTER=FG`) to check
   coverage. **Note:** disable/stop the integration first, or its held connection
   will suppress the very advertisement you're scanning for.
4. With two units, verify **each** is heard by *some* proxy; HA picks the best
   scanner per device automatically.

## Live GATT probe attempt (2026-08-24) — blocked by VLAN, not by the device

Tried a read-only proxied GATT probe from the laptop via `aioesphomeapi`
(`sources/ha-scan/ble_probe.py`): connect to adu-main's ESPHome native API →
proxy-connect FG53850 → read query-all `EE000.`.

**Blocked at the network layer:** adu-main's API (`10.100.12.244:6053`, IoT VLAN)
is **not routable** from the laptop *or* from any homelab server
(172.16.1.x) — all return unreachable. Only Home Assistant (`10.100.128.3`, on
the 10.100 net) can reach the ESPHome proxies' API port. This is the intended,
secure topology (BLE-proxy API access restricted to HA) — do **not** punch a
UniFi hole for it.

**Consequence:** the live GATT validation must run **where HA runs**, i.e.
through the integration itself once installed in HA (HA has the proxy path).
The `ble_probe.py` script is retained and works — it just needs to run from a
host on the 10.100 network (e.g. an HA add-on / a box on the IoT VLAN). The
laptop-side path we *can* use is the advertisement scan below (via HA's
websocket on `:8123`, which is reachable).

## How to reproduce the scan

```bash
export HA_TOKEN=$(grep '^HA_PROD_LONG_LIVED_TOKEN=' \
  ~/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor/.env | cut -d= -f2-)
export FILTER=FG SCAN_SECONDS=60
uv run sources/ha-scan/ble_scan.py
```

The script authenticates to `ws://hass.joyful.house:8123/api/websocket`,
subscribes to advertisements, and prints every proxy that hears the filter
target with per-proxy RSSI (strongest first).
