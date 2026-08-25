# /// script
# requires-python = ">=3.11"
# dependencies = ["aioesphomeapi>=24"]
# ///
"""Read-only live GATT probe of FG53850 via the ESPHome BLE proxy `adu-main`.

Connects to the ESPHome native API, opens a proxied GATT connection to the fog
machine, discovers FFE0/FFE1, enables notifications, sends ONLY the read-only
query-all frame `EE000.`, and logs the raw response. Never sends a control
(power) command.

Env: ESPHOME_HOST, ESPHOME_NOISE_PSK, TARGET_MAC (default 02:11:23:34:5A:17)
"""
import asyncio
import os
import sys

from aioesphomeapi import APIClient

HOST = os.environ.get("ESPHOME_HOST", "10.100.12.244")
PSK = os.environ["ESPHOME_NOISE_PSK"]
MAC = os.environ.get("TARGET_MAC", "02:11:23:34:5A:17").upper()
ADDR = int(MAC.replace(":", ""), 16)
QUERY_ALL = b"EE000."  # read-only status request; does NOT actuate the pump


def uuid_str(u):
    return str(u).lower()


async def main():
    cli = APIClient(HOST, 6053, None, noise_psk=PSK)
    await cli.connect(login=True)
    info = await cli.device_info()
    feat = getattr(info, "bluetooth_proxy_feature_flags", 0)
    print(f"connected to ESPHome {info.name} ({HOST}); bt_proxy_feature_flags={feat}")

    # --- 1. capture advertisement to confirm presence + get address_type/RSSI ---
    addr_type = {"v": None}
    seen = asyncio.Event()

    def on_adv(adv):
        if getattr(adv, "address", None) == ADDR:
            addr_type["v"] = getattr(adv, "address_type", None)
            if not seen.is_set():
                print(f"  advertisement: rssi={getattr(adv,'rssi',None)} "
                      f"name={getattr(adv,'name',None)!r} address_type={addr_type['v']}")
                seen.set()

    unsub = cli.subscribe_bluetooth_le_advertisements(on_adv)
    try:
        await asyncio.wait_for(seen.wait(), timeout=25)
    except asyncio.TimeoutError:
        print("  (no advertisement captured in 25s — proceeding with address_type=None)")
    finally:
        unsub()

    # --- 2. connect GATT through the proxy (retry: RF is marginal) ---
    state = {"connected": False, "mtu": 0, "error": 0}
    conn_evt = asyncio.Event()

    def on_state(connected, mtu, error):
        state.update(connected=connected, mtu=mtu, error=error)
        print(f"  conn state: connected={connected} mtu={mtu} error={error}")
        conn_evt.set()

    disconnect = None
    for attempt in range(1, 4):
        conn_evt.clear()
        print(f"connecting GATT (attempt {attempt}) addr_type={addr_type['v']} ...")
        try:
            disconnect = await cli.bluetooth_device_connect(
                ADDR, on_state, timeout=30.0, disconnect_timeout=20.0,
                feature_flags=feat, has_cache=False, address_type=addr_type["v"],
            )
            await asyncio.wait_for(conn_evt.wait(), timeout=32)
            if state["connected"]:
                break
        except Exception as e:  # noqa: BLE001
            print(f"  connect attempt {attempt} failed: {type(e).__name__}: {e}")
        if disconnect:
            try:
                disconnect()
            except Exception:
                pass
        await asyncio.sleep(2)

    if not state["connected"]:
        print("\n❌ could not establish a GATT connection (RF marginal / slots / phone app holding it).")
        await cli.disconnect()
        return 1

    # --- 3. discover services, find FFE1 ---
    svcs = await cli.bluetooth_gatt_get_services(ADDR)
    ffe1_handle = None
    ffe1_props = None
    for s in svcs.services:
        for c in s.characteristics:
            cu = uuid_str(c.uuid)
            if cu.startswith("0000ffe1") or cu == "ffe1" or "ffe1" in cu:
                ffe1_handle = c.handle
                ffe1_props = getattr(c, "properties", None)
            print(f"    char {uuid_str(c.uuid)} handle={c.handle} props={getattr(c,'properties',None)} (svc {uuid_str(s.uuid)})")
    if ffe1_handle is None:
        print("❌ FFE1 characteristic not found")
        await cli.bluetooth_device_disconnect(ADDR)
        await cli.disconnect()
        return 1
    print(f"FFE1 handle={ffe1_handle} props={ffe1_props}")

    # --- 4. notifications + read-only query ---
    buf = bytearray()
    got = asyncio.Event()

    def on_notify(handle, data):
        buf.extend(data)
        try:
            txt = bytes(data).decode("latin1")
        except Exception:
            txt = repr(bytes(data))
        print(f"  NOTIFY h={handle} {bytes(data).hex()}  ascii={txt!r}")
        if b"." in buf:
            got.set()

    try:
        unsub_notify, _cancel = await cli.bluetooth_gatt_start_notify(ADDR, ffe1_handle, on_notify)
        print("notifications enabled on FFE1")
    except Exception as e:  # noqa: BLE001
        print(f"  start_notify failed: {type(e).__name__}: {e}")
        unsub_notify = None

    # write-with-response mirrors the app (WRITE_TYPE_DEFAULT)
    for resp in (True, False):
        print(f"writing query-all {QUERY_ALL!r} (response={resp}) ...")
        try:
            await cli.bluetooth_gatt_write(ADDR, ffe1_handle, QUERY_ALL, resp)
            break
        except Exception as e:  # noqa: BLE001
            print(f"  write(response={resp}) failed: {type(e).__name__}: {e}")

    try:
        await asyncio.wait_for(got.wait(), timeout=10)
    except asyncio.TimeoutError:
        print("  (no '.'-terminated response within 10s)")

    print(f"\n=== RAW RESPONSE ({len(buf)} bytes) ===")
    print("hex :", bytes(buf).hex())
    print("ascii:", bytes(buf).decode("latin1", "replace"))

    # --- 5. clean up ---
    if unsub_notify:
        try:
            await unsub_notify()
        except Exception:
            pass
    await cli.bluetooth_device_disconnect(ADDR)
    await cli.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
