"""
MoodSync - Focus lighting and Screen-to-RGB Peripheral Sync
Drives ALL PC peripherals via OpenRGB SDK, in one of two programs:
  focus  - bright, alerting light while you focus, softer tones as you tire,
           warm breathing light during breaks (see focus.py)
  screen - mirrors the colors on your screen
Supports: Razer, Corsair, ASUS Aura, MSI Mystic Light, and more.
"""

import argparse
import colorsys
import queue
import signal
import sys
import threading
import time

import mss
import mss.exception
import numpy as np

import camera
import fatigue
import focus

# Windows writes to pipes and log files in a legacy code page that has no ✓/✗:
# show a '?' there instead of crashing
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor, OpenRGBDisconnected
except ImportError:
    print("Error: openrgb-python not installed.")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)


# Default configuration (every value can be overridden from the command line)
PROGRAM = "focus"          # focus | screen
MONITOR_INDEX = 1          # 1 = primary monitor, 0 = all monitors combined
SAMPLE_MODE = "average"    # average | dominant | center
COLOR_THRESHOLD = 10       # Minimum color change to trigger update (saves CPU)
UPDATE_INTERVAL = 0.05     # Seconds between captures (50ms = 20 FPS)
FOCUS_FPS = 10             # Focus mode only needs enough frames for smooth fades
FOCUS_THRESHOLD = 1        # Small steps keep fades smooth in focus mode
IDLE_CHECK_INTERVAL = 5    # Seconds between keyboard/mouse idle checks
SCREEN_CHECK_INTERVAL = 1  # Seconds between screen samples in focus mode
SCREEN_RETRY_SECONDS = 30  # Wait this long after the screen could not be read
FATIGUE_CHECK_INTERVAL = 30  # Seconds between tiredness estimates from typing
NO_KEYS_HINT_SECONDS = 180   # Warn if no keys arrive this long while the user is active
SMOOTHING = 0.35           # 0 = no smoothing, closer to 1 = slower fades
SATURATION_BOOST = 1.3     # Screen colors look washed out on LEDs, boost them
MAX_BRIGHTNESS = 1.0       # 0..1, caps the LED brightness
BLACK_LEVEL = 20           # Pixels darker than this are ignored (letterbox bars)
SAMPLE_SIZE = 64           # Screen is downscaled to roughly this many pixels wide
OPENRGB_HOST = "127.0.0.1"
OPENRGB_PORT = 6742
RECONNECT_DELAY = 3        # Seconds between reconnect attempts

# mss 10 renamed mss.mss to mss.MSS
ScreenCapture = getattr(mss, "MSS", None) or mss.mss

# Errors that mean the OpenRGB server went away
CONNECTION_ERRORS = (OpenRGBDisconnected, ConnectionError, OSError)


def parse_args(argv=None) -> argparse.Namespace:
    """Reads the command line options, falling back to the defaults above."""
    parser = argparse.ArgumentParser(
        description="Focus lighting and screen color sync for your RGB peripherals (via OpenRGB).")
    parser.add_argument("program", nargs="?", choices=["focus", "screen"], default=PROGRAM,
                        help="focus = light that follows your focus/break rhythm (default), "
                             "screen = mirror the screen colors")

    timing = parser.add_argument_group("focus program")
    defaults = focus.FocusSettings()
    timing.add_argument("--focus-minutes", type=float, default=defaults.focus_minutes,
                        help="length of a focus block")
    timing.add_argument("--break-minutes", type=float, default=defaults.break_minutes,
                        help="length of a short break")
    timing.add_argument("--long-break-minutes", type=float, default=defaults.long_break_minutes,
                        help="length of the long break")
    timing.add_argument("--cycles", type=int, default=defaults.cycles,
                        help="focus blocks before a long break")
    timing.add_argument("--idle-minutes", type=float, default=defaults.idle_minutes,
                        help="no keyboard/mouse input this long counts as away (0 = off)")
    timing.add_argument("--no-auto", action="store_true",
                        help="do not detect tiredness from typing")
    timing.add_argument("--no-auto-break", action="store_true",
                        help="detect tiredness, but never start a break by itself")
    timing.add_argument("--camera", action="store_true",
                        help="also detect tiredness from the webcam (eyes and yawns, needs mediapipe)")
    timing.add_argument("--camera-index", type=int, default=0, metavar="N",
                        help="which camera to use")
    timing.add_argument("--screen-mix", type=float, default=0.3,
                        help="share of the screen's average color mixed into the focus light (0 = none)")
    timing.add_argument("--no-screen-dim", action="store_true",
                        help="do not dim the light when the screen is dark")
    timing.add_argument("--no-screen", action="store_true",
                        help="do not look at the screen at all in focus mode")
    timing.add_argument("--evening", type=int, default=defaults.evening_hour, metavar="HOUR",
                        help="from this hour on the light starts warmer (-1 = off)")
    timing.add_argument("--fade-seconds", type=float, default=defaults.fade_seconds,
                        help="how long a change of light takes")
    timing.add_argument("--focus-color", default="AAD2FF", metavar="RRGGBB",
                        help="light while fresh and focused")
    timing.add_argument("--tired-color", default="FFD6AA", metavar="RRGGBB",
                        help="light the focus color shifts to as you tire")
    timing.add_argument("--rest-color", default="FF8228", metavar="RRGGBB",
                        help="light during breaks")

    screen = parser.add_argument_group("screen program")
    screen.add_argument("-m", "--monitor", type=int, default=MONITOR_INDEX,
                        help="monitor to capture (1 = primary, 0 = all monitors)")
    screen.add_argument("--mode", choices=["average", "dominant", "center"], default=SAMPLE_MODE,
                        help="how the screen color is picked")
    screen.add_argument("--smoothing", type=float, default=SMOOTHING,
                        help="0 = instant, 0.9 = very slow fades")
    screen.add_argument("--saturation", type=float, default=SATURATION_BOOST,
                        help="saturation multiplier (1 = unchanged)")

    parser.add_argument("--fps", type=float,
                        help=f"updates per second (default {FOCUS_FPS} for focus, "
                             f"{1 / UPDATE_INTERVAL:g} for screen)")
    parser.add_argument("--threshold", type=int,
                        help="minimum color change (0-255) that triggers an LED update "
                             f"(default {FOCUS_THRESHOLD} for focus, {COLOR_THRESHOLD} for screen)")
    parser.add_argument("--brightness", type=float, default=MAX_BRIGHTNESS,
                        help="maximum LED brightness, 0-1")
    parser.add_argument("--host", default=OPENRGB_HOST, help="OpenRGB SDK server address")
    parser.add_argument("--port", type=int, default=OPENRGB_PORT, help="OpenRGB SDK server port")
    parser.add_argument("--devices", nargs="+", metavar="NAME",
                        help="only control devices whose name contains one of these words")
    parser.add_argument("--exit-color", default="000000", metavar="RRGGBB",
                        help="color left on the devices when MoodSync stops")
    parser.add_argument("--dry-run", action="store_true",
                        help="do not connect to OpenRGB, just print the colors")
    parser.add_argument("--list-monitors", action="store_true",
                        help="print the available monitors and exit")
    args = parser.parse_args(argv)

    if args.fps is None:
        args.fps = FOCUS_FPS if args.program == "focus" else 1 / UPDATE_INTERVAL
    if args.threshold is None:
        args.threshold = FOCUS_THRESHOLD if args.program == "focus" else COLOR_THRESHOLD
    for name in ("focus_minutes", "break_minutes", "long_break_minutes"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be greater than 0")
    if not 0 <= args.screen_mix <= 1:
        parser.error("--screen-mix must be between 0 and 1")
    if args.cycles < 1:
        parser.error("--cycles must be 1 or more")
    if not -1 <= args.evening <= 23:
        parser.error("--evening must be an hour between 0 and 23, or -1")
    for name in ("focus_color", "tired_color", "rest_color"):
        try:
            setattr(args, name, parse_hex_color(getattr(args, name)))
        except ValueError:
            parser.error(f"--{name.replace('_', '-')} must look like FF8800")
    if args.fps <= 0:
        parser.error("--fps must be greater than 0")
    if not 0 <= args.smoothing < 1:
        parser.error("--smoothing must be between 0 and 1 (1 excluded)")
    if not 0 <= args.brightness <= 1:
        parser.error("--brightness must be between 0 and 1")
    if args.saturation < 0:
        parser.error("--saturation must be 0 or more")
    try:
        args.exit_color = parse_hex_color(args.exit_color)
    except ValueError:
        parser.error("--exit-color must look like FF8800")
    return args


def parse_hex_color(text: str) -> tuple:
    """Turns 'FF8800' or '#ff8800' into (255, 136, 0)."""
    text = text.lstrip("#")
    if len(text) != 6:
        raise ValueError(text)
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def connect_to_openrgb(host: str, port: int, quiet: bool = False):
    """
    Connects to the OpenRGB SDK Server.
    Returns the client if successful, None if the server is not reachable.
    """
    try:
        return OpenRGBClient(host, port, name="MoodSync")
    except CONNECTION_ERRORS:
        if not quiet:
            print("=" * 60)
            print("  ERROR: Cannot connect to OpenRGB SDK Server")
            print(f"  ({host}:{port})")
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
        return None


def select_devices(client, name_filters) -> list:
    """Returns the devices to control, optionally filtered by name."""
    devices = list(client.devices)
    if name_filters:
        wanted = [f.lower() for f in name_filters]
        devices = [d for d in devices if any(w in d.name.lower() for w in wanted)]
    return devices


def set_direct_mode(devices: list):
    """
    CRITICAL: Sets all devices to 'Direct' mode for fastest LED updates.

    This is REQUIRED for Corsair RAM, ASUS Aura, and some other devices.
    Without Direct mode, these devices will ignore color commands completely.

    The function iterates through each device's available modes and activates
    'Direct' mode if it exists. This must be done BEFORE sending any colors.
    """
    print("\nEnabling Direct mode on all devices...")

    for device in devices:
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
                except CONNECTION_ERRORS:
                    raise
                except Exception as e:
                    print(f"  ✗ {device_name}: Failed to set Direct mode ({e})")
                break

        # If no Direct mode found, device will use its current mode
        if not direct_mode_found:
            print(f"  - {device_name}: No Direct mode available (using default)")


def grab_screen(sct, monitor_index: int, mode: str) -> np.ndarray:
    """
    Captures the screen (or its center for 'center' mode) and returns a small
    RGB image of shape (h, w, 3). Downscaling keeps the per-frame cost low.
    """
    monitor = sct.monitors[monitor_index]

    if mode == "center":
        # Center region (100x100 pixels)
        region_size = 100
        monitor = {
            "left": monitor["left"] + monitor["width"] // 2 - region_size // 2,
            "top": monitor["top"] + monitor["height"] // 2 - region_size // 2,
            "width": region_size,
            "height": region_size,
        }

    # Capture and convert BGRA -> RGB
    img = np.asarray(sct.grab(monitor))[:, :, 2::-1]
    step = max(1, img.shape[1] // SAMPLE_SIZE)
    return img[::step, ::step]


def pick_color(img: np.ndarray, mode: str, black_level: int = BLACK_LEVEL) -> tuple:
    """
    Reduces an RGB image to a single (R, G, B) color.

    average:  mean of all pixels that are not (nearly) black
    dominant: most common hue among the colorful pixels, weighted by saturation
    center:   plain mean (the image is already the center region)
    """
    pixels = img.reshape(-1, 3).astype(np.float32)

    if mode == "center":
        return tuple(int(v) for v in pixels.mean(axis=0))

    # Ignore black bars and dark pixels, they would just dim the result
    lit = pixels[pixels.max(axis=1) > black_level]
    if len(lit) == 0:
        return (0, 0, 0)

    if mode == "dominant":
        mx = lit.max(axis=1)
        mn = lit.min(axis=1)
        saturation = (mx - mn) / np.maximum(mx, 1)
        is_colorful = saturation > 0.25
        colorful = lit[is_colorful]
        if len(colorful) >= max(10, len(lit) // 50):
            # Group the colorful pixels by hue (12 buckets) and keep the biggest group
            r, g, b = colorful[:, 0], colorful[:, 1], colorful[:, 2]
            hue = np.degrees(np.arctan2(np.sqrt(3) * (g - b), 2 * r - g - b)) % 360
            buckets = (hue // 30).astype(int)
            best = np.bincount(buckets, weights=saturation[is_colorful], minlength=12).argmax()
            lit = colorful[buckets == best]

    return tuple(int(v) for v in lit.mean(axis=0))


def adjust_color(color: tuple, saturation: float, brightness: float) -> tuple:
    """Boosts saturation and caps brightness so LEDs look closer to the screen."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in color))
    s = min(1.0, s * saturation)
    v = min(v, brightness)
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h, s, v))


def smooth_color(previous, target: tuple, smoothing: float) -> tuple:
    """Exponential smoothing: moves part of the way from previous to target."""
    if previous is None or smoothing <= 0:
        return target
    return tuple(int(round(p * smoothing + t * (1 - smoothing))) for p, t in zip(previous, target))


def color_changed(old, new: tuple, threshold: int) -> bool:
    """
    Checks if the color has changed significantly to avoid unnecessary updates.
    """
    if old is None:
        return True
    return (abs(old[0] - new[0]) > threshold or
            abs(old[1] - new[1]) > threshold or
            abs(old[2] - new[2]) > threshold)


def set_all_devices_color(devices: list, r: int, g: int, b: int):
    """
    Sets the color of ALL selected RGB devices.
    """
    color = RGBColor(r, g, b)
    for device in devices:
        try:
            # fast=True skips re-reading the device state, much quicker in a loop
            device.set_color(color, fast=True)
        except CONNECTION_ERRORS:
            raise
        except Exception:
            # Skip devices that fail (some may be busy)
            pass


def swatch(r: int, g: int, b: int) -> str:
    """A small colored block for terminals that support 24-bit color."""
    return f"\033[48;2;{r};{g};{b}m      \033[0m"


def list_monitors():
    """Prints the monitors mss can capture."""
    with ScreenCapture() as sct:
        for index, mon in enumerate(sct.monitors):
            label = "all monitors" if index == 0 else ("primary" if index == 1 else "")
            print(f"  {index}: {mon['width']}x{mon['height']} at ({mon['left']}, {mon['top']}) {label}")


def setup_devices(args):
    """Connects to OpenRGB, prints the devices and enables Direct mode."""
    client = connect_to_openrgb(args.host, args.port)
    if client is None:
        sys.exit(1)

    devices = select_devices(client, args.devices)
    print(f"\nDetected {len(client.devices)} RGB device(s):")
    for device in client.devices:
        mark = "" if device in devices else "  (skipped)"
        print(f"  - {device.name} ({device.type.name}){mark}")

    if not devices:
        print("\nNo devices to control. Check OpenRGB's device list or the --devices filter.")
        sys.exit(1)

    # CRITICAL: Set Direct mode on ALL devices before the main loop
    # This is REQUIRED for Corsair RAM and ASUS Aura devices to respond
    set_direct_mode(devices)
    return client, devices


def reconnect(args):
    """Waits until the OpenRGB server is back, then sets the devices up again."""
    print(f"\nLost connection to OpenRGB, retrying every {RECONNECT_DELAY}s...")
    while True:
        time.sleep(RECONNECT_DELAY)
        client = connect_to_openrgb(args.host, args.port, quiet=True)
        if client is None:
            continue
        devices = select_devices(client, args.devices)
        if not devices:
            continue
        try:
            set_direct_mode(devices)
        except CONNECTION_ERRORS:
            continue
        print("Reconnected.")
        return client, devices


def stop_on_sigterm(signum, frame):
    """Treat service stops (SIGTERM) like Ctrl+C so the exit color is applied."""
    raise KeyboardInterrupt


def read_commands(commands: queue.Queue):
    """Reads the one-letter commands typed in the terminal (letter + Enter)."""
    for line in sys.stdin:
        commands.put(line.strip().lower())


class ScreenProgram:
    """Mirrors the colors on the screen."""

    def __init__(self, args):
        self.args = args
        self.sct = None
        self.current = None
        self.retry_at = 0.0
        self.waiting = False

    def command(self, cmd: str, now: float):
        pass

    def close(self):
        if self.sct is not None:
            self.sct.close()
            self.sct = None

    def next_color(self, now: float):
        if now < self.retry_at:
            return None
        try:
            if self.sct is None:
                self.sct = ScreenCapture()
            img = grab_screen(self.sct, self.args.monitor, self.args.mode)
        except (mss.exception.ScreenShotError, IndexError) as e:
            # Display asleep, locked or unplugged: wait for it with a fresh
            # capture each time (mss caches the monitor list)
            self.close()
            self.retry_at = now + SCREEN_RETRY_SECONDS
            if not self.waiting:
                reason = "no monitor found" if isinstance(e, IndexError) else e
                print(f"No screen to capture right now ({reason}), "
                      f"trying again every {SCREEN_RETRY_SECONDS}s...")
                self.waiting = True
            return None
        if self.waiting:
            print("Screen is back.")
            self.waiting = False
        target = adjust_color(pick_color(img, self.args.mode), self.args.saturation, self.args.brightness)
        self.current = smooth_color(self.current, target, self.args.smoothing)
        return self.current

    def sent(self, color: tuple):
        r, g, b = color
        print(f"Sent: R={r:3d} G={g:3d} B={b:3d} {swatch(r, g, b)}")


PHASE_MESSAGES = {
    focus.FOCUS: "Focus block {cycle}/{cycles} - {minutes:g} min. Bright light, time to work.",
    focus.BREAK: "Break - {minutes:g} min. Look away from the screen and breathe with the light.",
    focus.LONG_BREAK: "Long break - {minutes:g} min. Stand up, stretch, drink some water.",
    focus.AWAY: "You seem to be away - light dimmed, focus timer paused.",
}


class FocusProgram:
    """Light that follows the focus/break rhythm (logic lives in focus.py)."""

    def __init__(self, args, now: float):
        self.args = args
        self.use_screen = not args.no_screen
        self.sct = None              # Screen capture, opened on first use
        self.screen_color = None     # Average screen color (saturation boosted)
        self.screen_light = 1.0      # Average screen brightness, 0-1
        self.screen_checked = now - SCREEN_CHECK_INTERVAL
        self.settings = focus.FocusSettings(
            focus_minutes=args.focus_minutes,
            break_minutes=args.break_minutes,
            long_break_minutes=args.long_break_minutes,
            cycles=args.cycles,
            idle_minutes=args.idle_minutes,
            auto_break=not args.no_auto_break,
            evening_hour=args.evening,
            fade_seconds=args.fade_seconds,
            focus_color=args.focus_color,
            tired_color=args.tired_color,
            rest_color=args.rest_color,
        )
        self.session = focus.FocusSession(self.settings, now)
        self.fader = focus.Fader(args.fade_seconds)
        self.last_tick = now
        self.idle = None
        self.idle_checked = now
        self.color = (0, 0, 0)
        self.last_status = -1.0
        self.live_status = sys.stdout.isatty()

        self.watch_idle = args.idle_minutes > 0
        if self.watch_idle:
            self.idle = focus.idle_seconds()
            if self.idle is None:
                print("Note: keyboard/mouse idle time is not available, away detection is off.")
                self.watch_idle = False

        # Automatic tiredness detection from the typing rhythm
        self.detector = None
        self.fatigue_checked = now
        self.block = self.session.block
        self.no_keys_hint = False
        if not args.no_auto:
            log = fatigue.KeyLog()
            listener, problem = fatigue.start_key_listener(log, time.monotonic)
            if problem and listener is None:
                print(f"Note: automatic tiredness detection is off - {problem}.")
            elif problem:
                print(f"Note: {problem}.")
            if listener is not None:
                self.detector = fatigue.FatigueDetector(log)
                self.detector.new_block(now)
                if self.detector.learning:
                    print("Learning your normal typing rhythm first (a few minutes of typing).")

        # Optional camera: eye closure, long blinks and yawns
        self.camera = None
        self.eyes = None
        if args.camera:
            watcher = camera.CameraWatcher(args.camera_index)
            problem = watcher.start()
            if problem:
                print(f"Note: camera tiredness detection is off - {problem}.")
            else:
                self.camera = watcher
                print("Camera on: watching eye closure, long blinks and yawns (nothing is recorded).")
        self.announce(now)

    def announce(self, now: float):
        s = self.session
        text = PHASE_MESSAGES[s.phase].format(
            cycle=s.cycle, cycles=self.settings.cycles, minutes=s.phase_length() / 60)
        print(("\n" if self.live_status else "") + text)
        self.last_status = -1.0

    def command(self, cmd: str, now: float):
        s = self.session
        if cmd == "q":
            raise KeyboardInterrupt
        if cmd == "b" and s.phase in (focus.FOCUS, focus.AWAY):
            s.start_break(now)
        elif cmd == "f" and s.phase != focus.FOCUS:
            if s.phase == focus.AWAY:
                s.update(now, 0)
            else:
                s.start_focus(now)
        elif cmd == "t" and s.phase == focus.FOCUS:
            s.tired = not s.tired
            print("\nOkay, softer light until the next break." if s.tired else "\nBack to full focus light.")
            return
        elif cmd in ("", "s"):
            self.last_status = -1.0
            return
        else:
            print("\nCommands: b = break now, f = focus now, t = I'm tired, s = status, q = quit")
            return
        self.announce(now)

    def idle_estimate(self, now: float):
        """Idle seconds, read from the system every few seconds and extrapolated between reads."""
        if not self.watch_idle:
            return None
        if now - self.idle_checked >= IDLE_CHECK_INTERVAL:
            self.idle = focus.idle_seconds()
            self.idle_checked = now
            if self.idle is None:
                return None
        return self.idle + (now - self.idle_checked)

    def note(self, text: str):
        """Prints a message without breaking the live status line."""
        print(("\n" if self.live_status else "") + text)
        self.last_status = -1.0

    def check_fatigue(self, now: float):
        """Feeds the tiredness detected from typing (and the camera) into the session."""
        if self.detector is None and self.camera is None:
            return
        if self.detector is not None and self.session.block != self.block:
            # A new focus block after a break: start fresh
            self.block = self.session.block
            self.detector.new_block(now)
        if now - self.fatigue_checked < FATIGUE_CHECK_INTERVAL:
            return
        self.fatigue_checked = now

        typing = None
        if self.detector is not None:
            was_learning = self.detector.learning
            typing = self.detector.update(now)
            if was_learning and not self.detector.learning:
                self.note("Learned your normal typing rhythm.")
            if self.detector.learning:
                typing = None

        eyes = None
        if self.camera is not None:
            if self.camera.problem:
                self.note(f"Note: camera tiredness detection stopped - {self.camera.problem}.")
                self.camera = None
            else:
                eyes = self.camera.tracker.score(now)
        self.eyes = eyes

        # Eyes are the stronger sign; without new information keep the last level
        if eyes is not None and typing is not None:
            level = 0.6 * eyes + 0.4 * typing
        elif eyes is not None:
            level = eyes
        elif typing is not None:
            level = typing
        else:
            return
        if self.session.set_auto_fatigue(level, now):
            signs = " and ".join(name for name, value in (("your eyes", eyes), ("your typing", typing))
                                 if value is not None and value >= 0.5) or "you"
            self.note(f"Signs of tiredness from {signs} - time for a break.")
            self.announce(now)

        # Keys never arrive although the user is active: the keyboard is not readable
        if (self.detector is not None and not self.no_keys_hint and self.detector.log.total == 0
                and self.idle is not None and self.idle < 60
                and now - self.detector.block_start > NO_KEYS_HINT_SECONDS):
            self.no_keys_hint = True
            self.note("Note: no keystrokes are reaching MoodSync. On macOS allow your terminal under "
                      "System Settings -> Privacy & Security -> Input Monitoring.")

    def close_screen(self):
        if self.sct is not None:
            self.sct.close()
            self.sct = None

    def close(self):
        self.close_screen()
        if self.camera is not None:
            self.camera.stop()

    def check_screen(self, now: float):
        """Samples the screen about once a second for its average color and brightness."""
        if not self.use_screen or now - self.screen_checked < SCREEN_CHECK_INTERVAL:
            return
        self.screen_checked = now
        try:
            if self.sct is None:
                self.sct = ScreenCapture()
            img = grab_screen(self.sct, self.args.monitor, "average")
        except (mss.exception.ScreenShotError, IndexError):
            # Display asleep, locked or unplugged: go on without it and look again
            # later with a fresh capture (mss caches the monitor list)
            self.close_screen()
            self.screen_color = None
            self.screen_checked = now + SCREEN_RETRY_SECONDS
            return
        self.screen_color = adjust_color(pick_color(img, "average"), self.args.saturation, 1.0)
        self.screen_light = float(np.mean(img)) / 255

    def next_color(self, now: float):
        dt, self.last_tick = now - self.last_tick, now
        if self.session.update(now, self.idle_estimate(now)):
            self.announce(now)
        self.check_fatigue(now)
        self.check_screen(now)

        hour = time.localtime().tm_hour
        target = self.session.target(now, hour)
        if self.session.phase == focus.FOCUS and self.screen_color is not None:
            # Breaks stay pure rest light, only focus follows the screen
            target = focus.with_screen(target, self.screen_color, self.screen_light,
                                       self.args.screen_mix, not self.args.no_screen_dim)
        state = self.fader.step(target, dt)
        self.color = focus.light_color(state, now, self.settings.breath_seconds, self.args.brightness)
        self.status(now, hour)
        return self.color

    def status(self, now: float, hour: int):
        """One status line: updated every second in a terminal, every minute in a log."""
        if now - self.last_status < (1 if self.live_status else 60):
            return
        self.last_status = now
        s = self.session
        label = {focus.FOCUS: f"Focus {s.cycle}/{self.settings.cycles}", focus.BREAK: "Break",
                 focus.LONG_BREAK: "Long break", focus.AWAY: "Away"}[s.phase]
        line = label
        if s.phase != focus.AWAY:
            left = int(s.remaining(now))
            line += f"  {left // 60:02d}:{left % 60:02d} left"
        if s.phase == focus.FOCUS:
            line += f"  tiredness {int(s.fatigue(now, hour) * 100):3d}%"
            if self.detector is not None:
                line += "  (learning rhythm)" if self.detector.learning else f"  detected {int(s.auto_fatigue * 100):3d}%"
            if self.camera is not None:
                line += "  eyes --" if self.eyes is None else f"  eyes {int(self.eyes * 100):3d}%"
        line += f"  {swatch(*self.color)}"
        if self.live_status:
            print(f"\r{line}\033[K", end="", flush=True)
        else:
            print(line, flush=True)

    def sent(self, color: tuple):
        pass


def main(argv=None):
    """Main loop for MoodSync with OpenRGB."""
    args = parse_args(argv)

    if args.list_monitors:
        list_monitors()
        return

    print("=" * 60)
    print("  MoodSync - " + ("Focus Lighting" if args.program == "focus" else "PC Peripheral RGB Sync"))
    print("=" * 60)

    signal.signal(signal.SIGTERM, stop_on_sigterm)

    if args.dry_run:
        client, devices = None, []
        print("\nDry run: OpenRGB is not used, colors are only printed.")
    else:
        client, devices = setup_devices(args)

    interval = 1 / args.fps
    if args.program == "screen":
        print(f"\nMonitor: {args.monitor}   Mode: {args.mode}   FPS: {args.fps:g}")
        print(f"Update threshold: {args.threshold}   Smoothing: {args.smoothing}")
    else:
        print(f"\nFocus {args.focus_minutes:g} min, break {args.break_minutes:g} min, "
              f"long break {args.long_break_minutes:g} min after {args.cycles} blocks")

    commands = queue.Queue()
    if args.program == "focus" and sys.stdin.isatty():
        threading.Thread(target=read_commands, args=(commands,), daemon=True).start()
        print("Type a letter + Enter: b = break now, f = focus now, t = I'm tired, q = quit")
    else:
        print("Press Ctrl+C to stop")
    print("-" * 60)

    last_sent = None

    if args.program == "screen":
        # A wrong monitor number is a mistake; no monitors at all just means the display sleeps
        with ScreenCapture() as sct:
            monitors = len(sct.monitors)
        if monitors > 1 and not 0 <= args.monitor < monitors:
            print(f"Monitor {args.monitor} does not exist. Available monitors:")
            list_monitors()
            sys.exit(1)
        program = ScreenProgram(args)
    else:
        program = FocusProgram(args, time.monotonic())

    # Both programs open the screen themselves, so they recover from a sleeping display
    try:
        while True:
            started = time.monotonic()
            while not commands.empty():
                program.command(commands.get(), started)

            color = program.next_color(started)
            try:
                # Only update if color changed significantly
                if color is not None and color_changed(last_sent, color, args.threshold):
                    if not args.dry_run:
                        set_all_devices_color(devices, *color)
                    program.sent(color)
                    last_sent = color
            except CONNECTION_ERRORS:
                client, devices = reconnect(args)
                last_sent = None

            # Keep a steady frame rate regardless of how long the work took
            time.sleep(max(0.0, interval - (time.monotonic() - started)))

    except KeyboardInterrupt:
        print("\n\nStopping MoodSync...")
    finally:
        # Leave the exit color however MoodSync stops (Ctrl+C, SIGTERM or an
        # unexpected error), so the lights never stay on the last color
        if not args.dry_run:
            try:
                set_all_devices_color(devices, *args.exit_color)
            except CONNECTION_ERRORS:
                pass
        program.close()
        if client is not None:
            try:
                client.disconnect()
            except CONNECTION_ERRORS:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Stopped while still starting up (connecting, loading the camera model...)
        print("\nStopped.")
