"""
MoodSync screen guard: protects the eyes from sudden brightness on screen.

Two optional layers (the platform side lives in display.py):

--flash-guard  Dims the whole screen through the display's gamma table, which
               is fast and does not show up in screen captures.
               - Predict: switching apps, opening a window or changing Spaces
                 is what usually throws a bright page at you. When that
                 happens while the screen is dark, the screen dims at once,
                 before the new content is measured.
               - React: the screen is sampled at low resolution (2 per second,
                 15 per second around events) and a big jump in brightness
                 dims it immediately.
               Dimming is instant, coming back is slow (like the eye adapting).
               Content that keeps flashing (video, animations) gets one steady
               dim instead of pulsing, so the guard never adds flicker itself.

--dim-white    Lays click-through, see-through dark windows over large white
               areas (white web pages, empty documents) so only those get
               softer. Text stays readable: everything under the window is
               darkened by the same factor, so contrast is kept. Areas switch
               on and off with separate thresholds and delays, so scrolling
               or animations do not make them blink.

The timing values are starting points to tune by feel, not research figures.
"""

import math
import threading
import time
from collections import deque

import numpy as np

GRID_COLUMNS = 48           # Screen is judged on a grid of about 48 x 30 cells
SLOW_SAMPLE = 0.5           # Seconds between screen samples normally
FAST_SAMPLE = 1 / 15        # ...and around app switches / flashes
FAST_SECONDS = 2.0          # How long sampling stays fast after an event
EVENT_POLL = 0.05           # Seconds between foreground window checks
GAMMA_STEP = 0.01           # Gamma is only rewritten for changes larger than this


def luminance_grid(img: np.ndarray, columns: int = GRID_COLUMNS) -> np.ndarray:
    """
    Average brightness (0-1) of each cell of an RGB image, on a grid about
    `columns` cells wide with roughly square cells.
    """
    h, w = img.shape[:2]
    cell = max(1, w // columns)
    rows, cols = max(1, h // cell), max(1, w // cell)
    img = img[:rows * cell, :cols * cell].astype(np.float32) / 255
    luma = img[..., 0] * 0.2126 + img[..., 1] * 0.7152 + img[..., 2] * 0.0722
    return luma.reshape(rows, cell, cols, cell).mean(axis=(1, 3))


def undo_overlays(grid: np.ndarray, rects: list, alpha: float) -> np.ndarray:
    """
    Our own dark windows show up in screen captures. Since we know where they
    are and how dark, divide them back out so we measure the real content.
    rects are (x, y, w, h) fractions of the screen.
    """
    if not rects or alpha <= 0:
        return grid
    grid = grid.copy()
    rows, cols = grid.shape
    for x, y, w, h in rects:
        c0, c1 = int(round(x * cols)), int(round((x + w) * cols))
        r0, r1 = int(round(y * rows)), int(round((y + h) * rows))
        grid[r0:r1, c0:c1] = np.minimum(1.0, grid[r0:r1, c0:c1] / (1 - alpha))
    return grid


class FlashGuard:
    """
    Decides how much to dim the whole screen (0 = not at all). Fed with the
    screen brightness and with app/window switch events; pure logic.
    """

    def __init__(self, max_dim=0.4, rise=0.25, bright=0.55, dark=0.35, predict_dim=0.3,
                 hold=0.25, release=0.8, adapt=1.0, cooldown=0.5, steady_after=3, steady_window=5.0,
                 rise_within=0.6):
        self.max_dim = max_dim          # Strongest dimming (0-1)
        self.rise = rise                # Brightness jump that counts as a flash...
        self.rise_within = rise_within  # ...when it happens within this many seconds
        self.bright = bright            # ...and only if the result is at least this bright
        self.dark = dark                # Predictive dimming only when the screen is darker than this
        self.predict_dim = predict_dim  # Dimming applied on an app/window switch
        self.hold = hold                # Seconds the dimming holds before it starts to lift
        self.release = release          # Seconds to lift full dimming (slow, like the eye)
        self.adapt = adapt              # Seconds the "eye" needs to get used to a new brightness
        self.cooldown = cooldown        # Minimum time between two flash reactions
        self.steady_after = steady_after    # This many flashes...
        self.steady_window = steady_window  # ...within this many seconds = flashing content

        self.level = 0.0                # Current dimming
        self.adapted = None             # Brightness the eye is used to
        self.hold_until = 0.0
        self.cooldown_until = 0.0
        self.last = None
        self.flashes = deque()
        self.recent = deque()           # (time, brightness) of the last rise_within seconds
        self.steady_until = 0.0         # Flashing content: hold a steady dim until then
        self.events = 0                 # Counters, for the status line
        self.reactions = 0
        self.tick = None                # Time of the previous update()

    def _dim(self, now: float, amount: float, hold: float):
        self.level = max(self.level, min(self.max_dim, amount))
        self.hold_until = max(self.hold_until, now + hold)

    def on_event(self, now: float):
        """An app/window/Space switch: dim ahead of time if the screen is dark."""
        self.events += 1
        if self.adapted is not None and self.adapted < self.dark:
            self._dim(now, self.predict_dim, self.hold + 0.3)

    def on_sample(self, now: float, brightness: float):
        """A new measurement of the whole screen's brightness (0-1)."""
        if self.adapted is None or self.last is None:
            self.adapted, self.last = brightness, now
            return
        dt = max(0.0, now - self.last)
        self.last = now

        # A flash is a fast rise: compare with the darkest moment just before
        self.recent.append((now, brightness))
        while self.recent and self.recent[0][0] < now - self.rise_within:
            self.recent.popleft()
        jump = brightness - min(b for _, b in self.recent)
        if jump >= self.rise and brightness >= self.bright and now >= self.cooldown_until:
            self.recent.clear()         # This rise is handled; staying bright is not a new flash
            self.recent.append((now, brightness))
            self.reactions += 1
            self.cooldown_until = now + self.cooldown
            self.flashes.append(now)
            while self.flashes and self.flashes[0] < now - self.steady_window:
                self.flashes.popleft()
            if len(self.flashes) >= self.steady_after:
                # Keeps flashing: one calm, steady dim instead of pulses
                self.steady_until = now + self.steady_window
            self._dim(now, jump * 1.2, self.hold)

        # The eye gets used to the new brightness
        self.adapted += (brightness - self.adapted) * (1 - math.exp(-dt / self.adapt))

    def update(self, now: float) -> float:
        """Current dimming (0-1), lifting slowly once the hold is over."""
        previous, self.tick = self.tick, now
        if now < self.steady_until:
            self.level = max(self.level, self.max_dim * 0.6)
        elif previous is not None and now > self.hold_until and self.level > 0:
            # Only the time after the hold counts towards lifting
            lifting = now - max(previous, self.hold_until)
            self.level = max(0.0, self.level - lifting * self.max_dim / self.release)
        return self.level


class RegionDimmer:
    """
    Finds large, bright areas on a luminance grid and decides how dark the
    overlay over them should be. Per-cell hysteresis (separate on/off
    thresholds and delays) keeps the areas from blinking.
    """

    def __init__(self, strength=0.3, on=0.8, off=0.7, on_after=1.0, off_after=1.5,
                 min_area=0.04, min_fill=0.6, target=0.7):
        self.strength = strength    # Darkest overlay (0-1)
        self.on, self.off = on, off             # Brightness to switch a cell on / off
        self.on_after, self.off_after = on_after, off_after   # ...after this many seconds
        self.min_area = min_area    # Areas smaller than this share of the screen are ignored
        self.min_fill = min_fill    # Share of an area's box that must be bright
        self.target = target        # Brightness the overlay aims for
        self.state = None           # Cell is dimmed
        self.since = None           # When each cell first crossed its threshold
        self.rects = []
        self.alpha = 0.0

    def update(self, now: float, grid: np.ndarray):
        """Returns (rects as (x, y, w, h) screen fractions, overlay darkness)."""
        if self.state is None or self.state.shape != grid.shape:
            self.state = np.zeros(grid.shape, bool)
            self.since = np.full(grid.shape, np.nan)

        want = np.where(self.state, grid > self.off, grid >= self.on)
        changing = want != self.state
        self.since = np.where(changing & np.isnan(self.since), now, self.since)
        self.since = np.where(changing, self.since, np.nan)
        delay = np.where(self.state, self.off_after, self.on_after)
        flip = changing & (now - np.nan_to_num(self.since, nan=now) >= delay)
        self.state = np.where(flip, want, self.state)
        self.since = np.where(flip, np.nan, self.since)

        rects, levels = [], []
        rows, cols = grid.shape
        for r0, c0, r1, c1, cells in _components(self.state):
            box = (r1 - r0) * (c1 - c0)
            if box < self.min_area * rows * cols or cells < self.min_fill * box:
                continue
            rects.append((c0 / cols, r0 / rows, (c1 - c0) / cols, (r1 - r0) / rows))
            levels.append(float(grid[r0:r1, c0:c1].mean()))
        self.rects = rects
        mean = max(levels) if levels else 0.0
        self.alpha = min(self.strength, max(0.0, 1 - self.target / mean)) if mean > 0 else 0.0
        return self.rects, self.alpha


def _components(mask: np.ndarray):
    """Connected areas of True cells: yields (row0, col0, row1, col1, cell count)."""
    rows, cols = mask.shape
    seen = np.zeros_like(mask, bool)
    for r in range(rows):
        for c in range(cols):
            if not mask[r, c] or seen[r, c]:
                continue
            stack, count = [(r, c)], 0
            seen[r, c] = True
            r0, r1, c0, c1 = r, r + 1, c, c + 1
            while stack:
                y, x = stack.pop()
                count += 1
                r0, r1, c0, c1 = min(r0, y), max(r1, y + 1), min(c0, x), max(c1, x + 1)
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < rows and 0 <= nx < cols and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            yield r0, c0, r1, c1, count


class ScreenGuard:
    """
    Runs the guard: a background thread watches the screen and app switches
    and drives the gamma dimming; the overlays are updated from the main
    thread through pump(), because windows must live on the main thread.
    """

    def __init__(self, monitor: int, flash_guard: bool, dim_white: bool,
                 flash_strength: float, dim_strength: float, capture, note=print):
        import display  # Platform code, only loaded when the guard is used

        self.display = display
        self.capture = capture      # Makes a screen capture (mss), used from the thread
        self.monitor = monitor
        self.note = note
        self.flash = FlashGuard(max_dim=flash_strength) if flash_guard else None
        self.regions = RegionDimmer(strength=dim_strength) if dim_white else None
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = None
        self.gamma = None
        self.overlay = None
        self.shown = ([], 0.0)      # What the overlay currently shows (for undo_overlays)
        self.wanted = ([], 0.0)     # What the thread wants the overlay to show
        self.bounds = None          # Monitor position, for placing overlays
        self.dim = 0.0

    def start(self):
        """Starts what this platform supports and reports what it could not."""
        if self.flash is not None:
            self.gamma, problem = self.display.open_gamma()
            if problem:
                self.note(f"Note: flash guard is off - {problem}.")
                self.flash = None
        if self.regions is not None:
            self.overlay, problem = self.display.open_overlay()
            if problem:
                self.note(f"Note: dimming white areas is off - {problem}.")
                self.regions = None
        if self.flash is None and self.regions is None:
            return False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def _run(self):
        watcher = self.display.ForegroundWatcher() if self.flash is not None else None
        sct = None
        next_sample = next_poll = 0.0
        fast_until = 0.0
        applied = 0.0
        try:
            while not self.stopped.is_set():
                now = time.monotonic()

                if watcher is not None and now >= next_poll:
                    next_poll = now + EVENT_POLL
                    if watcher.changed():
                        self.flash.on_event(now)
                        fast_until = now + FAST_SECONDS

                if now >= next_sample:
                    next_sample = now + (FAST_SAMPLE if now < fast_until else SLOW_SAMPLE)
                    try:
                        if sct is None:
                            sct = self.capture()
                        mon = sct.monitors[self.monitor]
                        img = np.asarray(sct.grab(mon))[:, :, 2::-1]
                    except Exception:
                        # Display asleep or unplugged: look again a little later with a fresh capture
                        if sct is not None:
                            sct.close()
                        sct = None
                        next_sample = now + 5
                        continue
                    with self.lock:
                        self.bounds = mon
                        rects, alpha = self.shown
                    grid = undo_overlays(luminance_grid(img), rects, alpha)
                    if self.flash is not None:
                        before = self.flash.reactions
                        self.flash.on_sample(now, float(grid.mean()))
                        if self.flash.reactions != before:
                            fast_until = now + FAST_SECONDS
                    if self.regions is not None:
                        wanted = self.regions.update(now, grid)
                        with self.lock:
                            self.wanted = wanted

                if self.flash is not None:
                    self.dim = self.flash.update(now)
                    if abs(self.dim - applied) >= GAMMA_STEP or (self.dim == 0 and applied > 0):
                        self.gamma.set(1 - self.dim)
                        applied = self.dim

                self.stopped.wait(1 / 30)
        finally:
            if sct is not None:
                sct.close()
            if self.gamma is not None:
                self.gamma.restore()

    def pump(self):
        """Main thread: moves the overlays to where the thread wants them."""
        if self.overlay is None:
            return
        with self.lock:
            rects, alpha = self.wanted
            bounds = self.bounds
        if bounds is not None:
            self.overlay.show(rects, alpha, bounds)
            with self.lock:
                self.shown = (list(self.overlay.rects), self.overlay.current_alpha())
        self.overlay.pump()

    def stop(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.overlay is not None:
            self.overlay.close()
        if self.gamma is not None:
            self.gamma.restore()
