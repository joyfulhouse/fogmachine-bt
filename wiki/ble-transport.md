# BLE transport (GATT, connect, chunking, notifications)

Purpose: how bytes actually move between app and device, independent of the
command semantics ([ble-protocol](ble-protocol.md)).
Status: **verified from source** (`com.spw.mistingapp.MistingBLEServiceExecutor`), pending one live confirmation.

## GATT profile

| Role | UUID | Source |
|---|---|---|
| Service | `0000ffe0-0000-1000-8000-00805f9b34fb` | `MistingBLEServiceExecutor.UUID_SERVICE` |
| Write **and** Notify characteristic | `0000ffe1-0000-1000-8000-00805f9b34fb` | `MistingBLEServiceExecutor.UUID_NOTIFY` |

A single characteristic (`FFE1`) is used for both directions — the classic
HM-10 transparent-serial pattern. `findService()` walks the discovered services,
matches `FFE0`, then within it matches `FFE1`, stores it as `bleGattChar`, and
enables notifications on it.

## Connection sequence

From `MistingBLEServiceExecutor.run()` / `noneSyncConnect()`:

1. `run()` special-cases `CmdId_Connect`: it calls `connectGatt()` and returns
   **without writing yet** — but the connect command stays the *executing*
   command.
2. `remoteDevice.connectGatt(ctx, autoConnect=false, callback, TRANSPORT_LE)`
   (SDK ≥ 23). `TRANSPORT_LE` = 2.
3. On `STATE_CONNECTED` → `discoverServices()` (with a refresh-on-timeout guard).
4. On services discovered → `findService()` locates `FFE0`/`FFE1`, calls
   `setCharacteristicNotification(FFE1, true)`, then the receiver calls
   `inRun()` for the still-pending connect command.
5. **`inRun()` now flushes the connect frame `EE0c0.` on-wire**, and the device
   replies `EE1c<rc>.`. So there *is* a lightweight post-discovery handshake
   (no auth/login, no secret). After that the device is ready. The app then
   auto-sends the first query (`EE000+datetime.`, clock sync) — see
   [ble-protocol](ble-protocol.md). ⚠️ Corrected via Codex cross-check; an
   earlier draft here wrongly said "no bytes are sent".

⚠️ The app calls `setCharacteristicNotification()` (local flag) but does **not**
explicitly write the CCCD descriptor `0x2902`. HM-10 modules typically push
notifications anyway. A correct client (Bleak / HA) should use `start_notify`,
which *does* write the CCCD — HM-10 tolerates this. Confirm on first live test.

- No bonding, no pairing, no encryption anywhere.
- Text encoding is **GB2312** (`encoding` field). All protocol bytes are ASCII
  digits/letters/punctuation, so GB2312 == ASCII for this traffic.

## Writing (request path)

From `inRun()`:

- Requests are built as an ASCII string (see [ble-protocol](ble-protocol.md)),
  encoded GB2312, then written to `FFE1` in **chunks of ≤ `bleWriteBufSize` = 20
  bytes** (`characteristic.setValue(chunk)` + `gatt.writeCharacteristic()`),
  looping until the whole request is sent.
- Batch/composed commands are additionally packed so that multiple short
  sub-requests can share a 20-byte write when they fit.
- Default write type (write-with-response); `onCharacteristicWrite` only logs.
- A pre-write busy-wait polls `mDeviceBusy` (reflection) on API ≤ 30, or sleeps
  ~3 ms on newer Android. `bleWriteSpanTime` = 10 ms nominal spacing.

## Reading (response path)

From `asyncTryParseBuf()` (fed by `onCharacteristicChanged`):

- Notification payloads are appended into a 1024-byte `readBuf`.
- The buffer is considered complete when the count of end-terminators (`.`)
  equals `packedSegSize` (the number of sub-commands sent). Only then is it
  parsed. So **responses can arrive across multiple notifications** and must be
  reassembled until the expected number of `.` terminators is seen.
- `ResponseBufferSize` = 1024.

## Practical client recipe (HA / Bleak)

1. Connect (via ESPHome proxy) with `bleak-retry-connector`.
2. `start_notify(FFE1, cb)`.
3. **Send the connect handshake `EE0c0.`** and wait for `EE1c0.`.
4. Write each ASCII request to `FFE1` in ≤20-byte chunks (write-with-response).
5. In the notify callback, accumulate bytes until you see the expected number of
   `.` terminators (1 for a single command), then decode.
5. Idle timeout / retry: the app uses a ~coarse read/write timeout and refreshes
   GATT (toggles the adapter after 3 consecutive errors) — a proxy client should
   instead rely on retry-connector + reconnect. See
   [ha-proxy-coverage](ha-proxy-coverage.md) for why connections here are
   marginal.
