# BLE protocol — frame + command spec (authoritative)

Purpose: the complete wire protocol for controlling FG53850.
Status: **verified from source**; payload widths from the app's own parser
(`MistingDevCmdDataFormat`). Byte strings not yet echoed by a live device — see
`⚠️` notes. Cross-checked against Codex's independent read
(`sources/codex-analysis/PROTOCOL_CODEX.md`).

Transport for these bytes is on [ble-transport](ble-transport.md).

## Frame format (both directions)

```
EE <phase> <cmdId> <code> <payload...> <term>
```

ASCII, no checksum, no CRC, no length field.

| Field | Bytes | Values | Notes |
|---|---|---|---|
| Header | `EE` | literal | `MistingCmdConstants.Cmd_Header` |
| phase | 1 | `0`=request (app→dev), `1`=response (dev→app) | |
| cmdId | 1 | see table below | |
| code | 1 | request: always `0`; response: `0`=success / `1`=failure | `ReturnCode_*` |
| payload | N | command-specific (below) | |
| term | 1 | `.` end-of-command (`Cmd_End`) | within query-all, sub-blocks use `,` (`Cmd_PartEnd`) and the whole reply ends `.` |

Built by `AbstractMistingDevCmd.packRequest()`; parsed by
`AbstractMistingDevCmd.unpackResponse()`. Request layout: `EE`,`phase`,`cmdId`,
literal `0`, `payload`, `.`. Response layout is identical with `code` in the 5th
position.

**Global boolean convention (inverted):** `0` = ON/enabled, `1` = OFF/disabled
(`Switch_On='0'`, `Switch_Off='1'`). Applies to power, per-day, and `enabled`
flags.

## Command table

| cmdId | Name | Request payload | Response payload |
|---|---|---|---|
| `0` | Query / RunTime | empty = *query-all*; or a single subId char. **First-ever query** instead carries a clock-sync: `+` + `yyyyMMddHHmmss` + weekdayIdx | concatenation of sub-blocks — see below |
| `1` | Power | 1 char: `0`=ON / `1`=OFF | (none/echo) |
| `2` | Customization mode | 1 char: `0`=AlwaysSpray / `1`=Nimble / `2`=AdvancedSet | mode char |
| `3` | Weekday (per day) | 2 chars: `<dayIdx 0-6>` + `<0=on/1=off>` | 1 char: day idx echoed |
| `4` | Time-customizable toggle | 1 char: `0`=on / `1`=off | 1 char |
| `5` | Freq-customizable toggle | 1 char: `0`=on / `1`=off | 1 char |
| `6` | Time customize (per entry) | 11 chars (below) | seq echoed |
| `7` | Freq customize (per entry) | 13 chars (below) | 2 chars: seq echoed |
| `8` | Batch | app-side only — children are sent as separate `EE….` frames, **not** an `EE08…` frame | concatenation of sub-responses |
| `c` | Connect handshake | `EE0c0.` — written **after** GATT connect + service discovery (the pending connect cmd is flushed by `inRun()`) | `EE1c<rc>.` |
| `+` | DateTime | `EE0+0yyyyMMddHHmmssW.` — **not used in production**; the clock is instead embedded in the first query (below) | — |

**weekdayIdx** = `(Calendar.DAY_OF_WEEK + 5) % 7` → **Mon=0 … Sun=6**
(`MistingDevQueryCmd.getCommandString`).

### Payload layouts (widths are authoritative, from `MistingDevCmdDataFormat`)

- **Running time** (query sub `0`): 6 digits `HHMMSS`, each field 0–99
  (`getRunningTime`/`setRunningTime`). This is cumulative run time, not clock.
- **Weekdays** (cmd `3` query sub `3`): 7 chars, one per day Mon→Sun, `0`=on/`1`=off
  (`getAllWeekDays`).
- **Time customize** (cmd `6`, sub `6`): 11 chars =
  `seq(2)` `enabled(1)` `fromHour(2)` `fromMin(2)` `toHour(2)` `toMin(2)`
  (`getCustomizedTime`/`setCustomizedTime`). Hours 0–23, mins 0–59.
- **Freq customize** (cmd `7`, sub `7`): 13 chars =
  `seq(2)` `enabled(1)` `workSec(5)` `pauseSec(5)` (`getCustomizedFreq`,
  `DecimalFormat("00000")`). work 3–84600 s, pause 5–84600 s. This is the
  spray-on / spray-off duty cycle ("frequency").
- **Customization mode** (cmd `2`, sub `2`): 1 char `0/1/2` as above.

### Query-all response structure

`MistingDevQueryCmd.unpackResponse()` parses a concatenation of sub-blocks:

```
EE 1 0 <rc> <subId> <data> ,   (repeated)  … ending with .
```

subId → field mapping (`setSingleCommandResult`):

| subId | field | data |
|---|---|---|
| `+` | device clock | `yyyyMMddHHmmss`(+wd) |
| `0` | running time | 6 digits `HHMMSS` |
| `1` | power | `0`=on/`1`=off |
| `2` | customization mode | `0/1/2` |
| `3` | weekdays | 7 chars |
| `4` | time-customizable | `0/1` |
| `5` | freq-customizable | `0/1` |
| `6` | a customized-time entry | 11 chars |
| `7` | a customized-freq entry | 13 chars |

`enabled` inside entries: `0`=enabled/`1`=disabled.

## Connect + first-query sequence (on-wire)

After the GATT link is up and FFE1 notifications are enabled, the app performs:

1. **Connect handshake** → `EE0c0.`  → device replies `EE1c0.`
2. **First query (with clock sync)** → `EE000+yyyyMMddHHmmssW.`
   (W = weekday, Mon=0..Sun=6) → device replies with the full query-all block set.
   After the first success, subsequent polls send the plain `EE000.`

A third-party client should replicate this: connect → notify → `EE0c0.` →
`EE000…` . (Verified from `MistingBLEServiceExecutor.run`/`inRun` +
`MistingDevQueryCmd.getCommandString`; cross-checked by Codex, see
`sources/codex-analysis/PROTOCOL_CODEX.md`.)

## Worked examples

Request bytes (ASCII), `⚠️` = not yet echoed by a live unit:

- **Connect**: `EE0c0.`  → response `EE1c0.`
- **Power ON**: `EE0100.` → response `EE110.`
- **Power OFF**: `EE0101.`
- **Query-all** (steady state): `EE000.`
- **First query + clock** (Mon 2026-08-24 13:05:09): `EE000+202608241305090.`
- **Set Wednesday off** (dayIdx 2, off): payload `20`+off → `EE03021.`
- **Freq entry 3, enabled, 35 s on / 8640 s off**: `EE0700300003508640.`
  (response `EE17003.` acks index 03)
- **Query-all response block** (power ON): `EE10010,` — `EE`,`1`,`0`,rc`0`,sub`1`,`0`(on),`,`;
  the whole reply concatenates blocks and ends with a single `.`

⚠️ The factory's built-in `getTestResponse` example strings use some placeholder
payloads whose lengths don't all match the parser's declared widths (e.g. a
10-char time entry). Treat the **parser widths above as authoritative** and
confirm exact framing against a live capture.
