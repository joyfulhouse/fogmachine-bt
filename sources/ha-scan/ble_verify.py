# /// script
# requires-python = ">=3.13"
# dependencies = ["aioesphomeapi>=24"]
# ///
"""Live-verification probe for FG-series fog machines: read-only by default,
with explicit opt-in NO-OP writes for cmd 2/3/4/5/6/7.

This is the human-run safety gate described in ``wiki/live-verify.md``. It
never invents frames: every byte comes from the builders in
``custom_components/fogmachine_bt/fogmachine/protocol.py`` (imported read-only),
and every "write" step re-sends the value the device itself just reported, so a
correct device ends the step in exactly the state it started in.

Default behaviour (no flags): connect through the ESPHome proxy, send the
connect handshake ``EE0c0.``, send query-all ``EE000.``, print the raw bytes
and the fully parsed state, disconnect. Nothing is changed.

NO-OP write steps (each needs its own flag AND ``--confirm-writes``; run in
ascending blast-radius order regardless of flag order):

  --noop-mode         cmd 2  re-send current customization mode
  --noop-weekday      cmd 3  re-send Monday's current on/off value
  --noop-time-master  cmd 4  re-send current time-customizable master toggle
  --noop-freq-master  cmd 5  re-send current freq-customizable master toggle
  --noop-time-entry   cmd 6  re-send the lowest-seq time window verbatim
  --noop-freq-entry   cmd 7  re-send the lowest-seq freq cycle verbatim

Every write step: read current value -> build the identical frame -> print raw
request bytes -> send -> print raw response + parsed (cmd id, rc) -> re-query
all -> DIFF against the pre-write state and fail on any change (the device
clock advancing is expected and reported separately). All writes REFUSE to run
unless power (cmd 1) reads OFF. Any rc != 0 or unexpected diff aborts the
remaining steps.

Offline paths (no hardware, no env needed):
  --dry-run             print the step plan and frame templates, connect nothing
  --parse '<raw>'       parse a pasted raw query-all response and print state
  --state-frame '<raw>' with --dry-run: compute the EXACT no-op frames from a
                        previously captured query-all response

Transport env (same conventions as ble_probe.py; a git-ignored ``.env`` in the
CWD or repo root is auto-loaded, never committed): ESPHOME_HOST (proxy
IP/host), ESPHOME_NOISE_PSK (proxy API encryption key), TARGET_MAC (fog
machine BLE address). Like ble_probe.py, run this where it can reach the
proxy's native API (:6053) — usually the HA host's network segment.

Run: ``uv run sources/ha-scan/ble_verify.py --help``
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import importlib.util
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_protocol():
    """Import the integration's protocol module read-only, by file path.

    ``custom_components`` is not an importable package from here; the module
    itself is stdlib-only, so a spec-based load keeps this script dependency-
    free of the integration's packaging.
    """
    path = (
        REPO_ROOT / "custom_components" / "fogmachine_bt" / "fogmachine" / "protocol.py"
    )
    spec = importlib.util.spec_from_file_location("fogmachine_protocol", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load protocol module from {path}")
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolves cls.__module__ through sys.modules; register first
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


P = _load_protocol()

WRITE_SPACING_S = 0.01  # bleWriteSpanTime: ~10 ms between 20-byte chunks
RESPONSE_TIMEOUT_S = 10.0


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from a git-ignored .env (CWD, then repo root).

    Never overrides variables already set in the environment.
    """
    for candidate in (Path.cwd() / ".env", REPO_ROOT / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


# --------------------------------------------------------------------------- #
#  Presentation helpers
# --------------------------------------------------------------------------- #
def show_bytes(label: str, data: bytes) -> None:
    print(f"  {label}: hex={data.hex()}  ascii={data.decode('latin1')!r}")


def state_to_rows(st) -> list[tuple[str, str]]:
    power = "?" if st.power_on is None else ("ON" if st.power_on else "OFF")
    running = (
        f"{st.running_hms} ({st.running_seconds}s)" if st.running_hms else "?"
    )
    weekdays = (
        "".join("Y" if d else "n" for d in st.weekdays) if st.weekdays else "?"
    )
    rows = [
        ("power", power),
        ("running_time", running),
        ("mode", st.mode or "?"),
        ("weekdays (Mon..Sun)", weekdays),
        ("time_customizable", str(st.time_customizable)),
        ("freq_customizable", str(st.freq_customizable)),
        ("device_datetime", st.device_datetime or "?"),
    ]
    for seq in sorted(st.time_entries):
        e = st.time_entries[seq]
        window = f"{e.from_h:02d}:{e.from_m:02d}-{e.to_h:02d}:{e.to_m:02d}"
        rows.append((f"time[{seq:02d}]", f"enabled={e.enabled} {window}"))
    for seq in sorted(st.freq_entries):
        e = st.freq_entries[seq]
        cycle = f"work={e.work_s}s pause={e.pause_s}s"
        rows.append((f"freq[{seq:02d}]", f"enabled={e.enabled} {cycle}"))
    return rows


def print_state(st, title: str = "PARSED DEVICE STATE") -> None:
    print(f"\n=== {title} ===")
    for name, value in state_to_rows(st):
        print(f"  {name:22} {value}")


def diff_states(before, after) -> tuple[list[str], list[str]]:
    """Compare two FogMachineState. Returns (real_changes, expected_changes).

    The device clock advancing between queries is expected; anything else on a
    no-op write is a failure. Running time must NOT move while power is OFF.
    """
    real: list[str] = []
    expected: list[str] = []
    for f in dataclasses.fields(before):
        b, a = getattr(before, f.name), getattr(after, f.name)
        if b == a:
            continue
        line = f"{f.name}: {b!r} -> {a!r}"
        if f.name == "device_datetime":
            expected.append(line + "  (clock advancing: expected)")
        elif f.name in ("running_seconds", "running_hms"):
            real.append(line + "  (running time moved with power OFF: NOT expected)")
        else:
            real.append(line)
    return real, expected


# --------------------------------------------------------------------------- #
#  No-op step planning (pure: state -> frames; testable offline)
# --------------------------------------------------------------------------- #
class StepError(Exception):
    """A no-op step cannot be built from the reported state."""


def build_noop_frame(step: str, st) -> bytes:
    """Build the frame that re-sends the device's CURRENT value for a step."""
    if step == "mode":
        if st.mode is None:
            raise StepError("device did not report a mode (query sub 2 missing)")
        mode_char = {v: k for k, v in P.MODE_NAMES.items()}.get(st.mode, st.mode)
        return P.build_mode(mode_char)
    if step == "weekday":
        if not st.weekdays:
            raise StepError("device did not report weekdays (query sub 3 missing)")
        return P.build_weekday(0, st.weekdays[0])  # Monday, current value
    if step == "time-master":
        if st.time_customizable is None:
            raise StepError("device did not report time-customizable (sub 4 missing)")
        flag = P.ON if st.time_customizable else P.OFF
        return P.build_request(P.CMD_TIME_CUSTOMIZABLE, flag)
    if step == "freq-master":
        if st.freq_customizable is None:
            raise StepError("device did not report freq-customizable (sub 5 missing)")
        flag = P.ON if st.freq_customizable else P.OFF
        return P.build_request(P.CMD_FREQ_CUSTOMIZABLE, flag)
    if step == "time-entry":
        if not st.time_entries:
            raise StepError("device reported no time entries (sub 6 missing)")
        e = st.time_entries[min(st.time_entries)]
        return P.build_time_entry(e.seq, e.enabled, e.from_h, e.from_m, e.to_h, e.to_m)
    if step == "freq-entry":
        if not st.freq_entries:
            raise StepError("device reported no freq entries (sub 7 missing)")
        e = st.freq_entries[min(st.freq_entries)]
        return P.build_freq_entry(e.seq, e.enabled, e.work_s, e.pause_s)
    raise StepError(f"unknown step {step!r}")


# (step, cmdId, description) in ascending blast-radius order — wiki/live-verify.md
STEPS: list[tuple[str, str, str]] = [
    ("mode", P.CMD_MODE, "re-send current customization mode"),
    ("weekday", P.CMD_WEEKDAY, "re-send Monday's current on/off value"),
    ("time-master", P.CMD_TIME_CUSTOMIZABLE, "re-send time-customizable master toggle"),
    ("freq-master", P.CMD_FREQ_CUSTOMIZABLE, "re-send freq-customizable master toggle"),
    ("time-entry", P.CMD_TIME_CUSTOMIZE, "re-send lowest-seq time window verbatim"),
    ("freq-entry", P.CMD_FREQ_CUSTOMIZE, "re-send lowest-seq freq cycle verbatim"),
]

FRAME_TEMPLATES = {
    "mode": "EE02 0 <mode> .",
    "weekday": "EE03 0 <dayIdx><0=on/1=off> .",
    "time-master": "EE04 0 <0=on/1=off> .",
    "freq-master": "EE05 0 <0=on/1=off> .",
    "time-entry": "EE06 0 <seq:2><en:1><fromHH:2><fromMM:2><toHH:2><toMM:2> .",
    "freq-entry": "EE07 0 <seq:2><en:1><workSec:5><pauseSec:5> .",
}


# --------------------------------------------------------------------------- #
#  BLE transport (same aioesphomeapi pattern as ble_probe.py)
# --------------------------------------------------------------------------- #
class ProxyLink:
    """One GATT link to the fog machine via an ESPHome BLE proxy."""

    def __init__(self, cli, addr: int, ffe1_handle: int):
        self.cli = cli
        self.addr = addr
        self.handle = ffe1_handle
        self.buf = bytearray()
        self.expected_terms = 1
        self.done = asyncio.Event()

    def on_notify(self, handle, data) -> None:
        self.buf.extend(data)
        show_bytes("NOTIFY chunk", bytes(data))
        if self.buf.count(b".") >= self.expected_terms:
            self.done.set()

    async def request(self, frame: bytes, label: str) -> bytes:
        """Write one request frame and return the '.'-terminated raw response.

        ≤20-byte chunks, write-without-response — the FG53850's FFE1 rejects
        write-with-response, see wiki/ble-transport.md.
        """
        self.buf.clear()
        self.done.clear()
        show_bytes(f"REQUEST {label}", frame)
        for i in range(0, len(frame), P.WRITE_CHUNK):
            await self.cli.bluetooth_gatt_write(
                self.addr, self.handle, frame[i : i + P.WRITE_CHUNK], False
            )
            await asyncio.sleep(WRITE_SPACING_S)
        try:
            await asyncio.wait_for(self.done.wait(), timeout=RESPONSE_TIMEOUT_S)
        except TimeoutError:
            raise TimeoutError(
                f"no '.'-terminated response within {RESPONSE_TIMEOUT_S:.0f}s "
                f"(got {len(self.buf)} bytes: {bytes(self.buf)!r})"
            ) from None
        raw = bytes(self.buf)
        show_bytes(f"RESPONSE {label}", raw)
        return raw


async def connect_link(host: str, psk: str, mac: str) -> tuple[object, ProxyLink]:
    from aioesphomeapi import APIClient

    addr = int(mac.upper().replace(":", ""), 16)
    cli = APIClient(host, 6053, None, noise_psk=psk)
    await cli.connect(login=True)
    info = await cli.device_info()
    feat = getattr(info, "bluetooth_proxy_feature_flags", 0)
    print(f"connected to ESPHome {info.name} ({host}); bt_proxy_feature_flags={feat}")

    # advertisement capture: confirms presence and yields address_type
    addr_type = {"v": None}
    seen = asyncio.Event()

    def on_adv(adv):
        if getattr(adv, "address", None) == addr:
            addr_type["v"] = getattr(adv, "address_type", None)
            if not seen.is_set():
                print(
                    f"  advertisement: rssi={getattr(adv, 'rssi', None)} "
                    f"name={getattr(adv, 'name', None)!r} "
                    f"address_type={addr_type['v']}"
                )
                seen.set()

    unsub = cli.subscribe_bluetooth_le_advertisements(on_adv)
    try:
        await asyncio.wait_for(seen.wait(), timeout=25)
    except TimeoutError:
        print("  (no advertisement in 25s — device may be connected elsewhere)")
    finally:
        unsub()

    state = {"connected": False}
    conn_evt = asyncio.Event()

    def on_state(connected, mtu, error):
        state["connected"] = connected
        print(f"  conn state: connected={connected} mtu={mtu} error={error}")
        conn_evt.set()

    disconnect = None
    for attempt in range(1, 4):
        conn_evt.clear()
        print(f"connecting GATT (attempt {attempt}) addr_type={addr_type['v']} ...")
        try:
            disconnect = await cli.bluetooth_device_connect(
                addr, on_state, timeout=30.0, disconnect_timeout=20.0,
                feature_flags=feat, has_cache=False, address_type=addr_type["v"],
            )
            await asyncio.wait_for(conn_evt.wait(), timeout=32)
            if state["connected"]:
                break
        except Exception as e:  # noqa: BLE001
            print(f"  connect attempt {attempt} failed: {type(e).__name__}: {e}")
        if disconnect:
            with contextlib.suppress(Exception):
                disconnect()
        await asyncio.sleep(2)
    if not state["connected"]:
        await cli.disconnect()
        raise ConnectionError(
            "could not establish a GATT connection (RF marginal / app holding it?)"
        )

    svcs = await cli.bluetooth_gatt_get_services(addr)
    ffe1 = None
    for s in svcs.services:
        for c in s.characteristics:
            if "ffe1" in str(c.uuid).lower():
                ffe1 = c.handle
    if ffe1 is None:
        await cli.bluetooth_device_disconnect(addr)
        await cli.disconnect()
        raise ConnectionError("FFE1 characteristic not found")
    print(f"FFE1 handle={ffe1}")

    link = ProxyLink(cli, addr, ffe1)
    await cli.bluetooth_gatt_start_notify(addr, ffe1, link.on_notify)
    print("notifications enabled on FFE1")
    return cli, link


async def query_all(link: ProxyLink):
    raw = await link.request(P.build_query_all(), "query-all EE000.")
    return P.parse_query_all(raw), raw


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="ble_verify.py",
        description=(
            "Read-only fog-machine probe with opt-in NO-OP writes for cmd 2-7. "
            "Changes nothing by default; all writes refuse to run unless power "
            "reads OFF. See wiki/live-verify.md for the ordered checklist."
        ),
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="no BLE at all: print the step plan "
             "(and exact frames if --state-frame given)",
    )
    ap.add_argument(
        "--parse", metavar="RAW",
        help="offline: parse a raw query-all response string and print the state",
    )
    ap.add_argument(
        "--state-frame", metavar="RAW",
        help="with --dry-run: captured query-all response to compute "
             "exact no-op frames from",
    )
    for step, cmd_id, desc in STEPS:
        ap.add_argument(
            f"--noop-{step}", action="store_true",
            dest=f"noop_{step.replace('-', '_')}",
            help=f"NO-OP write, cmd {cmd_id}: {desc}",
        )
    ap.add_argument(
        "--confirm-writes", action="store_true",
        help="required with any --noop-* flag; without it every write is refused",
    )
    ap.add_argument(
        "--yes", action="store_true",
        help="skip the interactive per-write confirmation prompt "
             "(non-TTY runs need this)",
    )
    return ap.parse_args(argv)


def selected_steps(args: argparse.Namespace) -> list[tuple[str, str, str]]:
    return [t for t in STEPS if getattr(args, f"noop_{t[0].replace('-', '_')}")]


def confirm(step: str, frame: bytes, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print(f"  REFUSED {step}: stdin is not a TTY and --yes was not given")
        return False
    prompt = f"  send NO-OP {step} frame {frame.decode('latin1')!r}? type YES to send: "
    return input(prompt).strip() == "YES"


def run_offline(args: argparse.Namespace) -> int:
    if args.parse:
        st = P.parse_query_all(args.parse)
        print_state(st, "PARSED (offline) DEVICE STATE")
        return 0

    steps = selected_steps(args)
    print("DRY RUN — no BLE connection will be made.\n")
    print("plan: connect handshake EE0c0. -> query-all EE000. -> print parsed state")
    if not steps:
        print("no --noop-* flags: read-only, nothing else would be sent.")
        return 0
    st = P.parse_query_all(args.state_frame) if args.state_frame else None
    if st:
        print_state(st, "STATE FROM --state-frame")
        if st.power_on is not False:
            print(
                "\n⚠️  power does not read OFF in this state — "
                "a live run would REFUSE all writes."
            )
    print("\nno-op write steps (ascending blast radius):")
    for step, cmd_id, desc in steps:
        if st:
            try:
                frame = build_noop_frame(step, st).decode("latin1")
                print(f"  cmd {cmd_id} {step:12} -> would send {frame!r}  ({desc})")
            except StepError as e:
                print(f"  cmd {cmd_id} {step:12} -> UNBUILDABLE: {e}")
        else:
            print(f"  cmd {cmd_id} {step:12} -> {FRAME_TEMPLATES[step]}  ({desc})")
    if not args.confirm_writes:
        print("\nNOTE: --confirm-writes not given — a live run would refuse these.")
    return 0


async def run_live(args: argparse.Namespace) -> int:
    steps = selected_steps(args)
    host = os.environ["ESPHOME_HOST"]
    psk = os.environ["ESPHOME_NOISE_PSK"]
    mac = os.environ["TARGET_MAC"]

    cli, link = await connect_link(host, psk, mac)
    try:
        # protocol init handshake, exactly like the OEM app after discovery
        raw = await link.request(P.build_connect(), "connect EE0c0.")
        cmd_id, rc, _ = P.parse_simple_response(raw)
        if cmd_id != P.CMD_CONNECT or rc != P.RC_OK:
            print(f"❌ connect handshake failed: cmd={cmd_id!r} rc={rc!r}")
            return 1

        # ALWAYS read + print full state first
        st, _ = await query_all(link)
        print_state(st)

        if not steps:
            print("\nread-only run complete; nothing written besides EE0c0./EE000.")
            return 0

        # ---- safety gate: power must read OFF ----
        if st.power_on is not False:
            reading = "ON" if st.power_on else "not reported"
            print(
                f"\n❌ SAFETY GATE: power reads {reading}, not OFF — "
                "refusing ALL write steps."
            )
            return 3

        failures = 0
        for step, cmd_id_expected, desc in steps:
            print(f"\n--- NO-OP STEP cmd {cmd_id_expected}: {step} ({desc}) ---")
            try:
                frame = build_noop_frame(step, st)
            except StepError as e:
                print(f"  SKIPPED: {e}")
                continue
            if not confirm(step, frame, args.yes):
                print("  skipped by user")
                continue
            t0 = time.monotonic()
            raw = await link.request(frame, f"noop-{step}")
            got_cmd, rc, payload = P.parse_simple_response(raw)
            print(
                f"  parsed response: cmd={got_cmd!r} rc={rc!r} payload={payload!r} "
                f"({time.monotonic() - t0:.2f}s)"
            )
            if got_cmd != cmd_id_expected or rc != P.RC_OK:
                print(
                    f"  ❌ FAIL: expected cmd {cmd_id_expected!r} rc {P.RC_OK!r} — "
                    "aborting remaining steps"
                )
                failures += 1
                break
            # same-connection read-back + diff
            st_after, _ = await query_all(link)
            real, expect = diff_states(st, st_after)
            for line in expect:
                print(f"  diff (ok): {line}")
            if real:
                for line in real:
                    print(f"  ❌ diff (UNEXPECTED): {line}")
                print("  ❌ FAIL: state changed on a no-op write — aborting")
                failures += 1
                break
            print("  ✅ PASS: rc=0 and read-back identical (device clock aside)")
            st = st_after  # next step diffs against the freshest state
        verdict = (
            f"❌ FAILURES: {failures}" if failures
            else "✅ all requested steps passed"
        )
        print(f"\n{verdict}")
        print(
            "paste the REQUEST/RESPONSE/diff lines above into the "
            "wiki/live-verify.md evidence log"
        )
        return 1 if failures else 0
    finally:
        with contextlib.suppress(Exception):
            await cli.bluetooth_device_disconnect(link.addr)
        await cli.disconnect()


def main() -> int:
    args = parse_args()
    if args.dry_run or args.parse:
        return run_offline(args)
    if selected_steps(args) and not args.confirm_writes:
        print("❌ --noop-* flags given without --confirm-writes; refusing to start.")
        return 2
    _load_dotenv()
    missing = [
        k
        for k in ("ESPHOME_HOST", "ESPHOME_NOISE_PSK", "TARGET_MAC")
        if k not in os.environ
    ]
    if missing:
        print(
            f"❌ missing env: {', '.join(missing)} "
            "(set in a git-ignored .env or the environment)"
        )
        return 2
    return asyncio.run(run_live(args))


if __name__ == "__main__":
    sys.exit(main())
