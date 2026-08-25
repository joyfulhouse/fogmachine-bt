# What data is available over Bluetooth

Purpose: the complete inventory of what an FG-series fog machine exposes over
BLE, and specifically whether the device's **"Water Loss"** indicator is
obtainable.
Status: **verified live** on a real device (full GATT enumeration + read of every
readable characteristic + raw query-all capture, via the integration's
diagnostics dump). Cross-checked against the decompiled app.

## TL;DR — Water Loss is NOT available over Bluetooth

The device's on-unit **"Water Loss" / low-water indicator is device-local only.**
It is not exposed on any GATT characteristic, not returned in the query-all
response, and not present anywhere in the OEM app (which also cannot show it).
There is no way to read water status, and therefore no way to automate on it,
over the current firmware's BLE interface.

## Complete GATT table (live)

Only three services exist; nothing beyond the standard SIG services and the
HM-10 serial pipe:

| Service | Characteristic | Props | Meaning |
|---|---|---|---|
| `1800` Generic Access | `2A00` Device Name | read/write | `"FG53850"` |
| | `2A01` Appearance | read/write | `0x0000` (unknown) |
| | `2A02` Peripheral Privacy | read | `0x00` |
| | `2A04` Preferred Conn Params | read | conn interval/latency/timeout |
| `1801` Generic Attribute | `2A05` Service Changed | read/indicate | `0100ffff` |
| `FFE0` (vendor) | `FFE1` | read/write-without-response/notify | the EE serial protocol |

Notably **absent**: Device Information (`180A`), Battery (`180F`), and any custom
status/sensor characteristic. Reading `FFE1` directly returns all-zeros — it
carries data only via the EE request/response protocol
([ble-protocol](ble-protocol.md)). The BLE advertisement carries only the `FFE0`
service UUID (no manufacturer/service data).

## Everything the query-all returns (live capture, decoded)

Raw response:

```
EE1000000006,EE10010,EE10020,EE10030000000,EE10040,EE10050,
EE100600000002359,EE100601100000001,EE100602100000001,EE100603100000001,
EE10070000000300005,.
```

| Block | Sub | Decoded |
|---|---|---|
| `EE1000000006` | 0 | running time `00:00:06` |
| `EE10010` | 1 | power = on |
| `EE10020` | 2 | mode = always-spray |
| `EE10030000000` | 3 | weekdays = all 7 enabled |
| `EE10040` | 4 | time-customizable = on |
| `EE10050` | 5 | freq-customizable = on |
| `EE100600000002359` | 6 | time window 0: enabled, 00:00–23:59 |
| `EE1006011000000 01` ×3 | 6 | time windows 1–3: disabled/empty |
| `EE10070000000300005` | 7 | freq cycle 0: enabled, work 3 s / pause 5 s |

Every byte is accounted for by the known protocol — **no unknown sub-blocks, no
trailing data**, and the query parser would reject an unknown sub-id, so the
device cannot be silently withholding a water field here.

## So the full set of automatable BLE data is

- **power** (on/off) — controllable + readable
- **running time** (cumulative HH:MM:SS)
- **customization mode** (always / nimble / advanced)
- **weekday schedule** (7 enable flags)
- **time windows** (up to 4 in nimble / 10 in advanced): from/to, enabled
- **spray "frequency" cycles** (work seconds / pause seconds, enabled)
- **device clock** (write-only sync)

There is **no** water level, low-water/Water-Loss, error/fault, temperature,
humidity, battery, or liquid/concentrate data in the protocol.

## If Water Loss is needed anyway

It is not reachable over this device's BLE. Options, in rough order of effort:

1. **Confirm on your unit** by downloading the integration's diagnostics
   (Settings → Devices & Services → FogMachine BT → Download diagnostics) — it
   re-runs this exact live dump. If a future firmware adds a characteristic, it
   will appear there.
2. **Physical sensing**: a water-level/float or flow sensor on the reservoir wired
   to an ESP (ESPHome) exposes low-water to HA directly, independent of the
   fogger's BLE.
3. Watch upstream: if the vendor ships a firmware/app update that surfaces water
   status, re-capture the GATT table and query response.
