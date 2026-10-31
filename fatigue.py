"""
MoodSync automatic tiredness detection from typing rhythm.

Tired people type slower, correct more and pause more often. MoodSync first
learns your normal rhythm (at the start of focus blocks, when you are fresh)
and then compares the last few minutes against it:

  slower:   median time between keystrokes compared to your normal
  errors:   share of Backspace/Delete presses compared to your normal
  pauses:   2-30 second gaps per 100 keys compared to your normal

Only key timings and whether a key was Backspace/Delete are recorded, never
which keys were typed. The learned rhythm (four numbers) is saved to
~/.moodsync.json so it carries over between runs.
"""

import json
import os
import statistics
import threading
from collections import deque
from dataclasses import asdict, dataclass

WINDOW_SECONDS = 180        # Typing compared over the last 3 minutes
MIN_KEYS = 60               # Fewer keys than this in the window = not enough typing to judge
BASELINE_MIN_KEYS = 600     # Keys needed to learn the normal rhythm
FRESH_SECONDS = 600         # First 10 minutes of a focus block count as fresh
BASELINE_LEARN_RATE = 0.2   # How much each fresh block updates the normal rhythm
SCORE_SMOOTHING = 0.3       # How quickly the tiredness score follows new windows
TYPING_GAP = 2.0            # Gaps shorter than this are typing
PAUSE_GAP = 30.0            # Gaps between TYPING_GAP and this are hesitation pauses
BASELINE_FILE = os.path.join(os.path.expanduser("~"), ".moodsync.json")


@dataclass
class TypingStats:
    keys: int
    interval: float         # Median seconds between keystrokes while typing
    corrections: float      # Backspace/Delete share of all keys (0-1)
    pauses: float           # Hesitation pauses per 100 keys


def typing_stats(events, start: float, end: float):
    """
    Summarises (time, is_correction) key events between start and end.
    Returns None if there was not enough typing to say anything.
    """
    events = [e for e in events if start <= e[0] <= end]
    if len(events) < MIN_KEYS:
        return None
    times = [t for t, _ in events]
    gaps = [b - a for a, b in zip(times, times[1:])]
    typing = [g for g in gaps if g < TYPING_GAP]
    if len(typing) < MIN_KEYS // 2:
        return None
    pauses = sum(1 for g in gaps if TYPING_GAP <= g < PAUSE_GAP)
    return TypingStats(
        keys=len(events),
        interval=statistics.median(typing),
        corrections=sum(1 for _, fix in events if fix) / len(events),
        pauses=pauses * 100 / len(events),
    )


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def tiredness(current: TypingStats, normal: TypingStats) -> float:
    """
    0 = typing like your normal self, 1 = clearly tired.
    50% slower typing, 8 points more corrections or twice the pauses each
    count as fully tired for that signal.
    """
    slower = clamp((current.interval / max(normal.interval, 0.01) - 1) / 0.5)
    errors = clamp((current.corrections - normal.corrections) / 0.08)
    pauses = clamp((current.pauses - normal.pauses) / max(normal.pauses, 3))
    return 0.45 * slower + 0.35 * errors + 0.2 * pauses


class KeyLog:
    """Thread-safe list of recent key events: (monotonic time, is_correction)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = deque()
        self.total = 0

    def add(self, when: float, correction: bool):
        with self.lock:
            self.events.append((when, correction))
            self.total += 1
            # Keep a bit more than the comparison window plus a fresh period
            while self.events and self.events[0][0] < when - (FRESH_SECONDS + WINDOW_SECONDS):
                self.events.popleft()

    def snapshot(self) -> list:
        with self.lock:
            return list(self.events)


def start_key_listener(log: KeyLog, clock):
    """
    Starts listening to the keyboard in the background (pynput).
    Returns (listener, problem): problem is a message when it cannot work.
    """
    try:
        from pynput import keyboard
    except ImportError:
        return None, "pynput is not installed (pip install -r requirements.txt)"

    corrections = {keyboard.Key.backspace, keyboard.Key.delete}
    modifiers = {getattr(keyboard.Key, n) for n in
                 ("shift", "shift_r", "ctrl", "ctrl_r", "alt", "alt_r", "alt_gr",
                  "cmd", "cmd_r", "caps_lock") if hasattr(keyboard.Key, n)}

    def on_press(key):
        # Modifiers are pressed together with other keys, they would skew the rhythm
        if key not in modifiers:
            log.add(clock(), key in corrections)

    try:
        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()
    except Exception as e:  # No display, missing backend, ...
        return None, f"keyboard cannot be read ({e})"

    if getattr(listener, "IS_TRUSTED", True) is False:
        return listener, ("macOS does not allow reading the keyboard yet: add your terminal under "
                          "System Settings -> Privacy & Security -> Input Monitoring, then restart MoodSync")
    return listener, None


class FatigueDetector:
    """Learns your normal typing rhythm and turns recent typing into a tiredness score."""

    def __init__(self, log: KeyLog, baseline_file: str | None = BASELINE_FILE):
        self.log = log
        self.baseline_file = baseline_file
        self.normal = self._load()
        self.score = 0.0
        self.block_start = None
        self.learned_this_block = False
        self.last = None     # Latest TypingStats, for the status line

    def _load(self):
        if not self.baseline_file:
            return None
        try:
            with open(self.baseline_file) as f:
                return TypingStats(**json.load(f)["typing"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save(self):
        if not self.baseline_file:
            return
        try:
            with open(self.baseline_file, "w") as f:
                json.dump({"typing": asdict(self.normal)}, f, indent=2)
        except OSError:
            pass

    @property
    def learning(self) -> bool:
        return self.normal is None

    def new_block(self, now: float):
        """A focus block started: you are rested, start over from 0."""
        self.block_start = now
        self.learned_this_block = False
        self.score = 0.0

    def _learn(self, now: float):
        """Uses the fresh start of a focus block to learn or refresh the normal rhythm."""
        if self.learned_this_block or self.block_start is None:
            return
        fresh_end = self.block_start + FRESH_SECONDS
        events = self.log.snapshot()
        stats = typing_stats(events, self.block_start, min(now, fresh_end))
        if self.normal is None:
            if stats and stats.keys >= BASELINE_MIN_KEYS:
                self.normal = stats
                self.learned_this_block = True
                self._save()
            return
        if now < fresh_end:
            return
        self.learned_this_block = True
        # Only refresh from a block that started fresh, so tired days do not become "normal"
        if stats and self.score < 0.2:
            k = BASELINE_LEARN_RATE
            self.normal = TypingStats(**{
                name: getattr(self.normal, name) * (1 - k) + getattr(stats, name) * k
                for name in ("keys", "interval", "corrections", "pauses")})
            self.normal.keys = int(self.normal.keys)
            self._save()

    def update(self, now: float) -> float:
        """Recomputes the tiredness score (0-1) from the last few minutes of typing."""
        self._learn(now)
        start = now - WINDOW_SECONDS
        if self.block_start is not None:
            start = max(start, self.block_start)    # Do not mix in the previous block
        stats = typing_stats(self.log.snapshot(), start, now)
        if stats is None:
            return self.score       # Reading or thinking: keep the last judgement
        self.last = stats
        if self.normal is None:
            return self.score
        raw = tiredness(stats, self.normal)
        self.score += (raw - self.score) * SCORE_SMOOTHING
        return self.score
