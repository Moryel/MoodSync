# MoodSync

Lighting that works with your focus, for **all PC RGB peripherals** via OpenRGB. Controls Razer, Corsair, ASUS Aura, MSI Mystic Light, Logitech, and 100+ other brands simultaneously.

- **Focus:** bright, cool daylight.
- **Getting tired:** as a focus block goes on (and in the evening) the light slowly shifts to a softer, warmer white.
- **Break:** warm, dim amber that slowly breathes (about 6 breaths a minute).
- **Automatic:** tiredness is detected from your typing rhythm, and optionally from your webcam (eye closure, long blinks, yawns). When it stays high, the break starts by itself.
- **Screen aware:** the focus light picks up a bit of your screen's color and dims when the screen is dark.
- **Eye care:** reminds you to blink when you stare (`--camera`), dims the screen against sudden bright flashes (`--flash-guard`) and softens large white areas (`--dim-white`).

MoodSync can also mirror the colors on your screen (`screen` program).

## Purpose

MoodSync is meant to make long hours at the computer easier on you, mostly on your eyes:

1. **A work rhythm with real breaks.** Focus blocks and breaks, ended early when you are clearly tired.
2. **Light that does not fight the screen.** The room light follows the screen's brightness, so a bright room next to a dark editor (or the other way round) does not wear you out.
3. **Help for the eyes where it is known to matter.** A reminder to blink, and protection against the screen suddenly becoming much brighter.

### What is and is not backed by research

- **Blue light is not the main problem.** A 2023 Cochrane review of 17 randomised trials found that blue-light filtering glasses make little or no difference to eye strain from screens [[1]](#sources) [[2]](#sources). That is why MoodSync does not filter blue light.
- **Blinking less is.** People blink far less while working at a screen, the tear film dries out, and that causes much of the discomfort [[3]](#sources) [[2]](#sources). That is why there is a blink reminder.
- **Brightness matters.** Reading on a very bright screen together with reduced blinking increases visual fatigue [[4]](#sources). That is why the screen guard dims sudden bright flashes and large white areas.
- **So does the match with the room.** A mismatch between room light and screen brightness is a problem of its own [[5]](#sources). Adaptive brightness helps modestly; one manufacturer estimates 7-17 % fewer eye strain symptoms than with fixed brightness [[6]](#sources). That is why the focus light follows the screen.
- **Dark mode is not always better.** Dark mode is found more comfortable in dim light and light mode in bright light, while reading speed and comprehension do not differ [[7]](#sources) [[8]](#sources). That is why nothing in MoodSync forces a dark look.
- **Eye closure is a recognised alertness measure.** The share of time the eyes are closed (PERCLOS) is a validated sign of drowsiness [[9]](#sources). The camera uses it to detect tiredness.

**Not backed by research:** the focus, tired and rest light colours are a matter of taste. There is no solid evidence that a particular light colour improves focus. The screen guard's timings (instant dimming, about 1 s to come back) are starting points tuned by feel, not research figures.

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

With `--camera` the webcam is watched too (MediaPipe face landmarks, about 15 frames a second, nothing is saved; off during breaks, in bursts on battery, see [Battery](#battery)):

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

### Battery

MoodSync follows the power source (`--power auto`, the default) and checks it every 30 s:

| | On the charger | On battery | Low power mode / battery saver |
|---|---|---|---|
| Light updates while it changes | 10/s | 5/s | 4/s |
| Screen program captures | 20/s | 10/s | 5/s |
| Screen guard samples | 2/s | 1/s | 1 every 2 s |
| Camera | on while focusing | 20 s every 2 minutes | off |
| White-area dimming | on | on | paused |

On all of them:

- **Nothing runs when nothing changes.** While the light is steady MoodSync updates it once a second; the faster rate is only used while it fades or breathes. The screen guard sleeps until its next sample instead of ticking 30 times a second.
- **The camera is off during breaks and while you are away.** When it is off, the camera hardware (and its light) is off too.
- **App switches come from the system** (macOS NSWorkspace notifications, Windows SetWinEventHook, Linux X11 events) instead of being asked for many times a second.
- **The screen is read sparsely:** 16 pixels per grid cell instead of every pixel (about 0.6 ms instead of 16 ms per sample).

What costs battery is mostly waking the processor up, not the work itself: a processor woken 30 times a second never reaches its deep sleep states. Measured on an M2 MacBook (Activity Monitor's *Energy Impact*):

| | Before | Now (charger) | Now (battery) |
|---|---|---|---|
| Focus light | 0.5 | 0.5 | |
| + flash guard | 2.9 | 1.1 | |
| + white-area dimming | 3.9 | 1.3 | 0.8 |

`--power full`, `--power battery` and `--power saver` force one behaviour; an explicit `--fps` always wins.

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
| `--power` | `auto`, `full`, `battery` or `saver` | `auto` |

Away detection reads the keyboard/mouse idle time: built in on macOS and Windows, needs `xprintidle` on Linux.

**macOS:** allow your terminal under System Settings → Privacy & Security → Screen Recording, otherwise only the wallpaper is captured.

## Tests

```bash
python -m unittest discover -s tests
```

## Sources

1. Singh S, Keller PR, Busija L, et al. *Blue-light filtering spectacle lenses for visual performance, sleep, and macular health in adults.* Cochrane Database of Systematic Reviews, 2023. https://doi.org/10.1002/14651858.CD013244.pub2
2. Acıbadem International. *Blue light glasses: do they actually work? The evidence, honestly* (plain-language summary). https://acibademinternational.com/blog/blue-light-glasses-do-they-actually-work-the-evidence-honestly/
3. Patel S, Henderson R, Bradley L, Galloway B, Hunter L. *Effect of visual display unit use on blink rate and tear stability.* Optometry and Vision Science, 1991. https://doi.org/10.1097/00006324-199111000-00010
4. Benedetto S, Carbone A, Drai-Zerbib V, Pedrotti M, Baccino T. *Effects of luminance and illuminance on visual fatigue and arousal during digital reading.* Computers in Human Behavior, 2014. https://doi.org/10.1016/j.chb.2014.09.023
5. Hou D, Xu W, Jing S, Lin Y. *Display dimming model characterized by three-dimensional ergonomic study.* Optical Engineering 60(3), 2021. https://doi.org/10.1117/1.OE.60.3.035110
6. Dell Technologies. *Estimating the benefits of advanced monitor functionality* (manufacturer white paper). https://www.delltechnologies.com/asset/en-us/products/electronics-and-accessories/industry-market/estimating-the-benefits-of-advanced-monitor-functionality.pdf
7. Sengsoon P, Intaruk R. *Immediate effects of light mode and dark mode features on visual fatigue in tablet users.* International Journal of Environmental Research and Public Health, 2025. https://doi.org/10.3390/ijerph22040609
8. Gadget Hacks. *Dark mode vs light mode: what research says about when each works best* (news summary). https://android.gadgethacks.com/news/dark-mode-vs-light-mode-what-research-says-about-when-each-works-best/
9. Dinges DF, Grace R. *PERCLOS: A valid psychophysiological measure of alertness as assessed by psychomotor vigilance.* Federal Highway Administration, 1998. https://doi.org/10.1037/e449092008-001

## License

MIT License
