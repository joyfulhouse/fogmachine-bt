# CLAUDE.md — fogmachine-bt

Guidance for Claude Code (and humans) working in this repo.

## What this project is

Reverse-engineering the **FG53850** BLE fog / patio-misting machine (OEM Android
app `com.spw.mistingapp2`, "SPW Misting") and building a **local Home Assistant
Bluetooth integration** to automate and control it — no cloud. One unit is
online now; a second will be installed.

⚠️ **Not related to `../moogo`** — that's a cloud integration for a different
product. This device is local BLE only.

## Knowledge lives in the wiki — read it first

This project uses an **LLM-maintained wiki** (the
[karpathy "LLM Wiki"](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
pattern) for durable, cross-session memory. **Start every session at
[`wiki/index.md`](wiki/index.md)**, and read [`wiki/SCHEMA.md`](wiki/SCHEMA.md)
before editing the wiki.

- `wiki/` — distilled, cross-referenced knowledge (edit these as you learn).
- `sources/` — **raw, immutable** evidence (APK, decompiled code, scans, Codex
  output). Never edit; register new evidence in `wiki/sources.md`.
- `custom_components/fogmachine_bt/` — the HA integration (to be built).
- `docs/` — longer-form docs if needed (keep session notes out of the repo root).

**When you learn something durable, fold it into the right wiki page** (ingest),
keep fact separate from plan, cite the source class/file, and update
`wiki/index.md` status. Before ending a session, lint: fix contradictions,
untraced claims, and stale `⚠️ unverified` markers that a live test resolved.

## Fast facts (see wiki for detail + citations)

- GATT: service `FFE0`, characteristic `FFE1` (write+notify, HM-10 style).
- Wire protocol: ASCII, no checksum — `EE <phase> <cmdId> <code> <payload> .`.
  **Inverted booleans: `0`=ON/enabled, `1`=OFF/disabled.**
- No pairing/auth/encryption; "connect" is just a GATT connect + notify enable.
- Live proxy visibility: only `aiosense-adu-main` hears FG53850, ~−78…−88 dBm
  (marginal) → recommend a closer ESPHome proxy. `wiki/ha-proxy-coverage.md`.
- BLE exposes power, running time, schedule/freq cycles, weekdays, mode, clock —
  **no** water/temp/humidity.

## Tooling / conventions

- **Python: use `uv`** (`uv run …`, `uv sync`). Python 3.13+. Never pip.
- The BLE scanner is a PEP-723 uv script: `uv run sources/ha-scan/ble_scan.py`
  (`FILTER=FG SCAN_SECONDS=60`, needs `HA_TOKEN`).
- HA token: `HA_PROD_LONG_LIVED_TOKEN` in
  `~/Projects/joyfulhouse/homeassistant-dev/eg4_web_monitor/.env`. HA at
  `hass.joyful.house:8123` (REST) / `ws://…/api/websocket` (websocket).
- RE tools: `apkeep` (download), `jadx` (Java), `apktool` (manifest/smali),
  `ghidra` (only if native libs appear — none in this APK).
- The HA integration follows HA custom-component conventions; keep the protocol
  layer (`fogmachine/`) free of HA imports so it's unit-testable.

## Safety when live-testing

- Prefer a **read-only probe first** (connect, `start_notify` FFE1, send query
  `EE000.`, log raw bytes) before sending any control writes.
- Powering the machine on/off actuates a real pump/fogger outdoors — gate
  automations behind confirmation until the protocol is confirmed on a live unit.

## Next steps

Tracked in [`wiki/index.md`](wiki/index.md) (status table) and
[`wiki/integration-plan.md`](wiki/integration-plan.md) ("Open items"). The
immediate one is a live GATT probe via `adu-main` to confirm framing.
