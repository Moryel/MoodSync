"""Tests for the screen guard logic (no screen, gamma or windows needed)."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import display  # noqa: E402
import guard  # noqa: E402


def run(g, start, seconds, brightness, step=1 / 15):
    """Feeds a constant brightness for a while, returns the dimming at the end."""
    t = start
    while t < start + seconds:
        g.on_sample(t, brightness)
        g.update(t)
        t += step
    return t, g.update(t)


class FlashGuardTests(unittest.TestCase):
    def test_sudden_white_dims_at_once_and_lifts_slowly(self):
        g = guard.FlashGuard()
        t, _ = run(g, 0, 3, 0.1)                 # dark editor
        g.on_sample(t, 0.95)                     # white page appears
        self.assertGreater(g.update(t), 0.35)    # dimmed in the same step
        t, level = run(g, t, 0.4, 0.95)
        self.assertGreater(level, 0.2)           # still dim right after
        t, level = run(g, t, 1.5, 0.95)
        self.assertEqual(level, 0)               # fully back within ~1-2 s

    def test_slow_change_is_left_alone(self):
        g = guard.FlashGuard()
        t = 0
        for i in range(100):                     # dark to bright over ~7 s
            t, level = run(g, t, 0.07, 0.1 + i * 0.008)
            self.assertEqual(level, 0)

    def test_bright_to_brighter_is_not_a_flash(self):
        g = guard.FlashGuard()
        t, _ = run(g, 0, 3, 0.6)
        g.on_sample(t, 0.75)
        self.assertEqual(g.update(t), 0)

    def test_switch_dims_ahead_only_when_dark(self):
        dark = guard.FlashGuard()
        run(dark, 0, 2, 0.1)
        dark.on_event(2)
        self.assertGreater(dark.update(2), 0.2)

        bright = guard.FlashGuard()
        run(bright, 0, 2, 0.8)
        bright.on_event(2)
        self.assertEqual(bright.update(2), 0)

    def test_switch_to_dark_app_lifts_soon(self):
        g = guard.FlashGuard()
        run(g, 0, 2, 0.1)
        g.on_event(2)
        _, level = run(g, 2, 1.5, 0.1)
        self.assertEqual(level, 0)

    def test_flashing_video_gets_one_steady_dim(self):
        g = guard.FlashGuard()
        t, _ = run(g, 0, 2, 0.1)
        levels = []
        for _ in range(8):                       # bright/dark every 0.6 s
            t, a = run(g, t, 0.3, 0.9)
            t, b = run(g, t, 0.3, 0.1)
            levels += [a, b]
        tail = levels[-6:]
        self.assertTrue(all(level > 0.15 for level in tail))     # never back to 0 in between
        self.assertLess(max(tail) - min(tail), 0.2)              # no big pulses

    def test_strength_cap(self):
        g = guard.FlashGuard(max_dim=0.2)
        t, _ = run(g, 0, 2, 0.0)
        g.on_sample(t, 1.0)
        self.assertLessEqual(g.update(t), 0.2)


def page(rows=30, cols=48, white=(0, 30, 10, 38), base=0.15, level=0.95):
    grid = np.full((rows, cols), base)
    r0, r1, c0, c1 = white
    grid[r0:r1, c0:c1] = level
    return grid


class RegionTests(unittest.TestCase):
    def test_white_page_gets_dimmed_after_a_moment(self):
        d = guard.RegionDimmer()
        grid = page()
        rects, alpha = d.update(0, grid)
        self.assertEqual(rects, [])              # not instantly
        rects, alpha = d.update(1.2, grid)
        self.assertEqual(len(rects), 1)
        x, y, w, h = rects[0]
        self.assertAlmostEqual(x, 10 / 48)
        self.assertAlmostEqual(w, 28 / 48)
        self.assertAlmostEqual(alpha, 0.26, delta=0.02)   # 0.95 -> about 0.7

    def test_small_white_spots_are_ignored(self):
        d = guard.RegionDimmer()
        grid = page(white=(5, 7, 5, 8))
        d.update(0, grid)
        self.assertEqual(d.update(2, grid)[0], [])

    def test_hysteresis_keeps_area_while_scrolling(self):
        d = guard.RegionDimmer()
        d.update(0, page())
        d.update(1.2, page())
        # Scrolling: brightness wobbles between the two thresholds
        for i, level in enumerate((0.75, 0.82, 0.74, 0.79)):
            rects, _ = d.update(1.5 + i * 0.5, page(level=level))
            self.assertEqual(len(rects), 1)
        # Really gone dark: switches off only after the delay
        self.assertEqual(len(d.update(4.0, page(level=0.2))[0]), 1)
        self.assertEqual(d.update(5.6, page(level=0.2))[0], [])

    def test_strength_cap(self):
        d = guard.RegionDimmer(strength=0.1)
        d.update(0, page(level=1.0))
        self.assertAlmostEqual(d.update(1.2, page(level=1.0))[1], 0.1)

    def test_luminance_grid(self):
        img = np.zeros((300, 480, 3), np.uint8)
        img[:, 240:] = 255
        grid = guard.luminance_grid(img, columns=48)
        self.assertEqual(grid.shape, (30, 48))
        self.assertAlmostEqual(grid[:, :24].mean(), 0)
        self.assertAlmostEqual(grid[:, 24:].mean(), 1, places=3)

    def test_own_overlay_is_measured_out(self):
        grid = page()
        dimmed = grid.copy()
        dimmed[0:30, 10:38] *= 0.7               # what the capture sees under a 30% overlay
        fixed = guard.undo_overlays(dimmed, [(10 / 48, 0, 28 / 48, 1)], 0.3)
        np.testing.assert_allclose(fixed, grid, atol=1e-6)


class FakeOverlay(display._Overlay):
    def __init__(self):
        super().__init__()
        self.log = []

    def _create(self):
        return len(self.windows)

    def _place(self, win, x, y, w, h):
        self.log.append(("place", win, round(x), round(y), round(w), round(h)))

    def _set_alpha(self, win, a):
        pass

    def _hide(self, win):
        self.log.append(("hide", win))

    def _destroy(self, win):
        pass


class OverlayTests(unittest.TestCase):
    BOUNDS = {"left": 100, "top": 0, "width": 1000, "height": 500}

    def test_places_and_fades(self):
        o = FakeOverlay()
        o.tick = 0
        guard_time = [0.0]
        display.time.monotonic, real = (lambda: guard_time[0]), display.time.monotonic
        try:
            o.show([(0.1, 0.2, 0.5, 0.5)], 0.3, self.BOUNDS)
            self.assertIn(("place", 0, 200, 100, 500, 250), o.log)
            guard_time[0] = 0.1
            o.show([(0.1, 0.2, 0.5, 0.5)], 0.3, self.BOUNDS)
            self.assertTrue(0 < o.current_alpha() < 0.3)          # fading in, not popping
            guard_time[0] = 2
            o.show([(0.1, 0.2, 0.5, 0.5)], 0.3, self.BOUNDS)
            self.assertAlmostEqual(o.current_alpha(), 0.3)
            # Area gone: fades out first, then hides
            guard_time[0] = 2.1
            o.show([], 0.0, self.BOUNDS)
            self.assertEqual(o.rects, [(0.1, 0.2, 0.5, 0.5)])
            guard_time[0] = 4
            o.show([], 0.0, self.BOUNDS)
            self.assertEqual(o.rects, [])
            self.assertIn(("hide", 0), o.log)
        finally:
            display.time.monotonic = real


class WatcherTests(unittest.TestCase):
    def test_reports_changes_only(self):
        w = display.ForegroundWatcher()
        values = iter([1, 1, 2, 2, None, 2, 3])
        w.read = lambda: next(values)
        self.assertEqual([w.changed() for _ in range(7)], [False, False, True, False, False, False, True])


class BackupTests(unittest.TestCase):
    def test_backup_round_trip(self):
        real = display.BACKUP_FILE
        display.BACKUP_FILE = os.path.join(os.path.dirname(__file__), "_gamma_backup_test.json")
        try:
            display._save_backup({"platform": "x", "ramp": [1, 2]})
            self.assertEqual(display._load_backup()["ramp"], [1, 2])
            display._drop_backup()
            self.assertIsNone(display._load_backup())
        finally:
            display._drop_backup()
            display.BACKUP_FILE = real


if __name__ == "__main__":
    unittest.main()
