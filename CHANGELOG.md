# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
