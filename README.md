# MoodSync

Lighting that works with your focus, for **all PC RGB peripherals** via OpenRGB. Controls Razer, Corsair, ASUS Aura, MSI Mystic Light, Logitech, and 100+ other brands simultaneously.

- **Focus:** bright, cool daylight.
- **Getting tired:** as a focus block goes on (and in the evening) the light slowly shifts to a softer, warmer white.
- **Break:** warm, dim amber that slowly breathes (about 6 breaths a minute).
- **Automatic:** tiredness is detected from your typing rhythm, and optionally from your webcam (eye closure, long blinks, yawns). When it stays high, the break starts by itself.
- **Screen aware:** the focus light picks up a bit of your screen's color and dims when the screen is dark.
- **Eye care:** reminds you to blink when you stare (`--camera`), dims the screen against sudden bright flashes (`--flash-guard`) and softens large white areas (`--dim-white`).

MoodSync can also mirror the colors on your screen (`screen` program).

> **What is and is not proven.** The colours are a matter of taste; there is no solid evidence that a particular light colour improves focus, and blue-light filtering makes little or no difference to screen eye strain. What does matter for tired eyes: blinking less while staring at a screen (the tear film dries), screens much brighter than the room, and long stretches without a break. The break rhythm, the blink reminder and the brightness features target those.

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
cd MoodSync
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/pip install mediapipe             # only for --camera
```

Then run it with `.venv/bin/python main.py` (Windows: `.venv\Scripts\python main.py`).

## Usage

1. Make sure OpenRGB is running with SDK Server started
2. Run the script:

```bash
python main.py              # focus lighting (default)
python main.py screen       # mirror the screen colors
```

### Focus program

The rhythm follows the Pomodoro technique: 25 minutes of focus, a 5 minute break, and a 15 minute long break after every 4 blocks.

| Phase | Light |
|-------|-------|
| Focus, fresh | Cool daylight (`AAD2FF`), full brightness |
| Focus, second half / later blocks / evening | Slowly shifts to neutral warm white (`FFD6AA`), up to 30% dimmer |
| Break | Warm amber (`FF8228`), dim, breathing |
| Away (no keyboard/mouse input for 3 min) | Low amber glow, focus timer paused |

#### Automatic tiredness detection

MoodSync learns your normal typing rhythm in the first minutes (saved to `~/.moodsync.json`, refreshed at the start of later focus blocks) and then compares the last 3 minutes against it:

- **slower typing:** time between keystrokes
- **more corrections:** share of Backspace/Delete
- **more hesitation:** 2-30 second pauses

Only key timings and whether a key was Backspace/Delete are used, never which keys you typed. On macOS allow your terminal under System Settings → Privacy & Security → **Input Monitoring**.

With `--camera` the webcam is watched too (MediaPipe face landmarks, about 15 frames a second, nothing is saved):

- **eye closure (PERCLOS):** share of the last minute the eyes were closed
- **long blinks:** closures longer than 0.4 s
- **yawns:** mouth wide open for more than 1.5 s

**Blink reminder:** people blink about 15-20 times a minute, but often less than half as much while staring at a screen. When the camera counts fewer than 8 blinks a minute for 2 minutes during focus, the light dips twice and a short reminder appears (at most every 10 minutes, `--no-blink-reminder` to turn it off).

Eyes count 60% and typing 40% when both are available. The detected tiredness softens the light right away; when it stays above 70% for 3 minutes (and you have focused at least 10 minutes), the break starts by itself. `--no-auto-break` keeps the soft light but leaves breaks to the timer, `--no-auto` turns detection off. The face model (~4 MB) is downloaded once to `~/.moodsync/`; on macOS allow your terminal under **Camera**.

#### Screen

During focus the light takes 30% of the screen's average hue (`--screen-mix`) and dims down to 60% when the screen is dark (`--no-screen-dim` to keep it), so the room never glares next to a dark editor. Breaks ignore the screen. `--no-screen` turns this off.

Coming back after a short absence continues the same focus block; an absence longer than a break counts as a break. While it runs, type a letter and press Enter:

| Key | Action |
|-----|--------|
| `t` | I'm tired (on top of automatic detection): switch to the softer light until the next break (again = undo) |
| `b` | Start a break now |
| `f` | End the break / start focusing now |
| `s` | Show status |
| `q` | Quit |

```bash
python main.py --focus-minutes 50 --break-minutes 10   # longer deep-work blocks
python main.py --camera                                # also watch eyes and yawns
python main.py --evening 19                            # warmer light from 19:00
python main.py --rest-color 40C080                     # green breaks instead of amber
```

### Screen guard (both programs)

```bash
python main.py --flash-guard     # dim the whole screen against sudden bright flashes
python main.py --dim-white       # soften large white areas (white web pages, empty documents)
```

**Flash guard** dims the whole screen through the display's gamma curve (fast, and it does not show up in screenshots or screen recordings):

- *Ahead of time:* switching apps, opening a window or changing Spaces/desktops is what usually throws a bright page at you. When that happens while the screen is dark, it dims right away, before the new content is even measured.
- *Reacting:* the screen is sampled at low resolution, 2 times a second normally and 15 times a second around switches. A fast jump in brightness dims it immediately.
- Dimming is instant, coming back takes about a second (like the eye adapting). Content that keeps flashing (videos, animations) gets one steady dim instead of pulses, so the guard does not add flicker of its own.
- `--flash-strength` (default `0.4`) is the strongest dimming. The screen is put back exactly as it was when MoodSync stops; if it is killed while dimmed, the next start restores it.

**White-area dimming** lays see-through, click-through dark windows over large white areas. Everything under them gets darker by the same factor, so text keeps its contrast. Areas switch on after about 1 s and off after 1.5 s, with separate thresholds, so scrolling does not make them blink. `--dim-strength` (default `0.3`) is the darkest it gets.

The timings are starting points tuned by feel, not research figures. Sampling the screen costs a little CPU and battery, and protected video (Netflix and the like) is captured as black, so the guard cannot see it.

| | Flash guard | App/window switch | White-area windows |
|---|---|---|---|
| macOS | ✅ | ✅ (no extra permission) | ✅ |
| Windows | ✅ main monitor; Windows allows about 50% dimming at most | ✅ | ✅ |
| Linux X11 | ✅ | ✅ | ✅ with a compositor (most desktops have one) |
| Linux Wayland | ❌ no common way to do this | ❌ | ❌ |

### Screen program

```bash
python main.py screen --mode dominant   # follow the strongest color instead of the average
python main.py screen --monitor 2       # capture the second monitor
python main.py --list-monitors          # show monitor numbers
```

### For both

```bash
python main.py --devices corsair razer  # only control matching devices
python main.py --brightness 0.6         # dim the LEDs
python main.py --dry-run                # test without OpenRGB, colors are printed in the terminal
```

Example output:
```
============================================================
  MoodSync - Focus Lighting
============================================================

Detected 2 RGB device(s):
  - Razer Huntsman Elite (KEYBOARD)
  - Corsair Vengeance RGB Pro (DRAM)

Enabling Direct mode on all devices...
  ✓ Razer Huntsman Elite: Direct mode enabled
  ✓ Corsair Vengeance RGB Pro: Direct mode enabled

Focus 25 min, break 5 min, long break 15 min after 4 blocks
Type a letter + Enter: b = break now, f = focus now, t = I'm tired, q = quit
------------------------------------------------------------
Focus block 1/4 - 25 min. Bright light, time to work.
Focus 1/4  18:42 left  tiredness   0%
```

## Features

- 🎯 **Focus lighting**: Pomodoro rhythm, tiredness-aware tones, breathing break light, away detection
- 👁️ **Eye care**: blink reminder, flash guard and white-area dimming
- 🎮 **Universal Control**: Works with ALL OpenRGB-supported devices
- ⚡ **Direct Mode**: Automatically enables Direct mode for instant updates (fixes Corsair RAM)
- 🖥️ **Screen sync** with three sampling modes: `average` (whole screen, black bars ignored), `dominant` (strongest hue), `center` (100×100 center region)
- 🌈 **LED-friendly colors**: saturation boost, brightness cap and smooth fades
- 🧠 **Smart Updates**: Only sends data when color changes (saves CPU), steady frame rate
- 🔌 **Auto reconnect**: Keeps running if OpenRGB restarts, picks the devices up again
- 🛡️ **Safe**: Graceful error handling, sets a chosen color (default: off) on exit or SIGTERM

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

Every setting is a command line option (`python main.py --help`); the defaults live at the top of `main.py` and `focus.py`.

**Focus program**

| Option | Description | Default |
|--------|-------------|---------|
| `--focus-minutes` | Length of a focus block | `25` |
| `--break-minutes` | Length of a short break | `5` |
| `--long-break-minutes` | Length of the long break | `15` |
| `--cycles` | Focus blocks before a long break | `4` |
| `--idle-minutes` | No input this long counts as away (0 = off) | `3` |
| `--camera` / `--camera-index` | Also detect tiredness from the webcam | off / `0` |
| `--no-blink-reminder` | With `--camera`: no blink reminders | |
| `--no-auto` | Do not detect tiredness from typing | |
| `--no-auto-break` | Detect tiredness, but never start a break by itself | |
| `--screen-mix` | Share of the screen's color in the focus light (0-1) | `0.3` |
| `--no-screen-dim` / `--no-screen` | Do not dim with a dark screen / ignore the screen | |
| `--evening` | Hour from which the light starts warmer (-1 = off) | `20` |
| `--fade-seconds` | How long a change of light takes | `20` |
| `--focus-color` / `--tired-color` / `--rest-color` | Colors (`RRGGBB`) | `AAD2FF` / `FFD6AA` / `FF8228` |

**Screen (both programs, the focus light uses the average color)**

| Option | Description | Default |
|--------|-------------|---------|
| `--monitor` | Monitor to capture (1 = primary, 0 = all) | `1` |
| `--mode` | `average`, `dominant` or `center` | `average` |
| `--smoothing` | 0 = instant, 0.9 = very slow fades | `0.35` |
| `--saturation` | Saturation multiplier | `1.3` |

**Screen guard (both programs)**

| Option | Description | Default |
|--------|-------------|---------|
| `--flash-guard` / `--flash-strength` | Dim the screen against sudden flashes / strongest dimming (0-0.7) | off / `0.4` |
| `--dim-white` / `--dim-strength` | Soften large white areas / darkest dimming (0-0.6) | off / `0.3` |

**Both**

| Option | Description | Default |
|--------|-------------|---------|
| `--fps` | Updates per second | `10` focus / `20` screen |
| `--threshold` | Minimum color change (0-255) to trigger an update | `1` focus / `10` screen |
| `--brightness` | Maximum LED brightness (0-1) | `1.0` |
| `--devices` | Only control devices whose name contains these words | all |
| `--exit-color` | Color left on the devices when stopping (`RRGGBB`) | `000000` |
| `--host` / `--port` | OpenRGB SDK server | `127.0.0.1` / `6742` |

Away detection reads the keyboard/mouse idle time: built in on macOS and Windows, needs `xprintidle` on Linux.

**macOS:** allow your terminal under System Settings → Privacy & Security → Screen Recording, otherwise only the wallpaper is captured.

## Tests

```bash
python -m unittest discover -s tests
```

## License

MIT License
