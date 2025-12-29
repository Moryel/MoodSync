# MoodSync

Real-time screen color synchronization for **all PC RGB peripherals** via OpenRGB. Controls Razer, Corsair, ASUS Aura, MSI Mystic Light, Logitech, and 100+ other brands simultaneously.

## Prerequisites

> ⚠️ **IMPORTANT**: You must install OpenRGB Desktop Software first!

1. Download OpenRGB from [https://openrgb.org/](https://openrgb.org/)
2. Install and run OpenRGB
3. Go to **SDK Server** tab
4. Click **Start Server**
5. Keep OpenRGB running in the background

## ⚠️ CRITICAL: Troubleshooting RAM & Peripherals

> **YOU MUST CLOSE CORSAIR iCUE / RAZER SYNAPSE software completely. Also, run OpenRGB as Administrator to control RAM sticks.**

If your **Corsair RAM**, **ASUS Aura RAM**, or other devices are not reacting:

1. **Close ALL vendor RGB software:**
   - Corsair iCUE
   - Razer Synapse
   - ASUS Armoury Crate / Aura Sync
   - MSI Dragon Center / Mystic Light
   - Logitech G Hub

2. **Run OpenRGB as Administrator:**
   - Right-click OpenRGB → "Run as administrator"
   - This is REQUIRED for RAM stick control

3. **Check Device Detection:**
   - In OpenRGB, verify your RAM appears in the device list
   - If not, go to Settings → SMBus Tools → Rescan

4. **Reboot if necessary:**
   - Some devices require a full system restart after closing vendor software

## Installation

```bash
git clone https://github.com/Moryel/MoodSync
cd moodsync-ai
pip install -r requirements.txt
```

## Usage

1. Make sure OpenRGB is running with SDK Server started
2. Run the script:

```bash
python main.py
```

Example output:
```
============================================================
  MoodSync - PC Peripheral RGB Sync
============================================================

Detected 4 RGB device(s):
  - Razer Huntsman Elite (KEYBOARD)
  - Corsair Vengeance RGB Pro (DRAM)
  - ASUS ROG STRIX B550-F (MOTHERBOARD)
  - G.Skill Trident Z RGB (DRAM)

Enabling Direct mode on all devices...
  ✓ Razer Huntsman Elite: Direct mode enabled
  ✓ Corsair Vengeance RGB Pro: Direct mode enabled
  ✓ ASUS ROG STRIX B550-F: Direct mode enabled
  ✓ G.Skill Trident Z RGB: Direct mode enabled

Monitor: 1
Update threshold: 10
Press Ctrl+C to stop
------------------------------------------------------------
Sent: R=255 G=  0 B=  0
Sent: R=128 G= 64 B= 32
```

## Features

- 🎮 **Universal Control**: Works with ALL OpenRGB-supported devices
- ⚡ **Direct Mode**: Automatically enables Direct mode for instant updates (fixes Corsair RAM)
- 🧠 **Smart Updates**: Only sends data when color changes (saves CPU)
- 🛡️ **Safe**: Graceful error handling if OpenRGB is not running

## Supported Devices

OpenRGB supports 100+ brands including:
- Razer (Chroma)
- Corsair (iCUE) - **RAM, Keyboards, Mice, Headsets**
- ASUS (Aura Sync) - **Motherboards, RAM, GPUs**
- MSI (Mystic Light)
- Logitech (G Hub)
- HyperX
- SteelSeries
- G.Skill RAM
- NVIDIA/AMD GPUs
- And many more...

## Configuration

Edit the constants in `main.py`:

| Setting | Description | Default |
|---------|-------------|---------|
| `MONITOR_INDEX` | Monitor to capture (1 = primary) | `1` |
| `COLOR_THRESHOLD` | Minimum color change to trigger update | `10` |
| `UPDATE_INTERVAL` | Seconds between captures | `0.05` |

## License

MIT License
