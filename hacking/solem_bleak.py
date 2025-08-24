"""
SOLEM BLIP Bluetooth LE Controller
==================================

This module provides control over SOLEM BLIP irrigation systems via Bluetooth LE.

CONFIRMED WORKING COMMANDS:
- startWatering(station, minutes): Water specific station (1-3) for X minutes (min: 1 minute)
- startWateringAll(minutes): Water all stations for X minutes (min: 1 minute)
- stopWatering(): Stop all irrigation immediately

IMPORTANT: Device has a minimum irrigation time of 1 minute (60 seconds).
Commands with shorter durations will be ignored.

USAGE:
1. Normal usage: python solem_bleak.py
2. Test all functions: change main() to call test_all_functions()

REQUIREMENTS:
- bleak library: pip install bleak
- Device address: Update target_address in main() if different

PROTOCOL NOTES:
- Station watering: 3105 12 [station] 00 [seconds_hex]
- All stations: 3105 11 0000 [seconds_hex]  
- Stop: 3105 15 00ff 0000
- Commit: 3b00 (sent after each command)
"""

import struct
import binascii
import time
import asyncio
from bleak import BleakClient, BleakScanner

class SolemBLIP:
    # UUIDs for SOLEM BLIP device - will be discovered dynamically
    NOTIFY_CHARACTERISTIC_UUID = None
    WRITE_CHARACTERISTIC_UUID = None
    DEVICE_NAME_UUID = None
    
    def __init__(self, address):
        self.__debug = False
        self.connected = False     
        self.address = address
        self.client = None
        self.name = None
        self.preferredParams = b'0x00'
        self.__notificationsEnabled = False
        
    def notification_handler(self, sender, data):
        """Handle notifications from the device"""
        if self.__debug:
            print(f"📨 Notification received:")
            self._analyze_notification(data)
    
    def _analyze_notification(self, data):
        """Analyze and decode notification data"""
        if len(data) < 4:
            print(f"  ⚠️  Short notification: {len(data)} bytes")
            return
        
        hex_data = binascii.hexlify(data).decode()
        print(f"  📊 Analysis: {hex_data}")
        
        # Parse common structure: seems to be 32 10 [STATUS] [DATA...]
        if len(data) >= 2:
            prefix = struct.unpack(">H", data[0:2])[0]
            print(f"  🔸 Prefix: {prefix:04x} ({'3210' if prefix == 0x3210 else '3c10' if prefix == 0x3c10 else 'unknown'})")
        
        if len(data) >= 4:
            status_area = struct.unpack(">H", data[2:4])[0]
            status_byte = (status_area >> 8) & 0xFF  # First byte of status area
            sub_status = status_area & 0xFF          # Second byte of status area
            print(f"  🔸 Status: {status_byte:02x} ({self._decode_status(status_byte)})")
            print(f"  🔸 Sub-status: {sub_status:02x} ({self._decode_sub_status(sub_status, status_byte)})")
        
        # Look for timer values - try different positions
        if len(data) >= 16:
            # Try different timer positions
            timer_area = data[12:16]
            timer_hex = binascii.hexlify(timer_area).decode()
            print(f"  ⏱️  Timer area: {timer_hex}")
            
            # Try to find the actual timer value (60 = 0x3C)
            # Let's check multiple positions
            for i in range(len(data) - 1):
                if i + 1 < len(data):
                    potential_timer = struct.unpack(">H", data[i:i+2])[0]
                    if potential_timer == 60 or potential_timer == 59:  # Look for our 60-second timer or countdown
                        print(f"  ⏱️  Found timer at position {i}: {potential_timer} seconds ({potential_timer//60}:{potential_timer%60:02d})")
            
            # Also try little-endian
            for i in range(len(data) - 1):
                if i + 1 < len(data):
                    potential_timer = struct.unpack("<H", data[i:i+2])[0]
                    if potential_timer == 60 or potential_timer == 59:
                        print(f"  ⏱️  Found timer (LE) at position {i}: {potential_timer} seconds ({potential_timer//60}:{potential_timer%60:02d})")
        
        # Look for station information
        if len(data) >= 8:
            station_area = data[6:8]
            station_hex = binascii.hexlify(station_area).decode()
            print(f"  🚿 Station area: {station_hex}")
        
        print(f"  📏 Total length: {len(data)} bytes")
        print()
    
    def _decode_status(self, status_byte):
        """Decode status byte meaning"""
        status_map = {
            0x40: "Device idle/dormant",
            0x41: "All stations mode active", 
            0x42: "Single station mode active",
            0x00: "Status packet 3/3 (final)",
            0x01: "Status packet 2/3 (middle)", 
            0x02: "Status packet 1/3 (first)"
        }
        return status_map.get(status_byte, f"Unknown status: {status_byte:02x}")
    
    def _decode_sub_status(self, sub_status, main_status):
        """Decode sub-status byte meaning based on context"""
        if main_status == 0x02:  # First packet
            sub_status_map = {
                0x40: "Idle mode",
                0x41: "All stations mode", 
                0x42: "Single station mode"
            }
            return sub_status_map.get(sub_status, f"Unknown mode: {sub_status:02x}")
        elif main_status == 0x01:  # Middle packet
            return f"Packet data: {sub_status:02x}"
        elif main_status == 0x00:  # Final packet
            return f"Final data: {sub_status:02x}"
        else:
            return f"Context unknown: {sub_status:02x}"
    
    async def discover_characteristics(self):
        """Discover and analyze all available characteristics"""
        if not self.connected or not self.client:
            raise Exception("Device not connected")
        
        print("\n=== Discovering Characteristics ===")
        services = self.client.services
        
        for service in services:
            print(f"\nService: {service.uuid} - {service.description}")
            
            for char in service.characteristics:
                properties = []
                if "read" in char.properties:
                    properties.append("READ")
                if "write" in char.properties:
                    properties.append("WRITE")
                if "write-without-response" in char.properties:
                    properties.append("WRITE_NO_RESP")
                if "notify" in char.properties:
                    properties.append("NOTIFY")
                if "indicate" in char.properties:
                    properties.append("INDICATE")
                
                props_str = ", ".join(properties)
                print(f"  Characteristic: {char.uuid} - {char.description} [{props_str}]")
                
                # Try to read if readable
                if "read" in char.properties:
                    try:
                        value = await self.client.read_gatt_char(char.uuid)
                        if len(value) < 50:  # Only show short values
                            try:
                                decoded = value.decode('utf-8', errors='ignore')
                                print(f"    Value: {value.hex()} ('{decoded}')")
                            except:
                                print(f"    Value: {value.hex()}")
                    except Exception as e:
                        print(f"    Could not read: {e}")
        
        # Try to identify the correct characteristics based on properties
        print("\n=== Identifying SOLEM Characteristics ===")
        for service in services:
            for char in service.characteristics:
                # Look for write characteristic (for commands)
                if ("write" in char.properties or "write-without-response" in char.properties):
                    print(f"Potential WRITE characteristic: {char.uuid}")
                    if not self.WRITE_CHARACTERISTIC_UUID:
                        self.WRITE_CHARACTERISTIC_UUID = str(char.uuid)
                
                # Look for notify characteristic (for responses)
                if "notify" in char.properties:
                    print(f"Potential NOTIFY characteristic: {char.uuid}")
                    if not self.NOTIFY_CHARACTERISTIC_UUID:
                        self.NOTIFY_CHARACTERISTIC_UUID = str(char.uuid)
    
    async def __writeCommand(self, cmd):
        """Write a command to the device"""
        if not self.connected or not self.client:
            raise Exception("Device not connected")
        
        if not self.WRITE_CHARACTERISTIC_UUID:
            raise Exception("Write characteristic not found")
            
        if self.__debug:
            print(f"Sending command: {binascii.hexlify(cmd)}")
        
        # Write the command
        await self.client.write_gatt_char(self.WRITE_CHARACTERISTIC_UUID, cmd)
        await asyncio.sleep(0.1)  # Small delay
        
        if self.__debug:
            print("Committing (command: 0x3b00)")
        
        # Send commit command
        commit_cmd = struct.pack(">H", 0x3b00)
        await self.client.write_gatt_char(self.WRITE_CHARACTERISTIC_UUID, commit_cmd)
        await asyncio.sleep(0.1)  # Small delay
    
    async def on(self):
        """Turn the irrigation system on"""
        cmd = struct.pack(">HBHH", 0x3105, 0xa0, 0x0001, 0x0000)
        await self.__writeCommand(cmd)

    async def off(self):
        """Turn the irrigation system off"""
        cmd = struct.pack(">HBHH", 0x3105, 0xc0, 0x0000, 0x0000)
        await self.__writeCommand(cmd)

    async def stopWatering(self):
        """Stop all watering immediately"""
        cmd = struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)
        await self.__writeCommand(cmd)
    
    async def getStatus(self):
        """Get current device status by sending a non-intrusive command
        
        Uses the ON command which doesn't interfere with active irrigation
        but provides accurate status information.
        
        Returns: Dictionary with status information
        """
        # Use ON command - it doesn't interfere with active irrigation
        cmd = struct.pack(">HBHH", 0x3105, 0xa0, 0x0001, 0x0000)
        
        # Store the last notification for parsing
        self._last_notification = None
        
        # Temporarily store notification handler
        original_handler = self.notification_handler
        
        def status_handler(sender, data):
            # Only capture the first notification (main status)
            if len(data) >= 18 and data[2] == 0x02:  # First packet
                self._last_notification = data
        
        # Replace handler temporarily
        if self.connected and self.client:
            await self.client.start_notify(self.NOTIFY_CHARACTERISTIC_UUID, status_handler)
        
        # Send command
        await self.__writeCommand(cmd)
        
        # Restore original handler
        if self.connected and self.client:
            await self.client.start_notify(self.NOTIFY_CHARACTERISTIC_UUID, original_handler)
        
        # Parse the notification
        if self._last_notification and len(self._last_notification) >= 18:
            data = self._last_notification
            sub_status = data[3]  # Sub-status byte
            timer_bytes = data[13:15]  # Timer at position 13-14
            timer_remaining = struct.unpack(">H", timer_bytes)[0] if len(timer_bytes) >= 2 else 0
            
            # Determine status
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

    async def offDays(self, days):
        """Turn off for specified number of days"""
        cmd = struct.pack(">HBHH", 0x3105, 0xc0, days, 0x0000)
        await self.__writeCommand(cmd)

    async def startWateringAll(self, minutes):
        """Start watering all stations for specified minutes - CONFIRMED WORKING
        
        MINIMUM TIME: 1 minute (60 seconds)
        Commands with less than 1 minute will be ignored by the device.
        """
        if minutes < 1:
            raise ValueError("Minimum irrigation time is 1 minute")
        secs = minutes * 60
        cmd = struct.pack(">HBHH", 0x3105, 0x11, 0x0000, secs)
        await self.__writeCommand(cmd)

    async def startWatering(self, station, minutes):
        """Start watering specific station for specified minutes - CONFIRMED WORKING
        
        MINIMUM TIME: 1 minute (60 seconds)
        Commands with less than 1 minute will be ignored by the device.
        """
        if minutes < 1:
            raise ValueError("Minimum irrigation time is 1 minute")
        secs = minutes * 60
        cmd = struct.pack(">HBBBH", 0x3105, 0x12, station, 0x00, secs)
        await self.__writeCommand(cmd)

    async def runProgram(self, program):
        """Run a specific program"""
        cmd = struct.pack(">HBHH", 0x3105, 0x14, program, 0x0000)
        await self.__writeCommand(cmd)
    
    async def enableNotifications(self):
        """Enable notifications from the device"""
        if not self.connected or not self.client:
            raise Exception("Device not connected")
        
        if not self.NOTIFY_CHARACTERISTIC_UUID:
            if self.__debug:
                print("No notify characteristic found, skipping notifications")
            return
            
        await self.client.start_notify(self.NOTIFY_CHARACTERISTIC_UUID, self.notification_handler)
        self.__notificationsEnabled = True
        if self.__debug:
            print("Notifications enabled")
        
    async def disableNotifications(self):
        """Disable notifications from the device"""
        if not self.connected or not self.client:
            return
            
        await self.client.stop_notify(self.NOTIFY_CHARACTERISTIC_UUID)
        self.__notificationsEnabled = False
        if self.__debug:
            print("Notifications disabled")

    async def connect(self, retries=10, sleep_time=2):
        """Connect to the SOLEM BLIP device"""
        self.connected = False
        if self.__debug:
            print("Connecting...")
        
        for attempt in range(retries):
            try:
                self.client = BleakClient(self.address)
                await self.client.connect()
                self.connected = True
                
                if self.__debug:
                    print("Connected!")
                
                # Discover characteristics only in debug mode
                if self.__debug:
                    await self.discover_characteristics()
                else:
                    # Set known working characteristics directly
                    self.WRITE_CHARACTERISTIC_UUID = "108b0002-eab5-bc09-d0ea-0b8f467ce8ee"
                    self.NOTIFY_CHARACTERISTIC_UUID = "108b0003-eab5-bc09-d0ea-0b8f467ce8ee"
                
                # Set device name
                self.name = "SOLEM BLIP"
                
                break
                
            except Exception as e:
                if self.__debug:
                    print(f"Connection attempt {attempt + 1} failed: {e}")
                
                if attempt < retries - 1:
                    await asyncio.sleep(sleep_time)
                else:
                    raise Exception(f"Unable to connect after {retries} attempts")

    async def disconnect(self):
        """Disconnect from the device"""
        if self.connected and self.client:
            try:
                if self.__notificationsEnabled:
                    await self.disableNotifications()
                await self.client.disconnect()
            except Exception as e:
                if self.__debug:
                    print(f"Error during disconnect: {e}")
        
        self.connected = False
        self.client = None

async def scan_for_solem_devices(timeout=10):
    """Scan for SOLEM BLIP devices"""
    print(f"Scanning for SOLEM BLIP devices for {timeout} seconds...")
    devices = await BleakScanner.discover(timeout=timeout)
    
    solem_devices = []
    for device in devices:
        # Look for SOLEM devices by name or known addresses
        if (device.name and ("blip" in device.name.lower() or "bl1ip" in device.name.lower())) or \
           (device.address.upper() in ["C8:B9:61:D4:E1:79", "F6618508-5155-1147-CC94-F01E09072AC3"]):
            solem_devices.append(device)
            print(f"Found SOLEM device: {device.address} - {device.name}")
    
    return solem_devices

async def test_protocol_variations(sprinkler):
    """Test different protocol variations to find the correct one"""
    print("\n=== Testing Protocol Variations ===")
    
    # Working commands - confirmed functional!
    commands_to_test = [
        # These commands work directly without needing ON first!
        ("🚿 Station 1 ✅", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 60)),
        ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
        
        # Leaving these here for reference and future testing
        # ("🚿 Station 1, 1min ✅", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 60)),
        # ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
        
        # # Test below minimum threshold (for documentation)
        # ("🚿 Station 1, 20seconds ❌", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 20)),
        # ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
        
        # ("🚿 Station 1, 2min ✅", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 120)),
        # ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),


        # Leaving these here for reference and future testing
        # ("🚿 Station 2, 2min", struct.pack(">HBBBH", 0x3105, 0x12, 0x02, 0x00, 120)),
        # ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
        
        # ("🚿 Station 3, 2min", struct.pack(">HBBBH", 0x3105, 0x12, 0x03, 0x00, 120)),
        # ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
        
        # ("🚿 All stations 2min ✅", struct.pack(">HBHH", 0x3105, 0x11, 0x0000, 120)),
        # ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
    ]
    
    for i, (name, cmd) in enumerate(commands_to_test):
        print(f"\n--- Testing {i+1}/{len(commands_to_test)}: {name} ---")
        print(f"Command: {binascii.hexlify(cmd)}")
        print("👀 Watch your irrigation system now!")
        
        try:
            # Send command without commit first
            await sprinkler.client.write_gatt_char(sprinkler.WRITE_CHARACTERISTIC_UUID, cmd)
            await asyncio.sleep(2)  # Wait for response
            
            # Now send commit
            commit_cmd = struct.pack(">H", 0x3b00)
            print(f"Commit: {binascii.hexlify(commit_cmd)}")
            await sprinkler.client.write_gatt_char(sprinkler.WRITE_CHARACTERISTIC_UUID, commit_cmd)
            
            # Calculate real wait time based on command
            wait_time = 10  # Default
            show_countdown = False
            
            if "20seconds" in name:
                wait_time = 25  # 20 seconds + 5 seconds buffer
                show_countdown = True
                print("⏱️  Waiting 25 seconds (20s irrigation + 5s buffer)...")
            elif "1min" in name:
                wait_time = 65  # 1 minute + 5 seconds buffer
                show_countdown = True
                print("⏱️  Waiting 1 minute and 5 seconds (1min irrigation + 5s buffer)...")
            elif "2min" in name:
                wait_time = 125  # 2 minutes + 5 seconds buffer  
                show_countdown = True
                print("⏱️  Waiting 2 minutes and 5 seconds (2min irrigation + 5s buffer)...")
            elif "STOP" in name:
                wait_time = 3  # Short wait for stop commands
                print("⏱️  Waiting 3 seconds for stop command...")
            else:
                print("⏱️  Waiting 10 seconds to observe...")
            
            # Show countdown for longer waits
            if show_countdown and wait_time > 15:
                for remaining in range(wait_time, 0, -10):
                    if remaining > 10:
                        print(f"⏰ {remaining} seconds remaining...")
                        await asyncio.sleep(10)
                    else:
                        print(f"⏰ {remaining} seconds remaining...")
                        await asyncio.sleep(remaining)
                        break
            else:
                await asyncio.sleep(wait_time)
            
        except Exception as e:
            print(f"Error sending {name}: {e}")
        
        print("--- End test ---")
        print("⏸️  Pausing 5 seconds before next test...")
        await asyncio.sleep(5)

async def main():
    """Simple main function for normal usage"""
    # Known working address - update this if your device has a different address
    target_address = "F6618508-5155-1147-CC94-F01E09072AC3"
    
    sprinkler = SolemBLIP(target_address)
    
    try:
        print("Connecting to SOLEM BLIP...")
        await sprinkler.connect(5)
        await sprinkler.enableNotifications()
        print(f"Connected to: {sprinkler.name}")
        
        # Example usage - uncomment what you want to test:
        
        # Water station 1 for 5 minutes
        print("Starting station 1 for 5 minutes...")
        await sprinkler.startWatering(1, 5)
        
        # Wait a bit then stop
        await asyncio.sleep(10)
        print("Stopping irrigation...")
        await sprinkler.stopWatering()
        
        # # Water all stations for 3 minutes
        # print("Starting all stations for 3 minutes...")
        # await sprinkler.startWateringAll(3)
        
        # # Stop after some time
        # await asyncio.sleep(10)
        # await sprinkler.stopWatering()
        
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        await sprinkler.disconnect()
        print("Done.")

async def test_all_functions():
    """Test all irrigation functions - use this to verify everything works"""
    # target_address = await scan_for_solem_devices()
    target_address = "F6618508-5155-1147-CC94-F01E09072AC3"
    
    sprinkler = SolemBLIP(target_address)
    sprinkler._SolemBLIP__debug = True  # Enable debug mode for testing
    
    try:
        print("Connecting...")
        await sprinkler.connect(10)
        await sprinkler.enableNotifications()
        print(f"Connected to: {sprinkler.name}")
        
        # Test all working functions
        await test_protocol_variations(sprinkler)
        
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        await sprinkler.disconnect()
        print("Done.")

async def analyze_notifications():
    """Focused analysis of device notifications and responses"""
    target_address = "F6618508-5155-1147-CC94-F01E09072AC3"
    
    sprinkler = SolemBLIP(target_address)
    sprinkler._SolemBLIP__debug = True  # Enable debug mode for detailed analysis
    
    try:
        print("=== NOTIFICATION ANALYSIS MODE ===")
        print("Connecting...")
        await sprinkler.connect(10)
        await sprinkler.enableNotifications()
        print(f"Connected to: {sprinkler.name}")
        
        # Test different commands for status checking
        test_commands = [
            ("🚿 Start 2min irrigation", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 120), 3),
            ("🔍 Status Check #1 - STOP command", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000), 3),
            ("⏱️  Wait 10 seconds", None, 10),
            ("🔍 Status Check #2 - ON command", struct.pack(">HBHH", 0x3105, 0xa0, 0x0001, 0x0000), 3),
            ("⏱️  Wait 10 seconds", None, 10),
            ("🔍 Status Check #3 - OFF command", struct.pack(">HBHH", 0x3105, 0xc0, 0x0000, 0x0000), 3),
            ("⏱️  Wait 10 seconds", None, 10),
            ("🔍 Status Check #4 - Program command", struct.pack(">HBHH", 0x3105, 0x14, 0x0001, 0x0000), 3),
            ("🛑 Final STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000), 3),
        ]

        # Leaving these here for reference and future testing
        #  ("📊 Idle State Check", None),  # Just wait and see idle notifications
        # ("🚿 1min irrigation", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 60)),
        # ("⏱️  Wait 30 seconds", None),  # Monitor countdown
        # ("🛑 Manual Stop", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
        # ("📊 Post-stop State", None),  # See what happens after stop

        
        for name, cmd, wait_time in test_commands:
            print(f"\n{'='*50}")
            print(f"🔍 {name}")
            print(f"{'='*50}")
            
            if cmd is None:
                # Just wait and observe notifications
                print(f"👁️  Observing notifications for {wait_time} seconds...")
                if wait_time > 30:
                    # Show countdown for long waits
                    for remaining in range(wait_time, 0, -10):
                        if remaining > 10:
                            print(f"⏰ {remaining} seconds remaining...")
                            await asyncio.sleep(10)
                        else:
                            print(f"⏰ {remaining} seconds remaining...")
                            await asyncio.sleep(remaining)
                            break
                else:
                    await asyncio.sleep(wait_time)
            else:
                print(f"📤 Sending command: {binascii.hexlify(cmd)}")
                
                # Send command
                await sprinkler.client.write_gatt_char(sprinkler.WRITE_CHARACTERISTIC_UUID, cmd)
                await asyncio.sleep(2)
                
                # Send commit
                commit_cmd = struct.pack(">H", 0x3b00)
                print(f"📤 Sending commit: {binascii.hexlify(commit_cmd)}")
                await sprinkler.client.write_gatt_char(sprinkler.WRITE_CHARACTERISTIC_UUID, commit_cmd)
                
                # Wait and observe
                print(f"👁️  Observing notifications for {wait_time} seconds...")
                await asyncio.sleep(wait_time)
        
    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        await sprinkler.disconnect()
        print("Done.")

async def test_status_commands():
    """Test different commands to find the best for status checking"""
    target_address = "F6618508-5155-1147-CC94-F01E09072AC3"
    
    sprinkler = SolemBLIP(target_address)
    sprinkler._SolemBLIP__debug = True
    
    try:
        print("=== STATUS COMMAND TESTING ===")
        await sprinkler.connect(10)
        await sprinkler.enableNotifications()
        
        # Start irrigation first
        print("\n🚿 Starting 2-minute irrigation...")
        await sprinkler.startWatering(1, 2)
        await asyncio.sleep(3)
        
        # Test different status check commands
        status_commands = [
            ("OFF command", struct.pack(">HBHH", 0x3105, 0xc0, 0x0000, 0x0000)),
            ("ON command", struct.pack(">HBHH", 0x3105, 0xa0, 0x0001, 0x0000)),
            ("Program command", struct.pack(">HBHH", 0x3105, 0x14, 0x0001, 0x0000)),
        ]
        
        for name, cmd in status_commands:
            print(f"\n{'='*40}")
            print(f"🔍 Testing: {name}")
            print(f"{'='*40}")
            
            # Send status check command
            await sprinkler.client.write_gatt_char(sprinkler.WRITE_CHARACTERISTIC_UUID, cmd)
            await asyncio.sleep(2)
            
            # Send commit
            commit_cmd = struct.pack(">H", 0x3b00)
            await sprinkler.client.write_gatt_char(sprinkler.WRITE_CHARACTERISTIC_UUID, commit_cmd)
            
            print("⏱️  Waiting 5 seconds to see response...")
            await asyncio.sleep(5)
        
        # Final stop
        print("\n🛑 Final stop...")
        await sprinkler.stopWatering()
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await sprinkler.disconnect()
        print("Done.")

if __name__ == "__main__":
    # Choose what to run:
    # asyncio.run(main())                 # Normal usage
    # asyncio.run(test_all_functions())   # Test all functions
    # asyncio.run(analyze_notifications())  # Analyze notifications in detail
    asyncio.run(test_status_commands())   # Test status checking commands
