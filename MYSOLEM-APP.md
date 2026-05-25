# MySolem App — Features & Protocol Mapping

This document captures everything we know about the **MySolem Android/iOS app**
behavior and how it maps to the BL-IP BLE protocol. Used as the planning
backlog for further reverse engineering and Home Assistant integration work.

> Last updated: 2026-05-25
> Source: direct observation of the Android app + existing reverse engineering
> material in `DISCOVERY.md`, `HOME_ASSISTANT_INTEGRATION_GUIDE.md`, `hacking/`.

---

## 1. What the MySolem app can do

The app talks to a single BL-IP controller via BLE and exposes the following
features. (Confirmed by user observation on Android.)

### 1.1 Programs

The controller stores **up to 3 named programs**. Each program has:

| Field | Type | Notes |
|---|---|---|
| `frequency` | enum | Daily, every 2 days, every 3 days, ..., specific weekdays |
| `water_budget` | int (%) | Global multiplier applied to all station durations in the program (e.g. 50% → halves all durations, 150% → 1.5x). Typical SOLEM range 0–200%. |
| `start_times` | list of HH:MM | N scheduled start times per day (the app allows multiple — exact max TBD) |

### 1.2 Station ↔ Program assignment

- Stations are numbered 1..N (N ∈ {1, 2, 4, 6} depending on model).
- Each station is bound to **exactly one program** (1-to-1 from the station's
  point of view; a program can drive multiple stations).
- Each station also has its own **per-program duration** (the watering time
  that program will run that station for).

This is the canonical SOLEM scheduling model: "Program 1 runs daily at 06:00
and 19:00; station 1 for 10 min, station 2 for 5 min".

### 1.3 Manual actions (from the app)

- **Start a single station** with a custom duration (already implemented in
  Another-Solem as `build_station_command`).
- **Start all stations** with a custom duration (implemented as
  `build_all_stations_command`).
- **Run a program** on demand (NOT implemented in either HA integration).
- **Stop** (implemented).

### 1.4 Read-only / status

The app surfaces information that we have **not yet identified** in the
protocol:

- **Battery level** of the controller (BL-IP runs on a 9V battery).
- **Current configuration** of the 3 programs.
- **Station → program** mapping.
- Possibly: next scheduled start, last run timestamp, error/fault flags.

---

## 2. Protocol coverage status

Cross-reference between MySolem features and the BLE protocol commands we
have today.

| MySolem feature | Status | Command / Notes |
|---|---|---|
| Start station X for Y minutes | ✅ Confirmed | `3105 12 [STN] 00 [SEC_BE16]` |
| Start all stations for Y minutes | ✅ Confirmed | `3105 11 0000 [SEC_BE16]` |
| Stop manual watering | ✅ Confirmed | `3105 15 00ff 0000` |
| Status / countdown polling | ✅ Confirmed | `3105 a0 0001 0000` (returns first of 3 notification packets) |
| **Run program N on demand** | 🟡 Hypothesis | `3105 14 [PROG_ID] 00 0000` — present in original RE notes (`31051400010000` = "dimi seara" / `31051400020000` = "avarie"). **Not yet tested.** |
| **Write program config** (freq + budget + start times) | ❌ Unknown | Likely a multi-frame write to a config opcode. Possibly `3105 1x` or `3105 2x` range. |
| **Read program config** | ❌ Unknown | Probably uses status-like command and parses packets 2 and 3 of the response (which the integration currently discards). |
| **Assign station → program** | ❌ Unknown | Unknown opcode. May be combined with program write. |
| **Per-station duration in program** | ❌ Unknown | Likely encoded together with the program config write. |
| **Battery level** | ❌ Unknown | Not in standard GATT (`0x180F` not exposed). Possibly: a byte inside one of the 3 status packets, or a dedicated command (`3105 ??`), or BLE advertising manufacturer_data. |
| **Off for N days** (programmed_off) | 🟡 Hypothesis | Original notes: `3105 c0 00 [DAYS] 0000`. State observed (`mode=0x02` after stop). Not user-visible in MySolem? |

Legend: ✅ tested & working — 🟡 partial / untested — ❌ unknown

---

## 3. Status notification structure (recap)

Every command produces **exactly 3 notification packets** of 18 bytes each
(prefix `3210` for the original write, `3c10` for the commit-driven response).

### Packet 1 (sub-status `0x02`) — current state, timer, mode

```
3210 02 [MODE] 00 [STN_MASK?] 00 [?]  [?]  [?]  10 [TIMER_BE16] 10 0000
  0  1  2  3   4  5   6   7  8  9  10 11   12 13 14            16 17
```

- `data[3]` = mode byte: `0x40` idle, `0x41` all stations, `0x42` single
  station, `0x02` programmed_off.
- `data[5..7]` = station mask (`aaaaaa` when single/all; `000000` otherwise).
- `data[13:15]` = remaining seconds (big-endian).
- `data[10..12]` = constants `58 14 10` in all captures — purpose unknown.
  *Candidate for battery byte: needs samples at known different battery levels
  to confirm.*

### Packet 2 (sub-status `0x01`) — UNKNOWN, currently discarded

Captured value (constant across idle / active):

```
3210 01 10 00 00 10 00 00 10 00 00 10 00 00 10 00 00 00 00 00
```

Looks like 4 slots of `10 00 00` followed by zeros. Plausible
interpretations:
- **Program slots** (3 visible + 1 spare?).
- **Station configuration** (4 stations × 3-byte record).
- Hardware/firmware identifier.

### Packet 3 (sub-status `0x00`) — UNKNOWN, currently discarded

Captured value: all zeros.

```
3210 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

May contain non-zero content when programs are configured. Need fresh
captures from a controller that already has programs set up.

---

## 4. MySolem flows we want to capture

When sniffing the app via Android Bluetooth HCI snoop log, the following
distinct sequences should be triggered (with several seconds pause between
each, to keep the log readable):

1. **App opens, connects, shows main page** → likely triggers status + battery
   read.
2. **Open program 1 detail screen** → should read full program 1 config.
3. **Modify program 1**: set frequency = daily, water_budget = 100%, one start
   at 06:00, station 1 duration = 5 min → save.
4. **Assign station 2 to program 1**.
5. **Run program 1 manually** (start button on program screen).
6. **Stop**.
7. **Manually start station 2 for 3 min**.
8. **Stop**.
9. **Close the app** (look for an explicit goodbye / disconnect handshake).

Each of these should be annotated in the resulting capture analysis.

---

## 5. Open questions

- How many `start_times` per program does the app actually allow? (need to
  poke the UI)
- Is `water_budget` per-program or global? (initial reading suggests
  per-program)
- Does the app ever **read** the battery, or is it only present in BLE
  advertising data?
- What happens if a station is left **unassigned**? Does the program write
  command include an explicit "station N is unused" marker?

---

## 6. Action items (live backlog)

- [ ] Add diagnostic logger in Another-Solem HA integration that captures all
      3 status packets and the BLE advertising `manufacturer_data` /
      `service_data` (passive intel while waiting for the snoop log).
- [ ] Implement `run_program` command on the hypothesis `3105 14 N 00 0000`
      and test it on a real controller. **Low risk** — worst case it does
      nothing.
- [ ] Capture MySolem Android Bluetooth HCI snoop log following the flow in
      §4.
- [ ] Decode captured log in Wireshark (`btatt` filter, look at the
      `108b0002` write characteristic and `108b0003` notify characteristic).
- [ ] Document each newly identified command back into this file.
- [ ] Add to `protocol.py`: program read/write, battery read.
- [ ] Add HA entities: battery `sensor`, program `button` (run), program
      `select` per station, configurable `number`/`time` entities for
      schedules.
