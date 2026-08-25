# Sources registry (raw, immutable evidence)

Purpose: index of the raw inputs the wiki is distilled from. Never edit files
under `/sources/`; add new evidence and record it here. See [SCHEMA](SCHEMA.md).

| Source | Path | What it provides |
|---|---|---|
| APK (SPW Misting v2.2.8) | `sources/apk/com.spw.mistingapp2.apk` | The app binary. 6.4 MB, single dex, no native libs. Pulled via `apkeep` (apk-pure) 2026-08-24. |
| jadx decompile | `sources/decompiled/jadx/` | 940 Java files; app code under `sources/com/spw/mistingapp` (43 files). Primary RE source. |
| apktool decode | `sources/decompiled/apktool/` | `AndroidManifest.xml`, `apktool.yml`, resources, smali. BLE perms; versionCode 23, minSdk 18, targetSdk 35. |
| BLE scan script | `sources/ha-scan/ble_scan.py` | HA websocket `bluetooth/subscribe_advertisements` scanner (per-proxy RSSI). |
| BLE scan dumps | `sources/ha-scan/ble_devices_dump.json`, `…_60s.json` | Live advertisement captures 2026-08-24 proving proxy visibility. |
| Codex analysis | `sources/codex-analysis/PROTOCOL_CODEX.md` | Independent second-opinion protocol doc (parallel RE cross-check). |

## Key app classes (jadx) — quick map

Under `sources/decompiled/jadx/sources/com/spw/mistingapp/`:

- `MistingBLEServiceExecutor.java` — BLE transport: GATT, connect, chunked
  writes, notify reassembly → [ble-transport](ble-transport.md).
- `cmd/MistingCmdConstants.java` — headers, cmd ids, ranges, inverted booleans.
- `cmd/AbstractMistingDevCmd.java` — `packRequest()`/`unpackResponse()` framing.
- `cmd/MistingDevCmdDataFormat.java` — authoritative payload widths/encodings.
- `cmd/imp/MistingDev*Cmd.java` — one class per command (power, query, freq,
  time, weekday, mode, batch, sync) → [ble-protocol](ble-protocol.md).
- `cmd/imp/MistingDevCmdFactory.java` — command dispatch + `getTestResponse`
  example frames.
- `MistingDevInfo.java` — device state model (power, running time, schedules).
- `FunctionListActivity.java` — unfiltered LE scan + device picker.

## Provenance / notes

- APK from a public mirror (apk-pure) — matches the observed device app name
  ("sp-android" help assets, package `com.spw.mistingapp2`). If exact-version
  fidelity matters later, re-pull with `adb pull` from a device.
- The decompiled output and the APK are large; they are git-ignored (see repo
  `.gitignore`). The wiki + scan dumps + Codex analysis are the durable record.
