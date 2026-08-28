# Live verification gate — proving cmd 2–7 writes are safe

Purpose: the ordered, human-run checklist that verifies the set-commands
(cmd `2`/`3`/`4`/`5`/`6`/`7`) against the real FG53850 **before** any control
entities are allowed to send them. Status: **planned** — ⚠️ no step below has
been executed on hardware yet; this page becomes the evidence log as steps run.

Why this exists: every read path is live-verified (see [index](index.md)), but
**no set-write has ever been sent to a live unit**. These frames actuate a real
outdoor pump/fogger. The frame spec is verified from source only
([ble-protocol](ble-protocol.md)); this checklist closes the loop with the
smallest possible blast radius at each step.

## Ground rules (apply to every step)

- **Power stays OFF for the entire session.** The tool refuses all writes
  unless the query-all power reading (sub `1`) is OFF; you should also visually
  confirm the machine is not fogging before starting.
- Steps are ordered by **ascending blast radius** — do not reorder or skip
  ahead. Stop the session on the first anomaly (rc != 0, unexpected diff,
  device reboot/disconnect) and record it before anything else.
- Every write in steps 1–6 is a **no-op**: it re-sends the value the device
  just reported, built by the same
  `custom_components/fogmachine_bt/fogmachine/protocol.py` builders the
  integration will use. A correct device ends each step unchanged.
- The tool is `sources/ha-scan/ble_verify.py` (registered in
  [sources](sources.md)). Preview any step offline first:

  ```sh
  uv run sources/ha-scan/ble_verify.py --help
  uv run sources/ha-scan/ble_verify.py --dry-run --state-frame '<raw>' --noop-mode ...
  ```

- **Capture everything**: run each live invocation under `tee` so the raw
  transcript (REQUEST/RESPONSE hex+ascii lines, parsed rc, diffs) lands in
  `sources/ha-scan/live-verify/` (raw, immutable — see [SCHEMA](SCHEMA.md)):

  ```sh
  mkdir -p sources/ha-scan/live-verify
  uv run sources/ha-scan/ble_verify.py ... 2>&1 | tee sources/ha-scan/live-verify/$(date +%Y%m%d-%H%M%S)-<step>.txt
  ```

  Then paste the distilled evidence (request bytes, response bytes, rc, diff
  verdict) into this page's evidence log below and flip the step's checkbox.

## Evidence to capture per write step

For each step record, in the step's log section below:

1. raw request bytes (hex + ascii) exactly as sent;
2. raw response bytes (hex + ascii) exactly as received;
3. parsed response: cmd id, rc, payload (expect rc `0` and the echo payload
   from the [command table](ble-protocol.md#command-table));
4. the same-connection read-back diff (expect: only `device_datetime`
   advanced; `running_time` must NOT move with power off);
5. transcript filename in `sources/ha-scan/live-verify/`.

## The checklist

### Step 0 — passive parser validation (zero write risk)

Nothing is written by us at all: the human changes settings in the OEM
**"SPW Misting"** app while HA (or repeated read-only `ble_verify.py` runs)
polls the device, proving every read parser decodes real frames. Note the
device stops advertising while the phone holds the connection — poll between
app sessions ([ha-proxy-coverage](ha-proxy-coverage.md)).

- [ ] Baseline: `uv run sources/ha-scan/ble_verify.py` (no flags, read-only) —
      record the full parsed state + raw query-all response here.
- [ ] In the app, change the **customization mode** (e.g. Always → Advanced);
      re-poll; confirm sub `2` parses to the new mode. Revert in the app.
- [ ] In the app, toggle one **weekday**; re-poll; confirm the right position
      in the 7-char sub `3` mask flips (Mon=index 0). Revert.
- [ ] In the app, toggle the **time-customizable** and **freq-customizable**
      masters; re-poll; confirm subs `4`/`5` follow (inverted: `0`=on). Revert.
- [ ] In the app, edit a **time window** and a **freq cycle**; re-poll; confirm
      the 11-char sub `6` / 13-char sub `7` payloads match the app's values
      field-for-field. Revert.
- [ ] Outcome: every parser in `protocol.py` validated against live frames, and
      the captured query-all responses double as `--state-frame` inputs for
      dry-running steps 1–6.

Evidence log:

```
(paste raw query-all responses + parsed states per toggle here)
```

### Steps 1–6 — no-op writes, ascending blast radius

Each step: dry-run first with the freshest captured `--state-frame`, verify the
printed frame re-encodes the current value byte-for-byte, then run live. One
step per invocation. Power must read OFF or the tool refuses.

- [ ] **Step 1 — cmd `2` (mode)**: re-send the current mode.
      Worst case if the protocol surprises us: mode changes while power is off
      → visible in diff, revertable in the app.

  ```sh
  uv run sources/ha-scan/ble_verify.py --noop-mode --confirm-writes
  ```

- [ ] **Step 2 — cmd `3` (weekday)**: re-send Monday's current on/off value.
      Worst case: one schedule day flips → revertable in the app.

  ```sh
  uv run sources/ha-scan/ble_verify.py --noop-weekday --confirm-writes
  ```

- [ ] **Step 3 — cmd `4` (time-customizable master)**: re-send current toggle.

  ```sh
  uv run sources/ha-scan/ble_verify.py --noop-time-master --confirm-writes
  ```

- [ ] **Step 4 — cmd `5` (freq-customizable master)**: re-send current toggle.
      Masters gate whole schedule groups, hence after the single-field cmds.

  ```sh
  uv run sources/ha-scan/ble_verify.py --noop-freq-master --confirm-writes
  ```

- [ ] **Step 5 — cmd `6` (time window)**: re-send the lowest-seq window
      verbatim (11-char payload). First multi-field write.

  ```sh
  uv run sources/ha-scan/ble_verify.py --noop-time-entry --confirm-writes
  ```

- [ ] **Step 6 — cmd `7` (freq cycle)**: re-send the lowest-seq work/pause
      cycle verbatim (13-char payload). Largest payload; directly parameterises
      pump duty when running, hence last.

  ```sh
  uv run sources/ha-scan/ble_verify.py --noop-freq-entry --confirm-writes
  ```

Evidence log (one block per step, see "Evidence to capture" above):

```
(paste per-step REQUEST/RESPONSE/rc/diff blocks here)
```

### Step 7 — ONE real change, on a DISABLED time window, with revert

Only after steps 0–6 all pass. This is the first frame that intentionally
changes device state. Blast radius is minimised by choosing a **disabled**
window (`enabled=1` in sub `6` — remember inverted booleans) whose values are
inert while disabled, and changing only its **minutes** field.

- [ ] Pick a time window whose read-back shows `enabled=False`; record its full
      current 11-char payload here: `____________`.
- [ ] Send the same window with **only `from_m` changed by +1 minute** (build
      via `--dry-run --state-frame` first to eyeball the frame; then send with
      the OEM app or a one-off `build_time_entry` call — keep the window
      DISABLED in the frame). Confirm rc `0`.
- [ ] Re-query: confirm the read-back shows exactly the one-minute change and
      nothing else.
- [ ] **Revert**: re-send the recorded original payload. Confirm rc `0` and
      that read-back matches the original byte-for-byte.
- [ ] Cross-check in the OEM app that the window shows its original values.

Evidence log:

```
(original payload, changed frame, both responses, final read-back)
```

### Aftercare

- [ ] Fold results into the wiki: mark the `⚠️` worked-example frames in
      [ble-protocol](ble-protocol.md) as live-verified (or correct them), update
      the status row in [index](index.md), and register the transcript files in
      [sources](sources.md).
- [ ] Only then: unblock the Phase 2 control entities in
      [integration-plan](integration-plan.md).

## What passing means

All six set-commands round-trip on real hardware with rc `0`, no-op writes
provably change nothing, and a real write + revert behaves exactly per the
[ble-protocol](ble-protocol.md) spec — the preconditions for letting HA
entities send cmd 2–7 unattended.
