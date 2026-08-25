# Device: FG53850 fog / misting machine

Purpose: what the physical device is and how it presents on BLE.
Status: **partial** (advertisement verified live; GATT internals verified from app source, not yet from a live connection).

## Identity

- **Product**: outdoor fog / patio-misting machine, sourced from China. Same
  hardware as the units sold at <https://thepatiomistingsystem.com>.
- **Companion app**: `com.spw.mistingapp2` ("SPW Misting"), Android, v2.2.8
  (versionCode 23, min SDK 18, target SDK 35). This is the OEM app; it talks to
  the machine **directly over BLE** (not via any cloud). ⚠️ Not related to the
  Moogo cloud integration in `../moogo` — different product/vendor.
- **Units**: one powered on now; a **second unit** is planned. Both are expected
  to advertise with an `FG#####` name — confirm the second unit's exact name.

## BLE advertisement (verified live 2026-08-24)

Observed via HA `bluetooth/subscribe_advertisements` (see
[ha-proxy-coverage](ha-proxy-coverage.md); raw dump
`sources/ha-scan/ble_devices_dump_60s.json`):

| Field | Value |
|---|---|
| Advertised name | `FG53850` |
| BLE address | `02:11:23:34:5A:17` (locally-administered — typical of clone modules) |
| Advertised service UUID | `0000ffe0-0000-1000-8000-00805f9b34fb` |
| Connectable | yes |
| Manufacturer data | none observed |

The `FFE0` service + a `FF##` MAC + the `FG` name are the signature of an
**HM-10 / JDY / CC254x-class BLE serial module**. Details of the GATT profile
the app drives are on [ble-transport](ble-transport.md).

## Notes for integration

- The app never filters by name or UUID when scanning — it lists every LE
  device and the user picks `FG53850` by name (`FunctionListActivity.onLeScan`).
  So `FG53850` is just this unit's factory name, not a hard-coded constant.
- For HA discovery, match on **service UUID `0000ffe0` + name prefix `FG`** (FFE0
  alone is too generic — many unrelated HM-10 gadgets use it). See
  [integration-plan](integration-plan.md).
- The BLE address is static here (starts `02:` = locally administered but not
  resolvable-random); usable as a stable unique_id. Confirm it doesn't rotate
  across power cycles during live testing.
