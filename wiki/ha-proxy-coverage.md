# Connectivity: Bluetooth proxies & weak links

Purpose: how FG-series machines behave on a Bluetooth link and how the
integration is designed to stay reliable over a marginal one.
Status: **verified live** — device behaviour confirmed against real hardware.
Scanner: `sources/ha-scan/ble_scan.py` (reports which proxy hears the device and
at what RSSI).

## The machine is reachable over HA's Bluetooth mesh

FG-series machines advertise a **connectable** GATT peripheral with service
`FFE0` ([ble-transport](ble-transport.md)), so any Home Assistant Bluetooth path
— a local adapter or an **ESPHome BLE proxy** — can connect and control them.
Because these are low-power modules with small antennas, RSSI is often weak
(commonly around −80 dBm or worse) when the nearest proxy is not close.

## Critical: the device stops advertising while connected

These are **single-connection** HM-10-class modules: while a BLE central is
connected, the device **stops broadcasting advertisements entirely**. On a
marginal link this has two important consequences:

- A **persistently-held GATT connection hides the device from every proxy.** If
  the weak link then drops, Home Assistant can no longer see an advertisement to
  reconnect, and the entity is stuck `unavailable`.
- Holding the connection also monopolises the one marginal RF path.

This is the opposite of the usual HA-Bluetooth advice ("keep the connection
open"), and it drives the integration's polling design below.

## Integration design for weak links

Implemented in `fogmachine/client.py` + `coordinator.py` (see `const.py` for the
tunables):

- **Connect per poll, disconnect immediately** (`disconnect_after=True`). The
  device spends almost all its time advertising, so it stays discoverable and
  reconnectable between polls.
- **Long base poll interval** (state changes slowly) with **exponential backoff**
  while the device is unreachable, reset on the next success — avoids hammering a
  bad link.
- **Hold last-known state** through a few consecutive failures instead of
  flapping entities to `unavailable` on an intermittent link.

This makes a weak link *behave well*; it cannot make a very weak link *fast or
certain*. Expect polls to succeed intermittently at low RSSI, and time-based
sensors (e.g. running time) to update on a coarser cadence.

## Improving reliability

1. **Put a Bluetooth proxy near the machine.** A proxy with line-of-sight and
   good RSSI (roughly −70 dBm or better) makes GATT connections solid. This is
   the single most effective improvement, and worth doing before adding more
   units. Where a closer proxy is not physically possible (e.g. an outdoor
   machine with nowhere to mount one), the weak-link design above is what keeps
   it usable.
2. **Check coverage with the scanner.** Run `sources/ha-scan/ble_scan.py`
   (`FILTER=FG`, `SCAN_SECONDS=60`) to see which proxy hears each machine and at
   what RSSI. **Stop/disable the integration first** — otherwise its held
   connection suppresses the advertisement you're trying to observe.
3. **With multiple units,** confirm each is heard by *some* proxy; Home Assistant
   automatically picks the best scanner per device.

## Live GATT validation

A laptop generally **cannot** reach an ESPHome proxy's native API (port 6053) —
it's typically firewalled to the Home Assistant host only. So proxied-GATT
validation should run **where Home Assistant runs** (which is exactly where the
integration itself runs). `sources/ha-scan/ble_probe.py` performs a read-only
connect + query-all and logs the raw response; point it at a reachable proxy via
the `ESPHOME_HOST` / `ESPHOME_NOISE_PSK` / `TARGET_MAC` env vars.

## Reproduce the advertisement scan

```bash
export HA_TOKEN=<a Home Assistant long-lived access token>
export HA_WS_URL=ws://<your-ha-host>:8123/api/websocket   # optional
export FILTER=FG SCAN_SECONDS=60
uv run sources/ha-scan/ble_scan.py
```

The script subscribes to `bluetooth/subscribe_advertisements` and prints every
proxy that hears the filter target, with per-proxy RSSI (strongest first).
