"""
MoodSync power awareness: on the charger everything runs at full speed; on
battery MoodSync looks less often; with the system's low power / battery saver
mode on, the costly extras (camera, white-area dimming) pause.

What costs battery is mostly waking the processor up, not the work itself:
a processor that is woken 30 times a second never reaches its deep sleep
states. So the profiles mostly change how often things wake up.
"""

import ctypes
import os
import re
import subprocess
import sys
from dataclasses import dataclass

CHECK_SECONDS = 30          # How often the power source is looked up


@dataclass(frozen=True)
class Profile:
    name: str
    focus_fps: float        # LED updates per second while the light is changing
    screen_fps: float       # Screen program captures per second
    guard_sample: float     # Seconds between screen samples for the screen guard
    guard_fast: float       # Seconds of fast sampling after an app switch or flash
    camera: str             # "continuous", "bursts" or "off"
    dim_white: bool         # White-area dimming allowed


FULL = Profile("charger", focus_fps=10, screen_fps=20, guard_sample=0.5, guard_fast=2.0,
               camera="continuous", dim_white=True)
BATTERY = Profile("battery", focus_fps=5, screen_fps=10, guard_sample=1.0, guard_fast=1.0,
                  camera="bursts", dim_white=True)
SAVER = Profile("low power mode", focus_fps=4, screen_fps=5, guard_sample=2.0, guard_fast=1.0,
                camera="off", dim_white=False)
PROFILES = {"full": FULL, "battery": BATTERY, "saver": SAVER}


def _run(cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _mac():
    on_battery = "'Battery Power'" in _run(["pmset", "-g", "batt"])
    try:
        from Foundation import NSProcessInfo
        saver = bool(NSProcessInfo.processInfo().isLowPowerModeEnabled())
    except Exception:
        saver = bool(re.search(r"lowpowermode\s+1", _run(["pmset", "-g"])))
    return on_battery, saver


def _windows():
    class SystemPowerStatus(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
    status = SystemPowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return False, False
    on_battery = status.ACLineStatus == 0 and status.BatteryFlag != 128   # 128 = no battery
    return on_battery, bool(status.SystemStatusFlag & 1)                  # battery saver


def _linux():
    base = "/sys/class/power_supply"
    on_battery = False
    try:
        supplies = os.listdir(base)
    except OSError:
        supplies = []
    has_battery = any(open(os.path.join(base, s, "type")).read().strip() == "Battery"
                      for s in supplies if os.path.exists(os.path.join(base, s, "type")))
    for s in supplies:
        try:
            if open(os.path.join(base, s, "type")).read().strip() == "Mains":
                on_battery = has_battery and open(os.path.join(base, s, "online")).read().strip() == "0"
        except OSError:
            pass
    saver = _run(["powerprofilesctl", "get"]).strip() == "power-saver"
    return on_battery, saver


def power_state():
    """Returns (on_battery, low_power_mode). Unknown counts as on the charger."""
    try:
        if sys.platform == "darwin":
            return _mac()
        if sys.platform == "win32":
            return _windows()
        return _linux()
    except Exception:
        return False, False


def pick(on_battery: bool, saver: bool) -> Profile:
    if saver:
        return SAVER
    return BATTERY if on_battery else FULL


class PowerWatch:
    """Looks up the power state every CHECK_SECONDS; mode = auto or a fixed profile name."""

    def __init__(self, mode: str, now: float, state=power_state):
        self.mode = mode
        self.state = state
        self.checked = now
        self.profile = PROFILES[mode] if mode != "auto" else pick(*state())

    def update(self, now: float):
        """Returns the new profile when it changed, else None."""
        if self.mode != "auto" or now - self.checked < CHECK_SECONDS:
            return None
        self.checked = now
        profile = pick(*self.state())
        if profile == self.profile:
            return None
        self.profile = profile
        return profile
