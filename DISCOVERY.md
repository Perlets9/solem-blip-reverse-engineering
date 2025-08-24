# SOLEM BLIP Protocol Discoveries

## Overview
This document details the discoveries made during the reverse engineering of the SOLEM BLIP irrigation system's Bluetooth Low Energy (BLE) protocol. Through systematic analysis, we uncovered the actual working protocol and discovered significant differences from the original assumptions.

## Key Discoveries

### 1. Device Discovery Changes

**Original Address**: `C8:B9:61:0A:47:FD` (static MAC)
**New Address**: `F6618508-5155-1147-CC94-F01E09072AC3` (randomized UUID)
**Device Name**: `BL1IP-D4E179N` (contains reference to original MAC suffix)

**Key Finding**: SOLEM BLIP devices use **BLE address randomization** for privacy, meaning the MAC address changes periodically. The device name contains a reference to the original MAC address.

### 2. BLE Characteristics Discovery

**Service UUID**: `108b0001-eab5-bc09-d0ea-0b8f467ce8ee`

**Characteristics**:
- **WRITE**: `108b0002-eab5-bc09-d0ea-0b8f467ce8ee` (WRITE, WRITE_NO_RESP)
- **NOTIFY**: `108b0003-eab5-bc09-d0ea-0b8f467ce8ee` (NOTIFY)

These UUIDs are **custom/proprietary** and not standard BLE service UUIDs.

### 3. Protocol Analysis

#### Command Structure
All commands follow this pattern:
```
[COMMAND_BYTES] → [COMMIT: 3b00]
```

#### Device State Responses
The device responds with different status codes indicating its internal state:

**Response Format**: `32 10 [STATUS] [DATA...]`

**Status Codes Discovered**:
- `40`: Device idle/dormant state
- `41`: All stations mode active  
- `42`: Single station mode active

**Example Responses**:
```bash
# Idle state
3210024000aaaaaa00005914100000100000

# All stations active (2min = 120sec = 0x78)
3210024100aaaaaa00015914100078100000

# Station 1 active (2min = 120sec = 0x78)  
3210024200aaaaaa00015914100078100000
```

#### Timer Countdown Discovery
**Critical Finding**: The device shows a **real-time countdown** in its responses!

**Before commit**: `...100078100000` (120 seconds = 0x78)
**After commit**: `...100077100000` (119 seconds = 0x77)

This proves the device is actively tracking irrigation time internally.

### 4. Working Commands Discovery

#### ❌ Commands That DON'T Work
```bash
# These commands from original reverse engineering don't work:
3105a000010000  # "ON" command - device responds but no irrigation
3105c000000000  # "OFF" command - changes state but no effect
```

#### ✅ Commands That DO Work
```bash
# Station-specific irrigation (WORKS!)
3105 12 [STATION] 00 [SECONDS_HEX]
# Example: Station 1, 120 seconds
31051201000078

# All stations irrigation (WORKS!)  
3105 11 0000 [SECONDS_HEX]
# Example: All stations, 120 seconds
31051100000078

# Stop irrigation (WORKS!)
31051500ff0000

# Commit command (required after each command)
3b00
```

### 5. Key Protocol Insights

#### No "ON" Command Required
**Major Discovery**: Unlike the original assumption, irrigation commands work **directly** without needing to send an "ON" command first. The device activates automatically when receiving irrigation commands.

#### Direct Time Control
Commands specify irrigation duration in **seconds as hexadecimal**:
- 60 seconds (1 min) = `0x3C` = `3c` ✅ MINIMUM WORKING TIME
- 120 seconds (2 min) = `0x78` = `78` ✅ CONFIRMED WORKING
- 300 seconds (5 min) = `0x12C` = `012c` ✅ CONFIRMED WORKING

**CRITICAL DISCOVERY**: The device has a **minimum irrigation time of 1 minute (60 seconds)**. Commands with shorter durations (e.g., 20 seconds) are ignored by the device.

#### Station Numbering
Stations are numbered 1, 2, 3 (not 0-based):
```bash
Station 1: 3105120100[TIME]
Station 2: 3105120200[TIME]  
Station 3: 3105120300[TIME]
```

### 6. Device Behavior Analysis

#### State Management
The device maintains internal state and only accepts irrigation commands when in appropriate states. The status byte in responses indicates:
- Whether the device is ready for commands
- Which type of irrigation is active
- Current timer countdown

#### Automatic Shutoff
The device automatically stops irrigation when the programmed time expires, as evidenced by the countdown in the response messages.

#### Immediate Stop
The stop command (`31051500ff0000`) immediately terminates any active irrigation, regardless of remaining time.

## Confirmed Functionality

### ✅ Working Features
- **Individual station control** (stations 1, 2, 3)
- **All stations simultaneous control**
- **Precise timing control** (tested: 1 minute minimum, 2 minutes, 5 minutes)
- **Immediate stop functionality**
- **Automatic timer expiration**
- **Real-time countdown monitoring**

### ❌ Non-Working Original Commands
- **ON command** (`3105a000010000`) - Device responds but no irrigation occurs
- **OFF command** (`3105c000000000`) - Changes internal state but no practical effect

## Protocol Recommendations

### Command Usage
1. **Direct irrigation commands**: Use station-specific or all-stations commands directly
2. **No initialization required**: Skip ON/OFF commands, go straight to irrigation
3. **Minimum time requirement**: Commands must be ≥ 1 minute (60 seconds)
4. **Always commit**: Send `3b00` after every irrigation command
5. **Monitor responses**: Watch for status codes and countdown timers
6. **Emergency stop**: `31051500ff0000` works immediately in any state

### Device Discovery
1. **Scan by name pattern**: Look for `BL1IP` or `BLIP` in device names
2. **Handle address changes**: Don't hardcode MAC addresses
3. **Use known UUIDs**: Implement the discovered service/characteristic UUIDs directly

## Future Research

### Unexplored Commands
The original reverse engineering notes mention program commands that weren't fully tested:
```bash
31051400010000  # "dimi seara" program
31051400020000  # "avarie" program  
```

These might activate pre-programmed irrigation schedules stored in the device.

### Advanced Features
- Multiple program storage and execution
- Scheduling capabilities
- Battery status monitoring
- Error condition reporting

## Conclusion

This reverse engineering effort revealed that the SOLEM BLIP device operates more directly than originally assumed. The key breakthrough was discovering that **irrigation commands work immediately** without requiring ON/OFF state management. 

The device's internal timer system and real-time countdown responses provide precise irrigation control, making it a reliable system for automated irrigation management. The protocol is simpler than initially thought - direct command execution with automatic timing and state management handled internally by the device.
