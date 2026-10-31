"""
MoodSync focus mode - lighting that follows your work rhythm.

Focus:  bright, cool daylight (the colours are a preference, not a proven effect).
Tired:  as the session goes on (or in the evening) the light slowly shifts to a
        softer, less harsh tone so it stops pushing you without breaking focus.
        Tiredness is also detected automatically from your typing (fatigue.py);
        when it stays high the break starts on its own.
Break:  warm, dim amber that slowly "breathes" (about 6 breaths a minute) to
        help you rest. Stepping away from the computer counts as a break.

Timing follows the Pomodoro rhythm: focus blocks, short breaks and a long
break after every few blocks. All of it is configurable.
"""

import ctypes
import math
import re
import subprocess
import sys
from dataclasses import dataclass

FOCUS = "focus"
BREAK = "break"
LONG_BREAK = "long break"
AWAY = "away"

# Default colors (before brightness is applied)
FOCUS_COLOR = (170, 210, 255)   # cool daylight (~6500K)
TIRED_COLOR = (255, 214, 170)   # neutral warm white (~4000K), calm but awake
REST_COLOR = (255, 130, 40)     # warm amber (~2200K)

BACK_IDLE_SECONDS = 5           # Idle time below this means the user is back


@dataclass
class FocusSettings:
    focus_minutes: float = 25
    break_minutes: float = 5
    long_break_minutes: float = 15
    cycles: int = 4                 # Focus blocks before a long break
    idle_minutes: float = 3         # No input this long during focus = away
    auto_break: bool = True         # Start a break by itself when you are clearly tired
    auto_break_level: float = 0.7   # Detected tiredness that counts as clearly tired
    auto_break_minutes: float = 3   # ...for this long
    min_focus_minutes: float = 10   # No automatic break earlier than this in a block
    evening_hour: int = 20          # From this hour on light starts warmer (-1 = off)
    fade_seconds: float = 20        # How long a phase change fades
    breath_seconds: float = 10      # One breath during breaks
    focus_color: tuple = FOCUS_COLOR
    tired_color: tuple = TIRED_COLOR
    rest_color: tuple = REST_COLOR


def blend(a: tuple, b: tuple, t: float) -> tuple:
    """Linear mix of two colors, t=0 -> a, t=1 -> b."""
    return tuple(x + (y - x) * t for x, y in zip(a, b))


class FocusSession:
    """
    Keeps track of the focus/break rhythm and decides which light fits.
    Time is passed in from outside (monotonic seconds) so it is easy to test.
    """

    def __init__(self, settings: FocusSettings, now: float):
        self.s = settings
        self.phase = FOCUS
        self.phase_started = now
        self.cycle = 1               # Which focus block within the set (1..cycles)
        self.tired = False           # Set by the user, lasts until the next break
        self.away_started = None
        self.auto_fatigue = 0.0      # Tiredness detected from typing (0-1)
        self.tired_since = None      # When detected tiredness became high
        self.block = 1               # Counts focus blocks, so callers notice a new one

    # ----- timing -----

    def phase_length(self) -> float:
        """Length of the current phase in seconds (0 for 'away')."""
        return {
            FOCUS: self.s.focus_minutes,
            BREAK: self.s.break_minutes,
            LONG_BREAK: self.s.long_break_minutes,
        }.get(self.phase, 0) * 60

    def remaining(self, now: float) -> float:
        if self.phase == AWAY:
            return 0
        return max(0.0, self.phase_length() - (now - self.phase_started))

    def _start(self, phase: str, now: float) -> str:
        self.phase = phase
        self.phase_started = now
        return phase

    def start_break(self, now: float) -> str:
        """Ends the focus block and starts a short or long break."""
        self._rested()
        long_one = self.cycle >= self.s.cycles
        return self._start(LONG_BREAK if long_one else BREAK, now)

    def start_focus(self, now: float) -> str:
        """Starts the next focus block (after a break)."""
        if self.phase in (BREAK, LONG_BREAK):
            self.cycle = 1 if self.phase == LONG_BREAK else self.cycle + 1
            self.block += 1
        return self._start(FOCUS, now)

    def _rested(self):
        """A break wipes out tiredness, set by hand or detected."""
        self.tired = False
        self.auto_fatigue = 0.0
        self.tired_since = None

    def set_auto_fatigue(self, level: float, now: float) -> str | None:
        """
        Takes the tiredness detected from typing. When it stays high long
        enough during focus, starts a break and returns its phase.
        """
        if self.phase != FOCUS:
            return None
        self.auto_fatigue = level
        if level < self.s.auto_break_level:
            self.tired_since = None
            return None
        if self.tired_since is None:
            self.tired_since = now
        worked = now - self.phase_started
        if (self.s.auto_break and worked >= self.s.min_focus_minutes * 60
                and now - self.tired_since >= self.s.auto_break_minutes * 60):
            return self.start_break(now)
        return None

    def update(self, now: float, idle_seconds) -> str | None:
        """
        Advances the rhythm. idle_seconds is the time since the last keyboard or
        mouse input (None if unknown). Returns the new phase when it changed.
        """
        if self.phase == AWAY:
            if idle_seconds is not None and idle_seconds >= BACK_IDLE_SECONDS:
                return None
            # The user is back: a long enough absence counts as a break
            away_for = now - self.away_started
            if away_for < self.s.break_minutes * 60:
                # Short absence: continue the same focus block, timer was paused
                self.phase = FOCUS
                self.phase_started += away_for
                return FOCUS
            self._rested()
            self.phase = BREAK if self.cycle < self.s.cycles else LONG_BREAK
            return self.start_focus(now)

        # Only focus blocks can be left: being idle during a break is the point
        if (self.phase == FOCUS and idle_seconds is not None
                and idle_seconds >= self.s.idle_minutes * 60):
            self.away_started = now - idle_seconds
            self.phase = AWAY
            return AWAY

        if self.remaining(now) <= 0:
            return self.start_break(now) if self.phase == FOCUS else self.start_focus(now)
        return None

    # ----- light -----

    def fatigue(self, now: float, hour: int) -> float:
        """
        0 = fresh, 1 = tired. Grows in the second half of a focus block, a bit
        more with every block in the set, and starts higher in the evening.
        """
        if self.tired:
            return 1.0
        progress = min(1.0, (now - self.phase_started) / max(1.0, self.phase_length()))
        level = max(0.0, (progress - 0.5) / 0.5) * 0.7
        level += 0.1 * (self.cycle - 1)
        level = max(level, self.auto_fatigue)
        if self.s.evening_hour >= 0 and (hour >= self.s.evening_hour or hour < 5):
            level = max(level, 0.4) + 0.2 * level
        return min(1.0, level)

    def target(self, now: float, hour: int) -> tuple:
        """
        Returns (color, level, breathing): the base color, its brightness (0-1)
        and how deep the breathing pulse is (0 = steady light).
        """
        if self.phase == FOCUS:
            f = self.fatigue(now, hour)
            return blend(self.s.focus_color, self.s.tired_color, f), 1.0 - 0.3 * f, 0.0
        if self.phase == BREAK:
            return self.s.rest_color, 0.45, 0.5
        if self.phase == LONG_BREAK:
            return self.s.rest_color, 0.35, 0.5
        return self.s.rest_color, 0.15, 0.0      # away: low glow


def with_screen(target: tuple, screen_color: tuple, screen_light: float,
                mix: float, follow_brightness: bool) -> tuple:
    """
    Lets the screen shape the focus light (bias lighting):
    - mix: share of the screen's hue blended into the light (0 = none)
    - follow_brightness: a dark screen (dark mode, movies) dims the light
      down to 60%, so the room is never much brighter than the screen
    screen_color is the screen average, screen_light its brightness (0-1).
    """
    color, level, breathing = target
    if mix > 0 and max(screen_color) > 0:
        # Use only the screen's hue: scale it up so it does not darken the light
        peak = max(screen_color)
        hue = tuple(c * 255 / peak for c in screen_color)
        color = blend(color, hue, mix)
    if follow_brightness:
        level *= 0.6 + 0.4 * max(0.0, min(1.0, screen_light))
    return color, level, breathing


class Fader:
    """Moves the light gradually towards its target so changes never jump."""

    def __init__(self, fade_seconds: float):
        self.tau = max(0.01, fade_seconds / 3)   # ~95% of the way after fade_seconds
        self.state = None                        # [r, g, b, level, breathing]

    def step(self, target: tuple, dt: float) -> list:
        color, level, breathing = target
        goal = [*color, level, breathing]
        if self.state is None:
            self.state = goal
        else:
            k = 1 - math.exp(-dt / self.tau)
            self.state = [s + (g - s) * k for s, g in zip(self.state, goal)]
        return self.state


def light_color(state: list, now: float, breath_seconds: float, max_brightness: float) -> tuple:
    """Turns the faded state into the RGB value that is sent to the LEDs."""
    r, g, b, level, breathing = state
    # Breathing: brightness slowly rises and falls (cosine, starts at full)
    breath = 1 - breathing * (0.5 - 0.5 * math.cos(2 * math.pi * now / breath_seconds))
    scale = level * breath * max_brightness
    return tuple(max(0, min(255, int(round(c * scale)))) for c in (r, g, b))


def idle_seconds():
    """
    Seconds since the last keyboard/mouse input, or None if it cannot be read.
    macOS: IOKit HIDIdleTime, Windows: GetLastInputInfo, Linux: xprintidle.
    """
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"],
                                 capture_output=True, text=True, timeout=2).stdout
            match = re.search(r'"HIDIdleTime" = (\d+)', out)
            return int(match.group(1)) / 1e9 if match else None
        if sys.platform == "win32":
            class LastInputInfo(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            info = LastInputInfo(ctypes.sizeof(LastInputInfo), 0)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000
        out = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=2).stdout
        return int(out.strip()) / 1000
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return None
