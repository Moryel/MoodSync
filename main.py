"""
MoodSync - Screen-to-RGB Peripheral Sync
Captures screen color and syncs ALL PC peripherals via OpenRGB SDK.
Supports: Razer, Corsair, ASUS Aura, MSI Mystic Light, and more.
"""

import time
import sys
import mss
import numpy as np

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor, DeviceType
except ImportError:
    print("Error: openrgb-python not installed.")
    print("Run: pip install openrgb-python")
    sys.exit(1)


# Configuration
MONITOR_INDEX = 1          # 1 = primary monitor
COLOR_THRESHOLD = 10       # Minimum color change to trigger update (saves CPU)
UPDATE_INTERVAL = 0.05     # Seconds between captures (50ms = 20 FPS)


def connect_to_openrgb() -> OpenRGBClient:
    """
    Connects to the OpenRGB SDK Server.
    Returns the client if successful, exits with error message if not.
    """
    try:
        client = OpenRGBClient()
        return client
    except ConnectionRefusedError:
        print("=" * 60)
        print("  ERROR: Cannot connect to OpenRGB SDK Server")
        print("=" * 60)
        print()
        print("  Please open OpenRGB software and start the SDK Server:")
        print("  1. Open OpenRGB application (as Administrator!)")
        print("  2. Go to 'SDK Server' tab")
        print("  3. Click 'Start Server'")
        print()
        print("  IMPORTANT: Close iCUE, Synapse, and other RGB software!")
        print()
        print("=" * 60)
        sys.exit(1)


def set_direct_mode(client: OpenRGBClient):
    """
    CRITICAL: Sets all devices to 'Direct' mode for fastest LED updates.
    
    This is REQUIRED for Corsair RAM, ASUS Aura, and some other devices.
    Without Direct mode, these devices will ignore color commands completely.
    
    The function iterates through each device's available modes and activates
    'Direct' mode if it exists. This must be done BEFORE sending any colors.
    """
    print("\nEnabling Direct mode on all devices...")
    
    for device in client.devices:
        device_name = device.name
        direct_mode_found = False
        
        # Search for 'Direct' mode in the device's available modes
        for mode_index, mode in enumerate(device.modes):
            # Check if this mode is 'Direct' (case-insensitive comparison)
            if mode.name.lower() == "direct":
                try:
                    # Activate Direct mode - REQUIRED for Corsair/ASUS compatibility
                    device.set_mode(mode_index)
                    direct_mode_found = True
                    print(f"  ✓ {device_name}: Direct mode enabled")
                except Exception as e:
                    print(f"  ✗ {device_name}: Failed to set Direct mode ({e})")
                break
        
        # If no Direct mode found, device will use its current mode
        if not direct_mode_found:
            print(f"  - {device_name}: No Direct mode available (using default)")


def get_screen_center_color(sct: mss.mss, monitor_index: int) -> tuple:
    """
    Captures the center region of the screen and calculates the average RGB color.
    
    Args:
        sct: mss screen capture instance
        monitor_index: Index of the monitor to capture (1 = primary)
    
    Returns:
        Tuple of (R, G, B) average color values
    """
    monitor = sct.monitors[monitor_index]
    
    # Define a center region (100x100 pixels)
    center_x = monitor["left"] + monitor["width"] // 2
    center_y = monitor["top"] + monitor["height"] // 2
    region_size = 100
    
    region = {
        "left": center_x - region_size // 2,
        "top": center_y - region_size // 2,
        "width": region_size,
        "height": region_size
    }
    
    # Capture and convert BGRA -> RGB
    screenshot = sct.grab(region)
    img_array = np.array(screenshot)
    
    avg_red = int(np.mean(img_array[:, :, 2]))
    avg_green = int(np.mean(img_array[:, :, 1]))
    avg_blue = int(np.mean(img_array[:, :, 0]))
    
    return (avg_red, avg_green, avg_blue)


def color_changed(old: tuple, new: tuple, threshold: int) -> bool:
    """
    Checks if the color has changed significantly to avoid unnecessary updates.
    """
    if old is None:
        return True
    return (abs(old[0] - new[0]) > threshold or
            abs(old[1] - new[1]) > threshold or
            abs(old[2] - new[2]) > threshold)


def set_all_devices_color(client: OpenRGBClient, r: int, g: int, b: int):
    """
    Sets the color of ALL connected RGB devices.
    """
    color = RGBColor(r, g, b)
    for device in client.devices:
        try:
            device.set_color(color)
        except Exception:
            # Skip devices that fail (some may be busy)
            pass


def main():
    """Main loop for MoodSync with OpenRGB."""
    print("=" * 60)
    print("  MoodSync - PC Peripheral RGB Sync")
    print("=" * 60)
    
    # Connect to OpenRGB
    client = connect_to_openrgb()
    
    # Display detected devices
    print(f"\nDetected {len(client.devices)} RGB device(s):")
    for device in client.devices:
        print(f"  - {device.name} ({device.type.name})")
    
    # CRITICAL: Set Direct mode on ALL devices before the main loop
    # This is REQUIRED for Corsair RAM and ASUS Aura devices to respond
    set_direct_mode(client)
    
    print(f"\nMonitor: {MONITOR_INDEX}")
    print(f"Update threshold: {COLOR_THRESHOLD}")
    print("Press Ctrl+C to stop")
    print("-" * 60)
    
    last_color = None
    
    try:
        with mss.mss() as sct:
            if not 0 <= MONITOR_INDEX < len(sct.monitors):
                print(f"Error: monitor {MONITOR_INDEX} not found "
                      f"(available: 1-{len(sct.monitors) - 1})")
                return

            while True:
                try:
                    # Capture screen color
                    r, g, b = get_screen_center_color(sct, MONITOR_INDEX)

                    # Only update if color changed significantly
                    if color_changed(last_color, (r, g, b), COLOR_THRESHOLD):
                        set_all_devices_color(client, r, g, b)
                        print(f"Sent: R={r:3d} G={g:3d} B={b:3d}")
                        last_color = (r, g, b)

                    time.sleep(UPDATE_INTERVAL)

                except Exception as e:
                    print(f"Error: {e}")
                    time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nStopping MoodSync...")
    finally:
        # Reset to black on any exit, so the lights don't stay on the last color
        set_all_devices_color(client, 0, 0, 0)


if __name__ == "__main__":
    main()
