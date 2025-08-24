"""
SOLEM BLIP Bluetooth LE Controller
==================================

This module provides control over SOLEM BLIP irrigation systems via Bluetooth LE.

CONFIRMED WORKING COMMANDS:
- startWatering(station, minutes): Water specific station (1-3) for X minutes
- startWateringAll(minutes): Water all stations for X minutes  
- stopWatering(): Stop all irrigation immediately

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
            print(f"Notification from {sender}: {binascii.hexlify(data)}")
    
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

    async def offDays(self, days):
        """Turn off for specified number of days"""
        cmd = struct.pack(">HBHH", 0x3105, 0xc0, days, 0x0000)
        await self.__writeCommand(cmd)

    async def startWateringAll(self, minutes):
        """Start watering all stations for specified minutes - CONFIRMED WORKING"""
        secs = minutes * 60
        cmd = struct.pack(">HBHH", 0x3105, 0x11, 0x0000, secs)
        await self.__writeCommand(cmd)

    async def startWatering(self, station, minutes):
        """Start watering specific station for specified minutes - CONFIRMED WORKING"""
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
        ("🚿 Station 1, 2min ✅", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 120)),
        ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),

        ("🚿 Station 1, 20seconds ✅", struct.pack(">HBBBH", 0x3105, 0x12, 0x01, 0x00, 20)),
        ("🛑 STOP", struct.pack(">HBHH", 0x3105, 0x15, 0x00ff, 0x0000)),
        


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
            if "20seconds" in name:
                wait_time = 25  # 20 seconds + 5 seconds buffer
                print("⏱️  Waiting 25 seconds (20s irrigation + 5s buffer)...")
            elif "2min" in name:
                wait_time = 125  # 2 minutes + 5 seconds buffer  
                print("⏱️  Waiting 2 minutes and 5 seconds (2min irrigation + 5s buffer)...")
            elif "STOP" in name:
                wait_time = 3  # Short wait for stop commands
                print("⏱️  Waiting 3 seconds for stop command...")
            else:
                print("⏱️  Waiting 10 seconds to observe...")
            
            await asyncio.sleep(wait_time)
            
        except Exception as e:
            print(f"Error sending {name}: {e}")
        
        print("--- End test ---")
        print("⏸️  Pausing 3 seconds before next test...")
        await asyncio.sleep(3)

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

if __name__ == "__main__":
    # Choose what to run:
    # asyncio.run(main())              # Normal usage
    asyncio.run(test_all_functions())  # Test all functions
