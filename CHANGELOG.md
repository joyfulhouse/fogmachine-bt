# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.7] - 2026-08-25

### Added

- **Diagnostics** (Download diagnostics from the device page). Includes a full
  live BLE dump: every GATT service/characteristic, the value of every readable
  characteristic (hex + ascii), and the raw query-all response — useful for
  discovering any device data the OEM app never surfaces (e.g. a water /
  low-water status).

## [0.1.6] - 2026-08-25

### Fixed

- **Running-time sensor now displays in hours.** Uses the canonical duration unit
  (seconds) with `suggested_unit_of_measurement=hours` so Home Assistant converts
  and labels it correctly (0.1.5's hours-native approach left a value/unit
  mismatch on the `DURATION` device class, whose base unit is seconds).

## [0.1.5] - 2026-08-25

### Fixed

- **Power switch no longer bounces.** Turning the switch off (or on) could flip
  back ~12 s later: the post-command re-query, over a weak link, sometimes
  returned the device's stale pre-change state. The command is now applied
  **optimistically** (the device acknowledges it with a success code) and the
  racy immediate read-back is removed; the regular poll reconciles state.
- **Running-time sensor reports hours** instead of seconds (the device reports
  cumulative running time as `HH:MM:SS`).

### Added

- Brand assets (`custom_components/fogmachine_bt/brand/{icon,logo}.png` + hDPI
  `@2x` variants, SVG sources under `brand/`) so HACS renders an icon and passes
  brand validation without the `ignore: brands` workaround.

### Changed

- Rewrote `README.md` to the standard JoyfulHouse integration layout (badges,
  features, install, entities, automations, troubleshooting).
- Scrubbed environment-specific network details (proxy names, host/VLAN
  addresses, token paths) from the wiki and helper scripts; the wiki now
  documents the device/protocol and the integration's design generically.

## [0.1.4] - 2026-08-25

### Changed

- **Optimised for weak, single-proxy links** (no closer proxy is deployable).
  Root cause found live: the device allows only one BLE central and **stops
  advertising while connected**, so a persistently-held GATT link hid FG53850
  from every proxy and blocked reconnection once the marginal link dropped.
  - The client now **connects per poll and disconnects immediately**
    (`disconnect_after=True`), so the device keeps advertising and stays
    discoverable/reconnectable between polls.
  - Base poll interval raised to 180 s; the coordinator applies **exponential
    backoff** (up to 30 min) while the device is unreachable, and resets on the
    next success.
  - Entities **hold their last-known state** through up to 4 consecutive poll
    failures instead of flapping to `unavailable` on an intermittent link.

## [0.1.3] - 2026-08-24

### Fixed

- Live-device fix (supersedes 0.1.2, which shipped unformatted): the FG53850's
  `FFE1` characteristic is **write-without-response only**; writing with response returned GATT error 3 ("write not
  permitted") and left the entry in `setup_retry`. The client now selects the
  write type from the characteristic's advertised properties (prefers
  write-without-response). First confirmed live connection via an ESPHome proxy.

## [0.1.1] - 2026-08-24

### Fixed

- **Critical:** the Bluetooth discovery matcher used `local_name: "FG*"`, which
  Home Assistant rejects (local-name matchers may not have a wildcard in the
  first 3 characters). This failed the whole `bluetooth` component setup and
  cascaded to `esphome`/`bluetooth_adapters`. The matcher now keys on the
  `FFE0` service UUID only, and the `FG` name filter moved into the config flow
  (`async_step_bluetooth` aborts non-`FG` devices).

## [0.1.0] - 2026-08-24

### Added

- Initial release: local **Bluetooth** control of FG-series fog / patio-misting
  machines (OEM app `com.spw.mistingapp2`), with no cloud dependency.
- Reverse-engineered the HM-10 (`FFE0`/`FFE1`) plain-ASCII protocol
  (`EE <phase> <cmd> <code> <payload> .`, inverted on/off, connect handshake
  `EE0c0.`, clock-sync first query). Framework-free protocol library with unit
  tests.
- Home Assistant integration: Bluetooth-discovery config flow, power **switch**,
  running-time + mode **sensors**, all over HA's Bluetooth proxies via
  `bleak-retry-connector`.
- Knowledge base under `wiki/` (protocol, transport, HA proxy coverage,
  integration plan) plus an independent Codex protocol cross-check.

### Known limitations

- Not yet validated against a live device; the first Home Assistant connection
  is the live test.
- Scheduling entities (time windows, work/pause frequency cycles, weekdays) are
  supported in the protocol library but not yet surfaced as HA entities.
