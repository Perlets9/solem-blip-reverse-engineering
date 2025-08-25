# SOLEM BLIP Home Assistant Integration Guide

## Overview
This document provides complete specifications for developing a Home Assistant custom component to control SOLEM BLIP irrigation systems via Bluetooth Low Energy (BLE). The component should provide full irrigation control with real-time status monitoring.

## Device Information

### Hardware Details
- **Device**: SOLEM BLIP Irrigation Controller
- **Communication**: Bluetooth Low Energy (BLE)
- **Device Name Pattern**: `BL1IP-*` or `BLIP-*`
- **Address Type**: Randomized UUID (changes periodically for privacy)

### BLE Characteristics
- **Service UUID**: `108b0001-eab5-bc09-d0ea-0b8f467ce8ee`
- **Write Characteristic**: `108b0002-eab5-bc09-d0ea-0b8f467ce8ee` (WRITE, WRITE_NO_RESP)
- **Notify Characteristic**: `108b0003-eab5-bc09-d0ea-0b8f467ce8ee` (NOTIFY)

## Protocol Specifications

### Command Structure
All commands follow this pattern:
```
[COMMAND_BYTES] → [COMMIT: 3b00]
```

### Working Commands

#### Irrigation Commands
```python
# Single station irrigation (1-3)
# Format: 3105 12 [STATION] 00 [SECONDS_HEX] (big-endian)
# Using struct.pack(">HBBBH", 0x3105, 0x12, station, 0x00, seconds)
station_1_5min = "310512010000012c"  # Station 1, 300 seconds (5 minutes)
station_2_5min = "310512020000012c"  # Station 2, 300 seconds  
station_3_5min = "310512030000012c"  # Station 3, 300 seconds

# All stations irrigation
# Format: 3105 11 0000 [SECONDS_HEX] (big-endian)
# Using struct.pack(">HBHH", 0x3105, 0x11, 0x0000, seconds)
all_stations_5min = "31051100000012c"  # All stations, 300 seconds

# Stop irrigation
# Using struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)
stop_command = "31051500ff0000"

# Commit command (required after each command)
commit = "3b00"
```

#### Status Check Command (Non-intrusive)
```python
# ON command - BEST for status checking (doesn't interfere with active irrigation)
# Using struct.pack(">HBHH", 0x3105, 0xa0, 0x0001, 0x0000)
status_check = "3105a000010000"

# Alternative commands (tested but less recommended):
# OFF command: struct.pack(">HBHH", 0x3105, 0xc0, 0x0000, 0x0000) = "3105c000000000"
# Program command: struct.pack(">HBHH", 0x3105, 0x14, 0x0001, 0x0000) = "31051400010000"
```

#### Status Command Testing Results
Through systematic testing (`test_status_commands()` function), we confirmed:

**Test Results from Real Device Logs:**
- **OFF command (`3105c000000000`)**: 
  - ✅ Returns status but shows `sub-status: 02` (Programmed off mode)
  - ⚠️ May change device state to "programmed off"
  - Timer shows countdown: `0x0076` (118s) → `0x0073` (115s)

- **ON command (`3105a000010000`)**: 
  - ✅ **RECOMMENDED** - Returns accurate status `sub-status: 42` (Single station mode)
  - ✅ Doesn't interfere with active irrigation
  - ✅ Shows real-time countdown: `0x006e` (110s) → `0x006c` (108s)

- **Program command (`31051400010000`)**: 
  - ✅ Returns status with `sub-status: 40` (Idle mode)
  - ⚠️ May trigger unintended program execution
  - Shows timer as `0x0000` (no active irrigation)

**Conclusion**: Use ON command for all status polling in Home Assistant integration.

### Important Constraints
- **Minimum irrigation time**: 1 minute (60 seconds)
- **Commands shorter than 60 seconds are ignored by the device**
- **Station numbers**: 1, 2, 3 (not zero-based)
- **Maximum time**: Approximately 12 hours (0xa8c0 seconds)

### Notification Protocol

#### Response Structure
Every command generates exactly 3 notification packets:
1. **Packet 1/3**: Main status information
2. **Packet 2/3**: Additional data
3. **Packet 3/3**: Final confirmation

#### Status Decoding (First Packet)
- **Byte 2**: Packet type identifier (`0x02` for first packet)
- **Byte 3 (Sub-status)**: Device mode
  - `0x40`: Idle/stopped
  - `0x41`: All stations active
  - `0x42`: Single station active
  - `0x02`: Programmed off mode
- **Bytes 13-14**: Timer remaining (big-endian, seconds)
  - **Note**: Timer value appears to be at different byte positions in the hex string
  - **Actual location**: Look for countdown values like `0x0076` (118s) → `0x0073` (115s)
  - **Format**: The timer bytes are embedded in the larger data structure

#### Complete Status Byte Mapping
From `_decode_status()` and `_decode_sub_status()` functions:
- **Main Status Bytes (Byte 2)**:
  - `0x02`: Status packet 1/3 (first) - contains main status info
  - `0x01`: Status packet 2/3 (middle) - additional data
  - `0x00`: Status packet 3/3 (final) - confirmation
- **Device Mode Sub-Status (Byte 3 when main status = 0x02)**:
  - `0x40`: Device idle/dormant
  - `0x41`: All stations mode active
  - `0x42`: Single station mode active
  - `0x02`: Programmed off mode

#### Device Behavior
- **Silent operation**: No periodic notifications during irrigation
- **Status polling required**: Send status check command to get current state
- **Auto-stop**: Device stops automatically when timer expires (silently)
- **Command-only responses**: Device only sends notifications in response to commands
- **No idle notifications**: Device doesn't send periodic status updates when idle
- **Immediate response**: All commands generate immediate triple-packet response
- **Real-time countdown**: Timer value in notifications counts down in real-time during irrigation

#### Notification Pattern Analysis
Based on extensive testing and real device logs, the device follows these patterns:

1. **Command Response Only**: Notifications are only sent in response to commands, never spontaneously
2. **Triple Packet Structure**: Every command generates exactly 3 packets (first=status, middle=data, final=confirmation)
3. **Dual Response Pattern**: Each command triggers TWO sets of triple packets:
   - **First set**: Immediate response with prefix `3210`
   - **Second set**: Post-commit response with prefix `3c10`
4. **Timer Countdown**: During irrigation, timer values count down in real-time:
   - Example: `0x0076` (118s) → `0x0073` (115s) over 3 seconds
   - Timer location varies but appears in the hex data stream
5. **Silent Auto-Stop**: When irrigation completes, device stops silently without sending notification
6. **Status Polling Required**: To know current status, must actively send status check command

#### Real Device Response Examples (from logs):
```
Command: Start 2min irrigation (120s = 0x0078)
Response 1 (3210): sub-status 0x42 (single station), timer 0x0078
Response 2 (3c10): sub-status 0x42 (single station), timer 0x0078

Status Check: ON command during irrigation
Response 1 (3210): sub-status 0x42 (single station), timer 0x006e (110s)
Response 2 (3c10): sub-status 0x42 (single station), timer 0x006c (108s)
```

## Home Assistant Component Requirements

### Entity Types Needed

#### 1. Switch Entities (Per Station)
```yaml
# Example entity configuration
switch.solem_blip_station_1:
  name: "Garden Station 1"
  icon: mdi:sprinkler
  device_class: switch

switch.solem_blip_station_2:
  name: "Garden Station 2" 
  icon: mdi:sprinkler
  device_class: switch

switch.solem_blip_station_3:
  name: "Garden Station 3"
  icon: mdi:sprinkler
  device_class: switch

switch.solem_blip_all_stations:
  name: "All Stations"
  icon: mdi:sprinkler-variant
  device_class: switch
```

#### 2. Number Entities (Duration Control)
```yaml
number.solem_blip_station_1_duration:
  name: "Station 1 Duration"
  min: 1
  max: 720  # 12 hours
  step: 1
  unit_of_measurement: "min"
  icon: mdi:timer

# Similar for stations 2, 3, and all stations
```

#### 3. Sensor Entities (Status Monitoring)
```yaml
sensor.solem_blip_status:
  name: "Irrigation Status"
  icon: mdi:information
  # States: idle, single_station_active, all_stations_active, programmed_off

sensor.solem_blip_time_remaining:
  name: "Time Remaining"
  unit_of_measurement: "min"
  icon: mdi:timer-sand
  device_class: duration

sensor.solem_blip_active_station:
  name: "Active Station"
  icon: mdi:sprinkler
  # States: none, station_1, station_2, station_3, all_stations
```

#### 4. Button Entity (Emergency Stop)
```yaml
button.solem_blip_stop:
  name: "Stop Irrigation"
  icon: mdi:stop
  device_class: restart
```

### Core Functionality Requirements

#### Device Discovery
```python
async def async_discover_devices(timeout=10):
    """Discover SOLEM BLIP devices via BLE scan"""
    devices = await BleakScanner.discover(timeout=timeout)
    
    solem_devices = []
    for device in devices:
        # Look for SOLEM devices by name patterns or known addresses
        if (device.name and ("blip" in device.name.lower() or "bl1ip" in device.name.lower())):
            solem_devices.append(device)
            
        # Also check for known addresses (but address changes due to randomization)
        # This is mainly for fallback/debugging purposes
        elif device.address.upper() in ["C8:B9:61:D4:E1:79", "F6618508-5155-1147-CC94-F01E09072AC3"]:
            solem_devices.append(device)
    
    return solem_devices

# IMPORTANT: Device name patterns observed:
# - "BL1IP-XXXX" (most common)
# - "BLIP-XXXX" (alternative pattern)
# - Case-insensitive matching recommended
# - Address randomization means MAC addresses change periodically
```

#### Connection Management
```python
class SolemBlipDevice:
    async def connect(self):
        """Establish BLE connection"""
        # Use bleak library for cross-platform BLE support
        # Handle connection retries and timeouts
        # Set up notification handlers
    
    async def disconnect(self):
        """Clean disconnect"""
        # Disable notifications
        # Close BLE connection
```

#### Command Interface
```python
async def start_irrigation(self, station: int, duration_minutes: int):
    """Start irrigation for specific station"""
    # Validate: station in [1, 2, 3] or 0 for all stations
    # Validate: duration_minutes >= 1 (minimum 1 minute enforced by device)
    # Convert minutes to seconds
    # Send appropriate command + commit
    if duration_minutes < 1:
        raise ValueError("Minimum irrigation time is 1 minute")
    
async def start_irrigation_all(self, duration_minutes: int):
    """Start irrigation for all stations"""
    # Validate: duration_minutes >= 1
    # Send all stations command + commit
    if duration_minutes < 1:
        raise ValueError("Minimum irrigation time is 1 minute")
    
async def stop_irrigation(self):
    """Stop all irrigation immediately"""
    # Send stop command + commit
    # Command: struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)
    
async def get_status(self):
    """Get current device status (non-intrusive)"""
    # Send ON command (doesn't interfere with active irrigation)
    # Command: struct.pack(">HBHH", 0x3105, 0xa0, 0x0001, 0x0000)
    
    # IMPORTANT: Temporarily replace notification handler to capture status
    self._last_notification = None
    original_handler = self.notification_handler
    
    def status_handler(sender, data):
        # Only capture the first notification (main status)
        if len(data) >= 18 and data[2] == 0x02:  # First packet
            self._last_notification = data
    
    # Replace handler temporarily
    await self.client.start_notify(NOTIFY_UUID, status_handler)
    
    # Send command + commit
    await self.send_command("3105a000010000")
    
    # Restore original handler
    await self.client.start_notify(NOTIFY_UUID, original_handler)
    
    # Parse captured notification and return structured status information:
    # {
    #     "active": bool,
    #     "mode": str,  # "idle", "single_station_active", "all_stations_active", "programmed_off"
    #     "timer_remaining": int,  # seconds
    #     "timer_minutes": int,
    #     "timer_seconds": int,
    #     "sub_status_code": int,
    #     "raw_response": str
    # }
```

#### Status Monitoring
```python
async def async_update(self):
    """Update entity states"""
    # Poll device status every 30-60 seconds
    # Update all entity states based on response
    # Handle connection errors gracefully
```

### Implementation Details

#### BLE Communication
```python
# Use bleak library for BLE communication
from bleak import BleakClient, BleakScanner

# Command sending pattern
async def send_command(self, command_hex: str):
    command_bytes = bytes.fromhex(command_hex)
    await self.client.write_gatt_char(WRITE_UUID, command_bytes)
    await asyncio.sleep(0.1)
    
    # Always send commit
    commit_bytes = bytes.fromhex("3b00")
    await self.client.write_gatt_char(WRITE_UUID, commit_bytes)
```

#### Status Parsing
```python
def parse_status_notification(self, data: bytes) -> dict:
    """Parse device status from notification"""
    if len(data) >= 18 and data[2] == 0x02:  # First packet
        sub_status = data[3]  # Sub-status byte
        timer_bytes = data[13:15]  # Timer at position 13-14
        timer_remaining = struct.unpack(">H", timer_bytes)[0] if len(timer_bytes) >= 2 else 0
        
        # Determine status based on sub_status byte
        if sub_status == 0x42:
            mode = "single_station_active"
            active = True
        elif sub_status == 0x41:
            mode = "all_stations_active" 
            active = True
        elif sub_status == 0x40:
            mode = "idle"
            active = False
        elif sub_status == 0x02:
            mode = "programmed_off"
            active = False
        else:
            mode = f"unknown_{sub_status:02x}"
            active = False
        
        return {
            "active": active,
            "mode": mode,
            "timer_remaining": timer_remaining,
            "timer_minutes": timer_remaining // 60,
            "timer_seconds": timer_remaining % 60,
            "sub_status_code": sub_status,
            "raw_response": data.hex()
        }
    
    return {
        "active": False,
        "mode": "no_response",
        "timer_remaining": 0,
        "timer_minutes": 0,
        "timer_seconds": 0,
        "sub_status_code": None,
        "raw_response": None
    }
```

### Configuration Schema

#### config_flow.py
```python
CONF_DEVICE_ADDRESS = "device_address"
CONF_DEVICE_NAME = "device_name"
CONF_SCAN_TIMEOUT = "scan_timeout"

CONFIG_SCHEMA = vol.Schema({
    vol.Optional(CONF_SCAN_TIMEOUT, default=10): cv.positive_int,
})
```

#### User Interface Flow
1. **Discovery Step**: Scan for SOLEM BLIP devices
2. **Selection Step**: User selects device from discovered list
3. **Configuration Step**: Set device name and polling interval
4. **Confirmation Step**: Test connection and create entities

### Error Handling

#### Connection Issues
- Retry connection with exponential backoff
- Handle BLE address changes (device randomization)
- Graceful degradation when device is unreachable
- Clear error messages in Home Assistant UI

#### Command Failures
- Validate parameters before sending commands
- Handle device non-response scenarios
- Provide user feedback for invalid operations
- Log detailed error information for debugging

### Performance Considerations

#### Polling Strategy
- **Status polling interval**: 30-60 seconds (configurable)
- **Connection keep-alive**: Maintain persistent connection
- **Efficient updates**: Only update changed entities
- **Background operation**: Non-blocking async operations

#### Resource Management
- **Connection pooling**: Reuse BLE connections
- **Memory management**: Clean up resources properly
- **CPU usage**: Minimize polling frequency when idle

### Security Considerations

#### BLE Security
- Handle device address randomization
- Validate all incoming data
- Secure credential storage (if authentication added)
- Rate limiting for commands

#### Home Assistant Integration
- Follow Home Assistant security best practices
- Validate all user inputs
- Sanitize device responses
- Implement proper error boundaries

### Testing Requirements

#### Unit Tests
- Command generation and parsing
- Status decoding logic
- Error handling scenarios
- Configuration validation

#### Integration Tests
- Full device communication flow
- Home Assistant entity behavior
- Configuration flow testing
- Error recovery testing

### Documentation Requirements

#### User Documentation
- Installation instructions
- Configuration guide
- Troubleshooting section
- Feature limitations

#### Developer Documentation
- API reference
- Protocol specifications
- Extension points
- Debugging guide

## Example Usage in Home Assistant

### Automation Examples
```yaml
# Water garden in the morning
automation:
  - alias: "Morning Garden Watering"
    trigger:
      platform: time
      at: "06:00:00"
    condition:
      condition: state
      entity_id: sensor.solem_blip_status
      state: "idle"
    action:
      - service: number.set_value
        target:
          entity_id: number.solem_blip_all_stations_duration
        data:
          value: 15
      - service: switch.turn_on
        target:
          entity_id: switch.solem_blip_all_stations

# Emergency stop on rain
automation:
  - alias: "Stop irrigation on rain"
    trigger:
      platform: state
      entity_id: binary_sensor.rain_detected
      to: "on"
    action:
      - service: button.press
        target:
          entity_id: button.solem_blip_stop
```

### Dashboard Card Example
```yaml
type: entities
title: Garden Irrigation
entities:
  - entity: sensor.solem_blip_status
  - entity: sensor.solem_blip_time_remaining
  - entity: sensor.solem_blip_active_station
  - type: divider
  - entity: switch.solem_blip_station_1
  - entity: number.solem_blip_station_1_duration
  - entity: switch.solem_blip_station_2
  - entity: number.solem_blip_station_2_duration
  - entity: switch.solem_blip_station_3
  - entity: number.solem_blip_station_3_duration
  - type: divider
  - entity: switch.solem_blip_all_stations
  - entity: number.solem_blip_all_stations_duration
  - entity: button.solem_blip_stop
```

## Implementation Priority

### Phase 1 (Core Functionality)
1. Device discovery and connection
2. Basic irrigation control (start/stop)
3. Status monitoring
4. Switch entities for each station

### Phase 2 (Enhanced Features)
1. Duration control via number entities
2. Status sensors
3. Configuration flow UI
4. Error handling and recovery

### Phase 3 (Advanced Features)
1. Multiple device support
2. Advanced scheduling integration
3. Historical data logging
4. Performance optimizations

## Reference Implementation

The complete working Python implementation is available in the `solem_bleak.py` file, which includes:
- Full BLE communication protocol
- Command generation and parsing
- Status monitoring with `getStatus()` method
- Error handling and connection management
- Detailed protocol analysis and debugging tools

This reference implementation should be adapted to follow Home Assistant's component architecture and coding standards.

## Support and Maintenance

### Known Limitations
- **Minimum irrigation time**: 1 minute (60 seconds) - commands with shorter durations are ignored
- **No real-time countdown notifications**: Device doesn't send periodic updates during irrigation
- **Silent auto-stop**: Device stops automatically when timer expires without notification
- **Status polling required**: Must actively send commands to get current status
- **Device address randomization**: BLE address changes periodically, requires dynamic discovery
- **Single concurrent BLE connection**: Only one connection per device at a time
- **Dual triple notification packets**: Each command generates 6 total packets (3 immediate + 3 post-commit)
- **Timer location variability**: Timer countdown appears in hex stream but position may vary
- **State-changing status commands**: Some status commands (OFF, Program) may alter device state
- **Real-time timer drift**: Timer values in consecutive responses may differ by 1-2 seconds due to processing time

### Future Enhancements
- Battery level monitoring (if supported by device)
- Advanced scheduling features
- Integration with weather services
- Multi-zone irrigation programs

This specification provides all necessary information to develop a complete, robust Home Assistant integration for SOLEM BLIP irrigation systems.
