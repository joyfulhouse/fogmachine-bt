# FogMachine BT

A Home Assistant custom integration for **FG-series fog / patio-misting
machines** (the China-sourced units driven by the *SPW Misting* app,
`com.spw.mistingapp2`), providing **local Bluetooth** control and monitoring with
**no cloud dependency**.

[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)
[![HACS][hacs-shield]][hacs]
[![CI][ci-shield]][ci]
[![Project Maintenance][maintenance-shield]][maintenance]
[![GitHub Sponsors][sponsors-shield]][sponsors]
[![Ko-fi][kofi-shield]][kofi]

## What It Does

This integration connects Home Assistant directly to FG-series fog machines over
**Bluetooth Low Energy** — through a local adapter or an ESPHome BLE proxy — with
no cloud, account, or internet dependency. The wire protocol was reverse-
engineered from the OEM Android app and is documented in
[`wiki/`](wiki/index.md); the protocol layer is fully unit-tested.

> Not affiliated with the *SPW Misting* app or its vendor. Unrelated to the
> cloud-connected Moogo product.

## Features

- Start/stop misting via a power **switch** entity
- Cumulative running-time **sensor** and a diagnostic operating-mode sensor
- Bluetooth **auto-discovery** (service `FFE0` + `FG` name) and manual add
- Works over Home Assistant's Bluetooth proxies (ESPHome), not just a local radio
- **Weak-link tuned:** connects per-poll and disconnects immediately (these
  modules stop advertising while connected), with exponential backoff and
  hold-last-state so entities don't flap on a marginal signal

## Prerequisites

- Home Assistant 2024.8.0 or newer
- [HACS](https://hacs.xyz) installed (recommended for installation)
- A **connectable** Bluetooth path to the machine: a local adapter or an active
  ESPHome BLE proxy within range (see
  [`wiki/ha-proxy-coverage.md`](wiki/ha-proxy-coverage.md))

## Installation

See **[INSTALL.md](INSTALL.md)** for the complete guide.

**Quick version (HACS):** add this repository as a custom repository in HACS,
install **FogMachine BT**, restart Home Assistant, then add the integration from
**Settings → Devices & Services**.

[![Open in HACS][hacs-repo-shield]][hacs-repo]

## Configuration

The machine is discovered automatically once a Bluetooth proxy hears it. No
credentials are required — control is entirely local.

### Configuration Steps

1. Go to **Settings → Devices & Services**
2. If the machine was auto-discovered, click **Configure** on the notification;
   otherwise click **Add Integration** and search for **FogMachine BT**
3. Select the `FG…` device and click **Submit**

## Supported Equipment

Any FG-series fog / patio-misting machine using the *SPW Misting* app — the
China-sourced units equivalent to the hardware sold as "patio misting systems".
Entities are created per device.

### Switches

| Entity | Description |
|---|---|
| Power | Start/stop misting |

### Sensors

| Entity | Description |
|---|---|
| Running time | Cumulative run time reported by the device |
| Mode | Operating mode (always / nimble / advanced), diagnostic |

Scheduling controls (time windows, work/pause "frequency" cycles, weekdays) are
already supported in the protocol library and are planned as entities in a
future release.

## Automation Examples

**Evening misting during mosquito hours:**

```yaml
automation:
  - alias: "Fog Machine Evening Misting"
    trigger:
      - platform: time
        at: "19:00:00"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.fg53850_power
```

**Stop misting at night:**

```yaml
automation:
  - alias: "Fog Machine Off at Night"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.fg53850_power
```

**Lovelace card:**

```yaml
type: entities
title: Fog Machine
entities:
  - entity: switch.fg53850_power
    name: Power
  - entity: sensor.fg53850_running_time
    name: Running Time
  - entity: sensor.fg53850_mode
    name: Mode
```

## Troubleshooting

**Integration not appearing / device not discovered**
- Ensure the machine is powered on and within range of a Bluetooth proxy
- Confirm a proxy actually hears it — run `sources/ha-scan/ble_scan.py`
  (`FILTER=FG SCAN_SECONDS=60`); **disable the integration first**, since its held
  connection suppresses the advertisement while scanning
- Restart Home Assistant completely after installing

**Entities show "unavailable" intermittently**
- This is expected on a weak link (RSSI around −85 dBm or worse). The integration
  backs off and holds the last state through brief dropouts; a closer Bluetooth
  proxy is the most effective fix. See
  [`wiki/ha-proxy-coverage.md`](wiki/ha-proxy-coverage.md).

**Debug logging:**

```yaml
logger:
  default: info
  logs:
    custom_components.fogmachine_bt: debug
```

## Development

The wire protocol and reverse-engineering notes live in
[`wiki/`](wiki/index.md). The protocol layer
(`custom_components/fogmachine_bt/fogmachine/`) is framework-free and unit-tested.

```bash
uv sync
uv run pytest            # protocol unit tests (no device needed)
uv run ruff check .
uv run ruff format --check .
```

## Support

- **Issues:** <https://github.com/joyfulhouse/fogmachine-bt/issues>
- **Discussions / questions:** open an issue with the `question` label.

## Support Development

If this project is useful to you, please consider supporting its development:

- [GitHub Sponsors][sponsors]
- [Ko-fi][kofi]

## License

This project is licensed under the **MIT** License — see [LICENSE](LICENSE) for
details.

## Credits

Built and maintained by [JoyfulHouse](https://github.com/joyfulhouse).

This is an unofficial integration and is not affiliated with or endorsed by the
device manufacturer or the *SPW Misting* app.

<!-- Badge links -->
[releases-shield]: https://img.shields.io/github/release/joyfulhouse/fogmachine-bt.svg?style=for-the-badge
[releases]: https://github.com/joyfulhouse/fogmachine-bt/releases
[license-shield]: https://img.shields.io/github/license/joyfulhouse/fogmachine-bt.svg?style=for-the-badge
[hacs-shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[hacs]: https://github.com/hacs/integration
[hacs-repo-shield]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-repo]: https://my.home-assistant.io/redirect/hacs_repository/?owner=joyfulhouse&repository=fogmachine-bt&category=integration
[ci-shield]: https://img.shields.io/github/actions/workflow/status/joyfulhouse/fogmachine-bt/hacs-validate.yml?style=for-the-badge&label=CI
[ci]: https://github.com/joyfulhouse/fogmachine-bt/actions
[maintenance-shield]: https://img.shields.io/badge/maintainer-%40btli-blue.svg?style=for-the-badge
[maintenance]: https://github.com/btli
[sponsors-shield]: https://img.shields.io/badge/sponsor-GitHub-EA4AAA.svg?style=for-the-badge&logo=githubsponsors&logoColor=white
[sponsors]: https://github.com/sponsors/btli
[kofi-shield]: https://img.shields.io/badge/Ko--fi-donate-FF5E5B.svg?style=for-the-badge&logo=ko-fi&logoColor=white
[kofi]: https://ko-fi.com/bryanli
