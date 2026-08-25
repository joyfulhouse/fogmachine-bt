# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=13"]
# ///
"""Scan Home Assistant BLE proxies for a target device via the
`bluetooth/subscribe_advertisements` websocket API.

Reports, for a name/address substring filter, every proxy (scanner) that hears
the device and the RSSI it hears it at — i.e. which BLE proxy is closest.

Note: if the integration is installed and enabled, stop/disable it before
scanning — these devices stop advertising while a central is connected, so a
held connection suppresses the very advertisement you're looking for.

Env:
  HA_WS_URL      default ws://homeassistant.local:8123/api/websocket
  HA_TOKEN       long-lived token (required)
  SCAN_SECONDS   default 25
  FILTER         name/address substring to match (default FG)
  PROXY_NAMES    optional JSON map {source_mac_upper: friendly_name}
"""
import asyncio
import json
import os
import sys
import time

import websockets

HA_WS_URL = os.environ.get("HA_WS_URL", "ws://homeassistant.local:8123/api/websocket")
TOKEN = os.environ["HA_TOKEN"]
SCAN_SECONDS = float(os.environ.get("SCAN_SECONDS", "25"))
FILTER = os.environ.get("FILTER", "FG").upper()
PROXY_NAMES = json.loads(os.environ.get("PROXY_NAMES", "{}"))


def pname(source: str) -> str:
    if not source:
        return "?"
    return PROXY_NAMES.get(source.upper(), source)


def norm_adv(item):
    """subscribe_advertisements items can be dicts or positional lists depending
    on HA version. Normalise to a dict with the fields we care about."""
    if isinstance(item, dict):
        return {
            "address": item.get("address", ""),
            "name": item.get("name") or "",
            "rssi": item.get("rssi"),
            "source": item.get("source", ""),
            "service_uuids": item.get("service_uuids") or [],
            "manufacturer_data": item.get("manufacturer_data") or {},
            "service_data": item.get("service_data") or {},
            "connectable": item.get("connectable"),
            "tx_power": item.get("tx_power"),
        }
    # positional tuple form: (name, address, rssi, manufacturer_data,
    # service_data, service_uuids, source, connectable, tx_power, ...)
    try:
        return {
            "name": item[0] or "",
            "address": item[1] or "",
            "rssi": item[2],
            "manufacturer_data": item[3] or {},
            "service_data": item[4] or {},
            "service_uuids": item[5] or [],
            "source": item[6] if len(item) > 6 else "",
            "connectable": item[7] if len(item) > 7 else None,
            "tx_power": item[8] if len(item) > 8 else None,
        }
    except Exception:
        return None


async def main():
    async with websockets.connect(HA_WS_URL, max_size=None) as ws:
        auth_req = json.loads(await ws.recv())
        if auth_req.get("type") != "auth_required":
            print(f"unexpected handshake: {auth_req}", file=sys.stderr)
            return 2
        await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
        auth_res = json.loads(await ws.recv())
        if auth_res.get("type") != "auth_ok":
            print(f"AUTH FAILED: {auth_res}", file=sys.stderr)
            return 2
        print(f"authenticated to {HA_WS_URL} (HA {auth_res.get('ha_version')})")

        await ws.send(json.dumps({"id": 1, "type": "bluetooth/subscribe_advertisements"}))
        sub = json.loads(await ws.recv())
        if not sub.get("success", False):
            print(f"subscribe failed: {sub}", file=sys.stderr)
            return 2
        print(f"scanning {SCAN_SECONDS:.0f}s for '{FILTER}' ...\n")

        # address -> {name, sources: {source: rssi}, adv: last_adv}
        devices = {}
        total_events = 0
        deadline = time.monotonic() + SCAN_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("type") != "event":
                continue
            event = msg.get("event", {})
            items = event.get("add")
            if items is None and isinstance(event, list):
                items = event
            for item in items or []:
                adv = norm_adv(item)
                if adv is None or not adv["address"]:
                    continue
                total_events += 1
                addr = adv["address"].upper()
                d = devices.setdefault(addr, {"name": adv["name"], "sources": {}, "adv": adv})
                if adv["name"] and not d["name"]:
                    d["name"] = adv["name"]
                d["adv"] = adv
                src = adv["source"]
                if adv["rssi"] is not None:
                    prev = d["sources"].get(src)
                    if prev is None or adv["rssi"] > prev:
                        d["sources"][src] = adv["rssi"]

        # ---- report ----
        print(f"heard {total_events} advertisements from {len(devices)} distinct devices\n")

        def matches(addr, d):
            hay = f"{addr} {d['name']}".upper()
            return FILTER in hay

        hits = {a: d for a, d in devices.items() if matches(a, d)}
        if not hits:
            print(f"❌ NO device matching '{FILTER}' was heard by any proxy.")
            # show a few named devices as proof scanning worked
            named = [(a, d) for a, d in devices.items() if d["name"]]
            named.sort(key=lambda kv: max(kv[1]["sources"].values() or [-999]), reverse=True)
            print("\nstrongest named devices currently visible (sanity check):")
            for a, d in named[:15]:
                best_src, best_rssi = max(d["sources"].items(), key=lambda kv: kv[1])
                print(f"  {a}  {d['name'][:28]:28}  {best_rssi:>4} dBm via {pname(best_src)}")
        else:
            print(f"✅ MATCH for '{FILTER}':\n")
            for a, d in hits.items():
                adv = d["adv"]
                print(f"  device: {a}   name={d['name']!r}   connectable={adv.get('connectable')}")
                print(f"    service_uuids: {adv.get('service_uuids')}")
                if adv.get("manufacturer_data"):
                    print(f"    manufacturer_data keys (company IDs): {list(adv['manufacturer_data'].keys())}")
                if adv.get("service_data"):
                    print(f"    service_data keys: {list(adv['service_data'].keys())}")
                print(f"    heard by {len(d['sources'])} proxy(ies), strongest first:")
                for src, rssi in sorted(d["sources"].items(), key=lambda kv: kv[1], reverse=True):
                    print(f"      {rssi:>4} dBm   {pname(src)}   [{src}]")
                print()

        # dump full raw for the wiki / codex
        out = os.environ.get("DUMP_JSON")
        if out:
            with open(out, "w") as fh:
                json.dump(
                    {a: {"name": d["name"], "sources": d["sources"], "adv": d["adv"]} for a, d in devices.items()},
                    fh,
                    indent=2,
                    default=str,
                )
            print(f"(wrote full device dump to {out})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
