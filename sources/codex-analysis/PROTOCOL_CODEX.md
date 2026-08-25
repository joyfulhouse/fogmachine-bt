# FG53850 BLE protocol, derived from `com.spw.mistingapp`

This document is derived only from the jadx Java sources under `sources/decompiled/jadx/sources/com/spw/mistingapp/`. Offsets below are zero-based character offsets. Every protocol character used by this app is single-byte in GB2312, so these character offsets are also byte offsets for valid frames.

## 1. GATT transport

### UUIDs and characteristic roles

- Primary service: `0000ffe0-0000-1000-8000-00805f9b34fb` (`UUID_SERVICE`). The app searches discovered services for this exact UUID in `MistingBLEServiceExecutor.findService()` (`MistingBLEServiceExecutor.java`).
- Serial characteristic: `0000ffe1-0000-1000-8000-00805f9b34fb` (`UUID_NOTIFY`). Despite the constant name, this one characteristic is used in both directions: `findService()` stores FFE1 in `bleGattChar`; `inRun()` calls `setValue(...)` and `writeCharacteristic(bleGattChar)` on it; `BluetoothGattCallback.onCharacteristicChanged()` receives data from it (`MistingBLEServiceExecutor.java`). No second write characteristic is defined or selected anywhere in the class.
- Reads are supported by the callback path (`BluetoothGattCallback.onCharacteristicRead()` forwards a successful read just like a notification), but the app never calls `readCharacteristic()` in this source. Normal responses arrive through `onCharacteristicChanged()` (`MistingBLEServiceExecutor.java`).

### Notification setup

After finding FFE1, `MistingBLEServiceExecutor.findService()` calls `setCharacteristicNotification(characteristic, true)`, then immediately broadcasts `ACTION_GATT_SERVICES_DISCOVERED`. `MistingBLEServiceExecutor.setCharacteristicNotification()` only calls Android's `BluetoothGatt.setCharacteristicNotification(...)`. It does **not** look up a CCCD, write descriptor UUID `00002902-0000-1000-8000-00805f9b34fb`, or call `writeDescriptor()`. The empty `BluetoothGattCallback.onDescriptorWrite()` is only a logger (`MistingBLEServiceExecutor.java`). Thus the app registers locally for characteristic changes but performs no explicit on-wire CCCD descriptor write in the decompiled code. A Bleak client should still use `start_notify(FFE1, callback)`, which lets the platform perform whatever subscription operation the peripheral exposes.

### Encoding, MTU, and write chunking

`MistingBLEServiceExecutor.encoding` is the literal string `"GB2312"`. `inRun()` encodes requests with `strPackSegRequest.getBytes(encoding)`, and `onCharacteristicRead()`, `onCharacteristicChanged()`, and `asyncTryParseBuf()` decode response bytes with the same encoding (`MistingBLEServiceExecutor.java`). All currently defined frame symbols and payloads are ASCII digits/punctuation, whose byte representation is the same in GB2312 and ASCII, but a faithful client should use GB2312 rather than assuming arbitrary UTF-8 text can be sent.

`bleWriteBufSize` is fixed at 20 bytes. `MistingBLEServiceExecutor.inRun()` first coalesces adjacent logical command segments only while their combined Java string length is at most 20, then converts the result to GB2312 and slices the resulting byte array into chunks of at most 20 bytes with `Arrays.copyOfRange(...)`. It writes each slice to FFE1. There is no `requestMtu()` call, no negotiated-MTU callback, and no adaptation of `bleWriteBufSize`; this is classic ATT-default-MTU-safe payload sizing (`MistingBLEServiceExecutor.inRun()`, `MistingBLEServiceExecutor.java`). The class also never explicitly sets the characteristic write type, so Android uses the write type already exposed/defaulted by the discovered characteristic (`MistingBLEServiceExecutor.inRun()`).

### Connect/handshake sequence

The command ID `c` has two distinct jobs: it initiates the Android BLE connection **and**, after discovery, sends a protocol frame.

1. The UI creates a `MistingDevConnectCmd` through `MistingDevCmdFactory.getCommand("c", ...)` and submits it in `FunctionListActivity.sendConnectCmd()` (`FunctionListActivity.java`; `cmd/imp/MistingDevCmdFactory.java`).
2. `MistingBLEServiceExecutor.run()` installs a 10,000 ms command timeout, calls `execStarting()`, recognizes ID `c`, closes any old GATT, and calls `noneSyncConnect(selectedDevice.getAddress())`; it does not write a frame at this point (`MistingBLEServiceExecutor.java`). The 10,000 ms value comes from `AbstractComponentTracker.LINGERING_TIMEOUT`, assigned to `timeoutGattReadWrite` in this class.
3. `noneSyncConnect()` calls `BluetoothDevice.connectGatt(..., TRANSPORT_LE)` on Android 6+, or the older overload on earlier versions (`MistingBLEServiceExecutor.noneSyncConnect()`).
4. A successful `BluetoothGattCallback.onConnectionStateChange()` broadcasts `ACTION_GATT_CONNECTED`. `MistingBLEReciver.onReceive()` responds by scheduling a service-refresh timeout for 10,005 ms and calling `discoverServices()` (`MistingBLEServiceExecutor.java`).
5. `BluetoothGattCallback.onServicesDiscovered()` calls `findService()`. Once FFE0/FFE1 is found and local notification registration is enabled, `findService()` broadcasts `ACTION_GATT_SERVICES_DISCOVERED` (`MistingBLEServiceExecutor.java`).
6. `MistingBLEReciver.onReceive()` now marks the executor connected, invokes the connection listener, and—because the `c` command is still executing—calls `inRun()` (`MistingBLEServiceExecutor.java`).
7. `MistingDevConnectCmd.getCommandString()` returns empty, while inherited `AbstractMistingDevCmd.packRequest()` creates `EE0c0.`. Therefore **`EE0c0.` really is written to FFE1 after GATT discovery**; the earlier connect/discover operations are Android control-plane activity, not protocol text (`cmd/MistingDevConnectCmd.java`; `cmd/AbstractMistingDevCmd.java`; `MistingBLEServiceExecutor.inRun()`). A normal success reply is `EE1c0.` and is parsed by `AbstractMistingDevCmd.unpackResponse()`. There is a connect-specific logic defect in `MistingBLEServiceExecutor.asyncTryParseBuf()`: a nonzero connect return code bypasses its failure branch, and the final-segment path then overwrites the command return code with `0`. Consequently, any syntactically parseable `c` response is treated as successful by this app even if its envelope says failure (`MistingBLEServiceExecutor.asyncTryParseBuf()`).
8. When parsing finishes, the command callback fires. `FunctionListActivity.onCmdFinished()` sees a successful `c` and immediately creates and submits command `0` (query-all), which on its first run normally includes clock synchronization as described in section 4 (`FunctionListActivity.java`).

### Response accumulation and completion

Both successful reads and notifications are copied into broadcasts by `MistingBLEServiceExecutor.broadcastUpdate(String, BluetoothGattCharacteristic)`. `MistingBLEReciver.onReceive()` extracts the raw byte array and passes it to `asyncTryParseBuf()` (`MistingBLEServiceExecutor.java`).

`MistingBLEServiceExecutor.inRun()` resets `readCnt` and a 1,024-byte `readBuf` before sending. `asyncTryParseBuf()` appends each arriving byte array at `readCnt`, decodes the whole accumulated prefix as GB2312, and counts occurrences of the command's end string. Every command returns `"."` from `AbstractMistingDevCmd.getEndString()` (`cmd/AbstractMistingDevCmd.java`). The buffer is considered complete only when the number of periods equals `packedSegSize`, the number of logical request frames coalesced into the current write group. Until then, the method returns and retains the accumulated bytes (`MistingBLEServiceExecutor.asyncTryParseBuf()`).

Once complete, `asyncTryParseBuf()` splits the accumulated response at each period, retaining the period in each substring, and passes each substring to `executingCmd.unpackSegResponse(...)`. This is why a query-all response uses commas between internal blocks but only one final period: it is one logical command response. There is no length-prefix or idle-time delimiter. The fixed buffer is 1,024 bytes, and overflow is handled only by the method's general exception path (`MistingBLEServiceExecutor.asyncTryParseBuf()`).

## 2. Frame format

### Ordinary request

`AbstractMistingDevCmd.packRequest()` constructs every ordinary request as:

```text
offset  width  meaning
0       2      header: "EE"
2       1      phase: "0" (request)
3       1      command ID
4       1      literal "0" (the request-side result/return-code slot)
5       N      command payload from getCommandString()
5+N     1      terminator: "."
```

Exact grammar: `EE` + `0` + `<id:1>` + `0` + `<payload:N>` + `.`. The header, phases, return codes, terminator, one-character ID widths, and comma part separator are declared in `MistingCmdConstants` (`cmd/MistingCmdConstants.java`); the exact concatenation is in `AbstractMistingDevCmd.packRequest()` (`cmd/AbstractMistingDevCmd.java`). The request's offset-4 zero is hard-coded by `packRequest()` and is not derived from command state.

### Ordinary response

`AbstractMistingDevCmd.unpackResponse()` accepts:

```text
offset  width  meaning
0       2      header: "EE"
2       1      phase: "1" (response)
3       1      command ID; must equal the request command ID
4       1      return code: "0" success, "1" failure
5       N      command-specific response payload (possibly empty)
5+N     1      terminator: "."
```

Exact grammar: `EE` + `1` + `<id:1>` + `<rc:1>` + `<payload:N>` + `.`. The parser requires at least six characters, finds the first period at or after offset 5, and passes characters `[5, period)` to `setCommandResult()` only when total response length is greater than six (`AbstractMistingDevCmd.unpackResponse()`, `cmd/AbstractMistingDevCmd.java`). `MistingCmdConstants` defines `0` as success and `1` as failure (`cmd/MistingCmdConstants.java`).

### Query-all response variant

For query-all only, `MistingDevQueryCmd.unpackResponse()` parses a series of blocks:

```text
offset within each block  width  meaning
0                         2      "EE"
2                         1      "1"
3                         1      outer command ID "0"
4                         1      return code
5                         1      subId
6                         N      subcommand payload
6+N                       1      block separator ","
```

The next block starts immediately after the comma. After the last comma, the complete response has one final `.`. Thus the full grammar is `{ EE10<rc><subId><payload>, }+ .`. The parser searches for a comma from offset 5, extracts the sub-ID at offset 5 and payload from offset 6 to the comma, advances past the comma, and loops while it is before the final character (`MistingDevQueryCmd.unpackResponse()`, `cmd/imp/MistingDevQueryCmd.java`). `MistingDevCmdFactory.getTestResponse()` supplies a concrete decompiled test fixture with precisely this shape (`cmd/imp/MistingDevCmdFactory.java`).

### No checksum or CRC

There is **no checksum, CRC, length field, escaping layer, or binary envelope** in the implemented protocol. `AbstractMistingDevCmd.packRequest()` appends only header, phase, ID, literal zero, payload, and period; `MistingDevBatchCmd.packRequest()` merely concatenates those complete frames; `MistingBLEServiceExecutor.inRun()` directly GB2312-encodes and chunks that text. On receive, `AbstractMistingDevCmd.unpackResponse()` and `MistingDevQueryCmd.unpackResponse()` validate header/phase/ID/delimiters and parse payloads, but perform no checksum calculation or comparison (`cmd/AbstractMistingDevCmd.java`; `cmd/imp/MistingDevBatchCmd.java`; `MistingBLEServiceExecutor.java`; `cmd/imp/MistingDevQueryCmd.java`).

## 3. Command catalog

The factory maps IDs `0` through `7`, `+`, and `c` to concrete command classes in `MistingDevCmdFactory.getCommand()` (`cmd/imp/MistingDevCmdFactory.java`). ID `8` is constructed directly as the batch wrapper (`MistingDevBatchCmd` constructor, `cmd/imp/MistingDevBatchCmd.java`).

### `0` — query / running time

Purpose: query all settings, query one setting by sub-ID, and decode running time sub-ID `0` (`MistingDevQueryCmd.getCommandString()`, `setSingleCommandResult()`, and `unpackResponse()`, `cmd/imp/MistingDevQueryCmd.java`).

Request payload:

- Normally the query sub-ID: empty string means query all; one character selects a single item. `subId` defaults to `""` and is returned by `getCommandString()` after the first successful query (`MistingDevQueryCmd` constructor, `setSubId()`, and `getCommandString()`). Therefore a steady-state query-all request is `EE000.`; a single power query is `EE0001.`.
- On the first query for a non-null device ID, the payload is instead `+yyyyMMddHHmmssW`: 1 plus sign, 14 decimal date/time digits, and one weekday digit. Details are in section 4 (`MistingDevQueryCmd.getCommandString()`).

Response payload:

- Single query: `<subId:1><subPayload>`, inside the ordinary response envelope. `setCommandResult()` requires the first payload character to match the requested `subId`, then dispatches the remainder (`MistingDevQueryCmd.setCommandResult()`).
- Query-all: the comma-separated block format from section 2 (`MistingDevQueryCmd.unpackResponse()`).
- Running-time subpayload (`subId 0`): `HHMMSS`, exactly three two-digit decimal fields in practice. Each decoded field is clamped to `0..99` by `checkRunningTimeData()`. `getRunningTime()` always formats each to width 2; `setRunningTime()` slices offsets `0..1`, `2..3`, and `4..5` (`MistingDevCmdDataFormat.getRunningTime()`, `setRunningTime()`, and `checkRunningTimeData()`, `cmd/MistingDevCmdDataFormat.java`). Note that the decompiled length guard mistakenly tests `length < 0`, but the fixed substring calls still require at least six characters.

### `1` — power

Purpose: set power state (`MistingDevPowerCmd.getCommandString()`, `cmd/imp/MistingDevPowerCmd.java`).

- Request payload: one character at payload offset 0 / frame offset 5. **Inverted encoding:** `0` = power ON and `1` = power OFF. This is declared by `Switch_On`/`Switch_Off` and implemented by `MistingDevCmdDataFormat.getPowerStatus()` and `setPowerStatus()` (`cmd/MistingCmdConstants.java`; `cmd/MistingDevCmdDataFormat.java`).
- Response payload: empty; only the envelope return code is used. `MistingDevPowerCmd.setCommandResult()` is empty (`cmd/imp/MistingDevPowerCmd.java`). A query sub-ID `1`, by contrast, returns one power-state character and is decoded by `MistingDevQueryCmd.setSingleCommandResult()`.

### `2` — customization mode

Purpose: select operating profile (`MistingDevCustomizationModeCmd.getCommandString()`, `cmd/imp/MistingDevCustomizationModeCmd.java`).

- Request payload: one character: `0` = always spray, `1` = nimble setting, `2` = advanced setting. Invalid internal values are normalized to `0` when formatting; invalid received values are also normalized to `0` (`MistingCmdConstants.java`; `MistingDevCmdDataFormat.getCustomizationMode()` and `setCustomizationMode()`, `cmd/MistingDevCmdDataFormat.java`).
- Response payload: empty; success/failure is the envelope return code (`MistingDevCustomizationModeCmd.setCommandResult()`). Query sub-ID `2` returns the one-character mode (`MistingDevQueryCmd.setSingleCommandResult()`).

### `3` — weekday enable

Purpose: set one weekday entry (`MistingDevWeekdaySetCmd.getCommandString()`, `cmd/imp/MistingDevWeekdaySetCmd.java`).

- Request payload, width 2: `[0] weekdayIndex`, a single decimal digit `0..6`; `[1] enabled`, where **`0` = enabled and `1` = disabled**. `MistingDevInfo.checkWeekDayIndex()` clamps model indexes to `0..6`; `MistingDevCmdDataFormat.getSpecWeekDay()` implements the inverted bit (`MistingDevInfo.java`; `cmd/MistingDevCmdDataFormat.java`).
- Weekday ordering is the model array's index order `0..6`. The Java source does not name these seven indexes. The calendar-to-device weekday conversion used for clock sync is `(Calendar.DAY_OF_WEEK + 5) % 7`, which produces Monday `0` through Sunday `6` (`MistingDevQueryCmd.getCommandString()`).
- Response payload: one decimal character containing the weekday index acknowledged. `MistingDevWeekdaySetCmd.setCommandResult()` requires exactly one character and stores it as `backWeekDay` (`cmd/imp/MistingDevWeekdaySetCmd.java`).
- Query sub-ID `3` payload: exactly seven inverted enable characters, indexes 0 through 6. `setAllWeekDay()` requires length 7 and `getAllWeekDays()` emits all seven (`MistingDevCmdDataFormat.setAllWeekDay()` and `getAllWeekDays()`).

### `4` — time-customizable switch

Purpose: enable or disable use of customized time windows (`MistingDevTimeCustomizableCmd.getCommandString()`, `cmd/imp/MistingDevTimeCustomizableCmd.java`).

- Request payload: one character, **`0` = enabled and `1` = disabled** (`MistingDevCmdDataFormat.getTimeCustomizable()` and `setTimeCustomizable()`, `cmd/MistingDevCmdDataFormat.java`).
- Response payload: empty (`MistingDevTimeCustomizableCmd.setCommandResult()`). Query sub-ID `4` returns the same one-character inverted boolean (`MistingDevQueryCmd.setSingleCommandResult()`).

### `5` — frequency-customizable switch

Purpose: enable or disable customized work/pause cycles (`MistingDevFreqCustomizableCmd.getCommandString()`, `cmd/imp/MistingDevFreqCustomizableCmd.java`).

- Request payload: one character, **`0` = enabled and `1` = disabled** (`MistingDevCmdDataFormat.getFreqCustomizable()` and `setFreqCustomizable()`, `cmd/MistingDevCmdDataFormat.java`).
- Response payload: empty (`MistingDevFreqCustomizableCmd.setCommandResult()`). Query sub-ID `5` returns the same one-character inverted boolean (`MistingDevQueryCmd.setSingleCommandResult()`).

### `6` — customized time-window entry

Purpose: set one scheduled time window (`MistingDevTimeSetCmd.getCommandString()`, `cmd/imp/MistingDevTimeSetCmd.java`).

Request payload is exactly 11 characters, produced/consumed by `MistingDevCmdDataFormat.getCustomizedTime()` / `setCustomizedTime()` (`cmd/MistingDevCmdDataFormat.java`):

```text
payload offset  width  field
0               2      sequence/index, zero-padded decimal
2               1      enabled: 0 = enabled, 1 = disabled
3               2      from hour
5               2      from minute
7               2      to hour
9               2      to minute
```

The normal outbound model range is sequence `00..09` for advanced devices (10 entries) and `00..03` for nimble time schedules (4 entries); these capacities are established by `MistingDevInfo.Max_AdvancedCustomizedData`, `Max_NimbleCustomizationTime`, `MistingAppGlobal.getAdvDevInfo()`, and `getNimbleDevInfo()` (`MistingDevInfo.java`; `MistingAppGlobal.java`). Model lookup clamps indexes to the configured capacity in `MistingDevInfo.checkCustomizedTimeDataIndex()`.

Outbound time getters normalize `from` to `00:00..23:58` (total minutes `0..1438`) and `to` to `00:01..23:59` (total minutes `1..1439`) in `CustomizedTime.adjustFromTime()` / `adjustToTime()` (`MistingDevInfo.java`). All fields are formatted to width 2 by `getCustomizedTime()`. The inbound decoder itself only clamps each hour/minute field independently to `0..99` via `checkSettingHour()` and `checkSettingMinute()`, so it is less strict than the outbound model (`MistingDevCmdDataFormat.setCustomizedTime()`, `cmd/MistingDevCmdDataFormat.java`). If no model entry exists, the builder emits the requested index plus disabled `1` and `00000001` (00:00 to 00:01) (`MistingDevCmdDataFormat.getCustomizedTime()`).

Response payload: exactly two decimal characters, the acknowledged sequence/index. `MistingDevTimeSetCmd.setCommandResult()` rejects any other width (`cmd/imp/MistingDevTimeSetCmd.java`). Query sub-ID `6` returns one complete 11-character entry and dispatches to `setCustomizedTime()` (`MistingDevQueryCmd.setSingleCommandResult()`).

### `7` — customized frequency/work-pause entry

Purpose: set one repeated mist-work/pause cycle (`MistingDevFreqSetCmd.getCommandString()`, `cmd/imp/MistingDevFreqSetCmd.java`).

Request payload is exactly 13 characters, produced/consumed by `MistingDevCmdDataFormat.getCustomizedFreq()` / `setCustomizedFreq()` (`cmd/MistingDevCmdDataFormat.java`):

```text
payload offset  width  field
0               2      sequence/index, zero-padded decimal
2               1      enabled: 0 = enabled, 1 = disabled
3               5      work duration in seconds, zero-padded decimal
8               5      pause duration in seconds, zero-padded decimal
```

Normal outbound work duration is clamped to `3..84600` seconds and pause duration to `5..84600` seconds by `CustomizedFreq.getWorkTime()` / `getPauseTime()` (`MistingDevInfo.java`). The model uses 10 frequency entries (`00..09`) for advanced settings and one (`00`) for nimble settings, established by `MistingDevInfo.Max_AdvancedCustomizedData`, `Max_NimbleCustomizationFreq`, `MistingAppGlobal.getAdvDevInfo()`, and `getNimbleDevInfo()` (`MistingDevInfo.java`; `MistingAppGlobal.java`). Model lookup clamps indexes in `MistingDevInfo.checkCustomizedFreqDataIndex()`. The decoder stores the five-digit integers without immediate clamping, but subsequent getters impose those ranges (`MistingDevCmdDataFormat.setCustomizedFreq()`; `MistingDevInfo.CustomizedFreq`). Missing entries are emitted disabled with work `00003` and pause `00005` (`MistingDevCmdDataFormat.getCustomizedFreq()`).

Response payload: exactly two decimal characters, the acknowledged sequence/index (`MistingDevFreqSetCmd.setCommandResult()`, `cmd/imp/MistingDevFreqSetCmd.java`). Query sub-ID `7` returns one complete 13-character entry (`MistingDevQueryCmd.setSingleCommandResult()`).

### `8` — batch (app-side composite only)

Purpose: group setting commands. It is **not sent as an `EE080...` protocol frame**. `MistingDevBatchCmd.packRequest()` concatenates each child command's already complete request; `packSegRequest(i)` returns a child request; `getCmdSegSize()` returns the number of children (`cmd/imp/MistingDevBatchCmd.java`). The BLE UI path actually submits each child separately in sequence from `FunctionListActivity.batchSendCustomizationCmds()` and `onCmdFinished()` (`FunctionListActivity.java`).

Consequently, there is no ID-8 request payload or ID-8 response payload. A conceptual batch request is a concatenation such as `EE0202.EE03000....`, and its response is the corresponding concatenation of ordinary period-terminated responses. `MistingDevBatchCmd.unpackResponse()` splits at each period and delegates each child response to that child's parser (`cmd/imp/MistingDevBatchCmd.java`). `MistingDevBatchSimplifiedCmd` changes only app metadata (`isSimplifiedNimble`), not wire format (`cmd/imp/MistingDevBatchSimplifiedCmd.java`).

### `c` — connect protocol command

Purpose: verify/initialize the application protocol after the Android GATT connection and discovery sequence (`MistingBLEServiceExecutor.run()` and `MistingBLEReciver.onReceive()`, `MistingBLEServiceExecutor.java`).

- Request payload: empty; full request `EE0c0.` (`MistingDevConnectCmd.getCommandString()`, `cmd/MistingDevConnectCmd.java`; `AbstractMistingDevCmd.packRequest()`).
- Response payload: empty; ordinary expected response `EE1c<rc>.`. `MistingDevConnectCmd.setCommandResult()` is empty (`cmd/MistingDevConnectCmd.java`). Although the base parser records the envelope return code, the BLE executor's connect-specific condition ultimately treats any syntactically valid response as success and overwrites the code with `0` (`AbstractMistingDevCmd.unpackResponse()`, `cmd/AbstractMistingDevCmd.java`; `MistingBLEServiceExecutor.asyncTryParseBuf()`).

### `+` — datetime/sync command ID

The constants and factory define `+` as its own command ID. `MistingDevSyncCCmd.getCommandString()` is empty, so if instantiated directly through `MistingDevCmdFactory.getCommand("+", ...)`, its ordinary request is `EE0+0.` and ordinary response shape is `EE1+<rc>[payload].`; its `unpackResponse()` calls the base parser and then forcibly sets the stored return code to success (`cmd/imp/MistingDevCmdFactory.java`; `cmd/imp/MistingDevSyncCCmd.java`; `cmd/AbstractMistingDevCmd.java`). No production call site in the inspected app constructs this direct command.

The clock data actually sent by the production path is not the payload of a direct `+` frame. It is `+yyyyMMddHHmmssW` embedded as the payload of the first command-`0` request (`MistingDevQueryCmd.getCommandString()`, `cmd/imp/MistingDevQueryCmd.java`), as detailed next. Query-all decoding also recognizes `+` as a possible response sub-ID and stores its subpayload verbatim as `dateTimeInDev` (`MistingDevQueryCmd.setSingleCommandResult()`; `MistingDevCmdDataFormat.setDateTimeInDev()`).

## 4. Query-all decoding

A new `MistingDevQueryCmd` starts with an empty `subId`, which means query all (`MistingDevQueryCmd` constructor, `cmd/imp/MistingDevQueryCmd.java`). Its response is one outer command-`0` response comprising repeated `EE10<rc><subId><payload>,` blocks followed by a period. `MistingDevQueryCmd.unpackResponse()` validates every block's `EE`, response phase `1`, outer ID `0`, and return code; records each sub-ID; and sends its payload to `setSingleCommandResult()` (`cmd/imp/MistingDevQueryCmd.java`).

Sub-ID mapping from `MistingDevQueryCmd.setSingleCommandResult()` is:

| subId | payload width | meaning |
|---|---:|---|
| `+` | not width-validated | device datetime string, stored verbatim |
| `0` | 6 | running time `HHMMSS` |
| `1` | 1 | power (`0` on, `1` off) |
| `2` | 1 | mode (`0` always, `1` nimble, `2` advanced) |
| `3` | 7 | Monday-through-Sunday enable characters (`0` enabled, `1` disabled) |
| `4` | 1 | time-customizable (`0` enabled, `1` disabled) |
| `5` | 1 | frequency-customizable (`0` enabled, `1` disabled) |
| `6` | 11 | one time-window entry (`SSBHHMMHHMM`) |
| `7` | 13 | one work/pause entry (`SSBWWWWWPPPPP`) |

The widths and conversions come from `MistingDevQueryCmd.setSingleCommandResult()` and the corresponding setters in `MistingDevCmdDataFormat` (`cmd/imp/MistingDevQueryCmd.java`; `cmd/MistingDevCmdDataFormat.java`). Multiple `6` and `7` blocks may occur, distinguished by their two-character sequence prefix; each is stored into the model by its embedded index (`MistingDevCmdDataFormat.setCustomizedTime()` / `setCustomizedFreq()` and `MistingDevInfo.setCustomizedTime()` / `setCustomizedFreq()`).

The decompiled factory test fixture is:

```text
EE10002445-1,EE10010,EE10022,EE10030101100,EE10040,EE10051,
EE10060453672335,EE1007030003586400,.
```

(shown on two lines here only for readability). It demonstrates that every block repeats the complete `EE10<rc>` prefix, each ends in a comma, and only the aggregate ends in a period (`MistingDevCmdFactory.getTestResponse()`, `cmd/imp/MistingDevCmdFactory.java`).

### First-query datetime push

`MistingDevQueryCmd` keeps a static `timeSetSuccForDev` map keyed by device ID. In `getCommandString()`, if the ID is non-null and its count is absent/zero, the method returns:

```text
+yyyyMMddHHmmssW
```

`yyyyMMddHHmmss` is generated using `SimpleDateFormat(..., Locale.ENGLISH)`. `W` is `(GregorianCalendar.DAY_OF_WEEK + 5) % 7`, i.e. Monday `0`, Tuesday `1`, ..., Sunday `6` (`MistingDevQueryCmd.getCommandString()`, `cmd/imp/MistingDevQueryCmd.java`). Since the command object still has outer ID `0` and empty `subId`, inherited packing produces `EE000+yyyyMMddHHmmssW.`.

For each successful block parsed from a query-all response, `unpackResponse()` increments the map count for that device. Therefore later query objects return the actual empty sub-ID and send `EE000.` (`MistingDevQueryCmd.unpackResponse()` and `getCommandString()`). This is a clock-sync-bearing query-all request, not a separately framed `+` command. `FunctionListActivity.onCmdFinished()` automatically submits this first query after successful `c` (`FunctionListActivity.java`).

## 5. Practical notes for an independent third-party client (e.g. Python/Bleak + Home Assistant)

- Connect to FFE0, subscribe to FFE1, send `EE0c0.`, wait for `EE1c0.`, then send query-all. This order follows `MistingBLEServiceExecutor.run()`, `MistingBLEReciver.onReceive()`, `findService()`, and `inRun()` (`MistingBLEServiceExecutor.java`). Because the Android source omits an explicit CCCD write, use the BLE library's standard notification subscription API rather than copying that omission.
- Keep outbound ATT payloads at 20 bytes unless deliberately negotiating and testing a larger MTU. Split the **GB2312-encoded byte array**, not Unicode character indexes. The app's exact behavior is fixed 20-byte slicing and no MTU negotiation (`MistingBLEServiceExecutor.inRun()`). Long 6/7/query-with-clock requests are therefore allowed to span writes; the device protocol parser is expected to reassemble the byte stream until `.`.
- Serialize writes. On Android API 30 and below, the app polls private GATT `mDeviceBusy` and sleeps 10 ms while busy, up to the overall timeout. On API 31+, each busy check simply sleeps 3 ms and reports not busy. It does not wait for `onCharacteristicWrite()` and does not actually use its declared `bleWriteSpanTime = 10` field (`MistingBLEServiceExecutor.isDeviceBusy()`, `inRun()`, and `BluetoothGattCallback.onCharacteristicWrite()`). A robust Bleak implementation should await each library write and avoid overlapping commands.
- Allow approximately 10 seconds for a command response: `timeoutGattReadWrite` is 10,000 ms and `run()` schedules `stopRun()` at that deadline (`MistingBLEServiceExecutor.run()` / `stopRun()`; `AbstractComponentTracker.LINGERING_TIMEOUT`). The BLE executor has no command-level retransmission loop. On discovery timeout it attempts a GATT service-cache refresh; on BLE error it refreshes and fails the active command, and after three refresh errors it cycles the Android adapter (`MistingBLEReciver.onReceive()` and `refreshServices()`, `MistingBLEServiceExecutor.java`). These recovery actions are app/platform behavior, not wire protocol messages.
- The UI's automatic polling is every 30 seconds after a successful query and every 5 seconds after a failed query; that is polling/retry policy, not a device-mandated delay (`FunctionListActivity.AutoQueryIntervals`, `AutoQueryUnsuccessIntervals`, `checkQueryMessage()`, and `onCmdFinished()`, `FunctionListActivity.java`). The separate classic-Bluetooth executor has a 3-second spacing rule, but the BLE executor's `execSpanTime` is zero and unused (`MistingDevCmdExecutor.sendRequestAndGetResponse()`, `MistingDevCmdExecutor.java`; fields and `inRun()`, `MistingBLEServiceExecutor.java`). Do not incorrectly impose the classic RFCOMM delay on BLE.
- Accumulate notifications until the expected number of periods arrives. For one request, that normally means the first `.`. Do not split query-all on commas as independent BLE requests: commas delimit its internal blocks and the final period terminates the whole response (`MistingBLEServiceExecutor.asyncTryParseBuf()`; `MistingDevQueryCmd.unpackResponse()`). Consider applying your own maximum-buffer bound; the app uses 1,024 bytes (`MistingBLEServiceExecutor.ResponseBufferSize`, `readBuf`, and `asyncTryParseBuf()`).
- Use GB2312 for fidelity. Present payloads are ASCII-safe, but decoding arbitrary bytes as UTF-8 is not what the app does (`MistingBLEServiceExecutor.onCharacteristicChanged()`, `inRun()`, and `asyncTryParseBuf()`).
- There are no water-level or temperature sensor characteristics or commands in this protocol implementation. `MistingBLEServiceExecutor.findService()` recognizes only FFE0 and FFE1; `MistingCmdConstants` defines only IDs `0..8`, `c`, and `+`; `MistingDevCmdFactory.getCommand()` maps no sensor command; and `MistingDevQueryCmd.setSingleCommandResult()` has no water/temperature sub-ID (`MistingBLEServiceExecutor.java`; `cmd/MistingCmdConstants.java`; `cmd/imp/MistingDevCmdFactory.java`; `cmd/imp/MistingDevQueryCmd.java`). `MistingDevInfo` stores runtime, power, modes, weekdays, scheduling switches, time windows, frequency cycles, and device datetime, but no water-level or temperature field (`MistingDevInfo.java`, class fields and accessors).

### Worked wire examples

1. **Power ON**

   Request: `EE0100.` (`AbstractMistingDevCmd.packRequest()` plus `MistingDevPowerCmd.getCommandString()`)

   ```text
   EE | 0 | 1 | 0 | 0 | .
   hdr  req  id  slot  ON  end
   ```

   Success response: `EE110.` (`AbstractMistingDevCmd.unpackResponse()`; `MistingDevPowerCmd.setCommandResult()`)

   ```text
   EE | 1 | 1 | 0 | .
   hdr  rsp  id  ok  end
   ```

   The adjacent zeros in the request are distinct: frame offset 4 is the hard-coded request slot, while frame offset 5 is the inverted power value `0` = ON (`cmd/AbstractMistingDevCmd.java`; `cmd/MistingDevCmdDataFormat.java`).

2. **Set frequency entry 03 enabled, work 35 s, pause 8,640 s**

   Request: `EE0700300003508640.` (`MistingDevFreqSetCmd.getCommandString()`; `MistingDevCmdDataFormat.getCustomizedFreq()`)

   ```text
   EE | 0 | 7 | 0 | 03 | 0 | 00035 | 08640 | .
   hdr  req  id  slot seq  on  work-s  pause-s  end
   ```

   This is 19 bytes in GB2312/ASCII, so it fits one 20-byte app write (`MistingBLEServiceExecutor.inRun()`). Success response: `EE17003.` = `EE | 1 | 7 | 0 | 03 | .`; the two-character payload acknowledges index 03 (`MistingDevFreqSetCmd.setCommandResult()`).

3. **Steady-state query-all and one returned block**

   Request: `EE000.` = `EE | 0 | 0 | 0 | <empty subId> | .` (`MistingDevQueryCmd.getCommandString()` after clock sync; `AbstractMistingDevCmd.packRequest()`).

   A power-ON block inside the aggregate response is `EE10010,`:

   ```text
   EE | 1 | 0 | 0 | 1 | 0 | ,
   hdr  rsp  id  ok  sub power part-end
   ```

   Here outer ID `0` means query, sub-ID `1` means power, and subpayload `0` means ON. A minimal illustrative complete aggregate containing only that block is `EE10010,.`; real query-all responses concatenate the other blocks before the one final period (`MistingDevQueryCmd.unpackResponse()` and `setSingleCommandResult()`; `MistingDevCmdFactory.getTestResponse()`).
