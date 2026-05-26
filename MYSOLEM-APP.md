# MySolem App — Features & Protocol Mapping

This document captures everything we know about the **MySolem Android/iOS app**
behavior and how it maps to the BL-IP BLE protocol. Used as the planning
backlog for further reverse engineering and Home Assistant integration work.

> Last updated: 2026-05-26 (after **five** MySolem snoop captures — see
> [`SNOOP-2026-05-25.md`](./SNOOP-2026-05-25.md),
> [`SNOOP-2026-05-25-run2.md`](./SNOOP-2026-05-25-run2.md),
> [`SNOOP-2026-05-25-run3.md`](./SNOOP-2026-05-25-run3.md),
> [`SNOOP-2026-05-25-run4.md`](./SNOOP-2026-05-25-run4.md) and
> [`SNOOP-2026-05-26-run5.md`](./SNOOP-2026-05-26-run5.md) for raw analysis).
>
> **Status**: protocol reverse engineering for everything MySolem exposes
> is now considered **complete** apart from the explicit non-goals
> (battery, Security key, BL6IP layout, station rename).

---

## 1. What the MySolem app can do

The app talks to a single BL-IP controller via BLE and exposes the following
features. Confirmed by user observation on Android + decoded BLE snoop log.

### 1.1 Programs

The controller exposes **3 programs** in the MySolem UI, but the firmware
actually reserves **12 program slots** (slots 4–12 are zero-padded and
unused). Each program has:

| Field | Type | Size | Notes |
|---|---|---|---|
| `name` | ASCII string | 16 bytes (null-padded) | Default `"Program A"`, `"Program B"`, `"Program C"` |
| `water_budget` | uint8 | 1 byte | Percentage (default `0x64`=100, range 0–200%) |
| `frequency_type` | uint8 | 1 byte | See §1.3 table |
| `dow_bitmap` | uint8 | 1 byte | Days-of-week bitmap (Custom mode only). `0x7f` = all 7 days otherwise. |
| `period_days` | uint8 | 1 byte | Used when `frequency_type` is Interval/Weekly etc. |
| `days_to_next` | uint8 | 1 byte | Days from save time until first firing. Effective "start date" = save_date + days_to_next. |
| `last_modified` | day/month/year | 4 bytes | When MySolem last wrote the program. NOT the start date. |
| `start_times` | uint16 × up-to-8 | 16 bytes | **Minutes since midnight**, BE16. Up to 8 per program. Sentinel `0x05a0` for unused slots. *(Decoded in run 2 capture.)* |
| `station_durations` | uint16-ish | 16 bytes | Per-station duration in seconds, BE16. Position in array indicates which station. Layout still partially decoded. |
| (schedule via `0x35`) | unknown | — | Returns 24 zero frames in all captures so far. Purpose unclear — might be unrelated to start times. |

### 1.3 Frequency types — COMPLETE

All 8 MySolem frequency labels map to only 5 distinct firmware codes,
disambiguated by the other fields:

| `FREQ_TYPE` (byte 4) | MySolem labels | How to detect each label |
|---|---|---|
| `0x00` | **Daily** or **Custom** | If `DOW_BITMAP = 0x7f` → Daily, otherwise Custom (and the bitmap tells you which weekdays) |
| `0x01` | **Even days** | — |
| `0x02` | **Odd days** (Exclude 31st OFF) | — |
| `0x03` | **Odd days** (Exclude 31st ON) | Same UI label as `0x02`, differs only by toggle |
| `0x04` | **Every 2 days** / **Every 3 days** / **Weekly** / **Interval** | `PERIOD` in byte 6: 2/3 → "Every N days", 7 → "Weekly", anything else → "Interval" |

DOW_BITMAP bit ordering: **bit 0 = Monday, bit 6 = Sunday** (ISO-like).
`0x7f` = all 7 days.

The "Exclude 31st" toggle is encoded as a separate top-level code (`0x02`
vs `0x03`), not as a bit flag.

### 1.2 Station ↔ Program assignment & per-station duration

Each station is bound to **exactly one program**, with a duration that is
specific to that (station, program) pair.

**Decoded in run 3** — see [`SNOOP-2026-05-25-run3.md`](./SNOOP-2026-05-25-run3.md)
§1 for the full evidence.

Stored in program-data row 02 (opcode `37 11 02 [SLOT] ...`), 16 bytes:

```
[STN1:3] [STN2:3] [STN3:3] [STN4:3] [STN5:3] [PAD:1]
```

Each `STNk` = `[00] [duration_hi] [duration_lo]` (3 bytes, BE16 seconds).
`00 00 00` means "this station is not assigned to this program".

Up to **5 stations** in this row. BL6IP probably spills into row 03 (always
zero in BL2IP captures), to be confirmed.

### 1.5 Monthly water budget

Separate from program-level water budget. The controller stores **12 monthly
multipliers** (Jan..Dec) read/written via opcodes `0x41`/`0x3f`. All-100%
(`0x0064`) by default.

### 1.6 Information screen (MySolem)

From the user-supplied screenshot of MySolem's "Information" page, the app
exposes the following metadata about the controller:

| Field | Value (observed) | Source |
|---|---|---|
| Default name | `BL2IP-D5AA7E` | `0f 00` read (ASCII at offset 3) |
| Software version | `5.1.7` | TBD — possibly inside the `0f 00` response trailing bytes, or `0xe3` extended ID |
| Model | `BL-IP` | Implicit from name prefix |
| Stations names | "Station 1", "Station 2" | TBD opcode — likely a separate read/write per station |
| Location | (custom string) | TBD — user-set metadata, app-only or stored on device |
| Monthly water budgets | 12 values | `0x41` read / `0x3f` write |
| Backup / Restore | — | Implemented client-side in MySolem (just bulk read/write of the configuration opcodes already known) |
| Erase programs and durations | — | Likely a `2f`/`37` write batch with zero payloads (the all-zero rows of slots `0x12+` look exactly like this) |
| **Security key** | (off in this capture) | Application-level auth feature — **not yet mapped**. See §1.5. |

### 1.7 Security key (NOT mapped)

MySolem allows setting a "Security key" on the controller. When enabled,
the app likely prepends an authentication handshake (probably a known
opcode with the key as payload) before each control command, and the
controller rejects writes from clients that don't authenticate.

We have **not captured this flow** — the user does not have it enabled. If
the integration ever encounters a controller with the key set, control
commands will silently fail until we add support. Documenting it here so
we don't forget; intentional non-goal for now.

### 1.8 Signal strength (RSSI)

MySolem also displays a Bluetooth signal level indicator. This is **not** an
opcode in the SOLEM protocol — RSSI is measured by the receiving radio (the
phone in MySolem's case, or the HA Bluetooth proxy in our case) on every
advertising packet it sees. **No device interaction required**.

In Home Assistant:
- `BluetoothServiceInfoBleak.rssi` from the discovery cache, or
- `bluetooth.async_last_service_info(...).rssi` for the latest value.

Implementation cost is ~10 lines (a `SensorEntity` with `device_class:
signal_strength`, `unit: 'dBm'`, `state_class: measurement`). Doesn't even
need a BLE connection — it's available even when the device is sleeping but
still advertising.

### 1.9 Manual actions

| Action | Status | Command |
|---|---|---|
| Start single station, custom duration | ✅ Confirmed | `31 05 12 [STN] 00 [SEC:BE16]` |
| Start all stations, custom duration | ✅ Confirmed | `31 05 11 00 00 [SEC:BE16]` |
| Stop manual watering | ✅ Confirmed | `31 05 15 00 ff 00 00` |
| Status read | ✅ Confirmed | `3b 00` (the legacy `3105 a0 0001 0000` is NOT required) |
| **Run program N on demand** | ✅ Confirmed (run 2, byte-level via tshark) | `31 05 14 00 0N 00 00` — N at byte 4 (BE16). 1 → A, 2 → B, 3 → C |

---

## 2. Protocol opcode table

Frame format: `[OPCODE:1] [LEN:1] [PAYLOAD:LEN]`. Responses use opcode =
request + 1.

| Req | Resp | Type | Purpose | Implementation status |
|---|---|---|---|---|
| `0x0f` | `0x10` | read | Device info (MAC + model name, e.g. `"BL2IP-D5AA7E"`) | Not implemented |
| `0xe3` | `0xe4` | read | Extended ID / serial | Not implemented |
| `0xf7` | `0xf8` | read | Flags / unknown (3 bytes, all zero in capture) | Not implemented |
| `0x03` | `0x04` | write | Set/sync timestamp; byte 3 candidate for battery | Not implemented |
| `0x31` | `0x32` | write | Start watering / stop (legacy `3105 ...`) | ✅ Implemented |
| `0x35` | `0x36` | read | All schedule start times (24 frames) | Not implemented |
| `0x37` | `0x38` | write | Program data row | Not implemented |
| `0x39` | `0x3a` | read | All programs (12 slots × 7 rows = 84 frames) | Not implemented |
| `0x3b` | `0x3c` | write | Commit + status refresh (3-packet response) | ✅ Implemented (as the existing commit) |
| `0x3f` | `0x40` | write | Monthly water budget | Not implemented |
| `0x41` | `0x42` | read | Monthly water budget | Not implemented |
| `0x2f` | `0x30` | write | Program name | Not implemented |

## 3. Status notification (the 3-packet response)

Every `3b 00` write triggers 3 notifications.

### Packet 1 (sub-status `0x02`) — current state

```
3c 10 02 [MODE] 00 aa aa aa 00 [STN_ACTIVE] [B0] [B1] 10 [TIMER:BE16] 10 00 00
```

- `MODE`: `0x40` idle, `0x41` all stations active, `0x42` single station
  active, `0x02` programmed-off.
- `STN_ACTIVE`: `0x00` when idle, `0x01` when a station is running.
- `B0`, `B1` (bytes 10 and 11): **dynamic** across captures. **Strong
  candidate for battery level**. See [`SNOOP-2026-05-25.md`](./SNOOP-2026-05-25.md)
  §4 for evidence.
- `TIMER:BE16`: remaining seconds on the active timer.

### Packet 2 (sub-status `0x01`) — UNKNOWN, currently discarded

Always `3c 10 01 10 00 00 10 00 00 10 00 00 10 00 00 10 00 00 00 00 00` in
captures. May contain configuration when programs are active — needs
captures with running programs.

### Packet 3 (sub-status `0x00`) — UNKNOWN, currently discarded

Always all zeros in captures.

## 4. MySolem session flow (typical)

When the app connects, it performs this sequence:

1. `0f 00` — read device info (MAC + name).
2. `e3 00` — read extended ID.
3. `f7 00` — read flags.
4. `3b 00` — read status.
5. `03 06 00 ...` — sync timestamp (phone time → device).
6. `41 00` — read monthly water budget.
7. `39 00` — read all 12 program slots (84 frames back).
8. `35 00` — read all schedules (24 frames back).

…then it idles until the user issues an action.

**Important**: this session-start sequence implicitly proves that:
- The device clock needs to be synced from outside (controller has no NTP).
- Programs, schedules and budgets are all read in one shot at startup,
  meaning **MySolem doesn't poll continuously** — it reads once and trusts
  the cached state.

## 5. Open questions

- **Battery encoding**: byte 10 of status packet 1 is the strongest
  candidate (was `58` in Aug 2025, `4d` in May 2026 — consistent with
  battery discharge). Date-sync byte 3 (`0x7e`) is constant across both
  May captures so likely NOT battery. Needs long-term tracking.
- ~~**Days-of-week bitmap**~~ ✅ Decoded in run 5 (bit 0 = Monday).
- **What does opcode `0x35` actually return?** It returned 24 all-zero
  frames in all 5 captures, even with start times configured. Start times
  live inside `0x39`/`0x3a` records, NOT here. Function still unknown
  but not needed for the integration.
- ~~**Station → program assignment**~~ ✅ Decoded in run 3 (see §1.2).
- ~~**Frequency setting**~~ ✅ Fully decoded in run 5 (see §1.3).
- ~~**"Exclude 31st" toggle**~~ ✅ Decoded in run 5: `FREQ_TYPE` switches
  between `0x02` (OFF) and `0x03` (ON).
- **Software version `5.1.7`**: visible in MySolem app but not yet
  positively identified in any BLE response. Likely inside the `0xe3`
  extended ID response trailing bytes.
- **Station names** ("Station 1", "Station 2"): editable from MySolem,
  but the corresponding write opcode is not yet observed.
- **Security key**: intentionally not mapped (see §1.5).

## 6. Action items (live backlog)

### Quick wins (can be done with zero or existing data)
- [ ] **RSSI sensor** — no BLE round-trip needed, reads from HA's discovery
      cache. Available even when controller is asleep but advertising.
- [ ] **`run_program` button (1..3)** — `31 05 14 [N] 00 00 00`. Confirmed
      in run 2 capture.
- [ ] Patch Another-Solem to use `3b 00` for status (drop `3105 a0 ...`).
      Simpler, fewer bytes on the air.
- [ ] Add experimental **battery sensor** reading `status_packet1[10]`,
      clearly labeled "experimental — needs verification".
- [ ] Implement `0x39`/`0x3a` reader → expose per-program sensors
      (`name`, `water_budget`, `active_days`, `durations`, `start_date`).
- [ ] Implement `0x41`/`0x42` reader → expose monthly budget sensor.
- [ ] Add a `device.name`, `device.firmware` reading via `0x0f`.

### Needs new captures (low priority — none required for MVP)
- [ ] Wait a few weeks, capture again → confirm battery byte
      (`status_packet1[10]`) discharge trend.
- [ ] Capture from a **BL6IP** device (6 stations) → confirm row 03
      layout for stations 5–6.
- [ ] Capture: rename "Station 1" → find the station-name write opcode.
- [ ] Capture: enable Security key → map authentication handshake.

### Captures already done ✅
- [x] ~~Assign station 1→Program A, station 2→Program B~~ run 3
- [x] ~~Set various frequencies~~ runs 4 + 5
- [x] ~~Custom mode with specific weekdays~~ run 5
- [x] ~~Even days / Odd days / Exclude 31st toggle~~ run 5
- [x] ~~Multiple intervals (every 4, 10, 30 days)~~ runs 4 + 5

### Write support (needs careful testing)
- [ ] Implement `0x2f`/`0x37`/`0x3f` writes to set programs / schedules /
      budgets from HA.
- [ ] Add safety: always emit final `3b 00` commit, never write opcode
      sequences that weren't observed in MySolem captures.
