"""Tests for power profiles and the battery-friendly pacing."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import focus  # noqa: E402
import power  # noqa: E402


class ProfileTests(unittest.TestCase):
    def test_pick(self):
        self.assertIs(power.pick(False, False), power.FULL)
        self.assertIs(power.pick(True, False), power.BATTERY)
        self.assertIs(power.pick(True, True), power.SAVER)
        self.assertIs(power.pick(False, True), power.SAVER)     # low power mode on the charger too

    def test_battery_looks_less_often(self):
        self.assertLess(power.BATTERY.focus_fps, power.FULL.focus_fps)
        self.assertGreater(power.BATTERY.guard_sample, power.FULL.guard_sample)
        self.assertEqual(power.BATTERY.camera, "bursts")
        self.assertEqual(power.SAVER.camera, "off")
        self.assertFalse(power.SAVER.dim_white)

    def test_watch_follows_changes(self):
        state = [(False, False)]
        w = power.PowerWatch("auto", 0, state=lambda: state[0])
        self.assertIs(w.profile, power.FULL)
        state[0] = (True, False)
        self.assertIsNone(w.update(10))                          # not checked again yet
        self.assertIs(w.update(power.CHECK_SECONDS + 1), power.BATTERY)
        self.assertIsNone(w.update(2 * power.CHECK_SECONDS + 2))  # unchanged

    def test_fixed_mode_ignores_power_source(self):
        w = power.PowerWatch("saver", 0, state=lambda: (False, False))
        self.assertIs(w.profile, power.SAVER)
        self.assertIsNone(w.update(1000))

    def test_real_power_state_is_readable(self):
        on_battery, saver = power.power_state()
        self.assertIsInstance(on_battery, bool)
        self.assertIsInstance(saver, bool)


class FaderTests(unittest.TestCase):
    def test_settles(self):
        f = focus.Fader(fade_seconds=3)
        target = ((200, 100, 50), 1.0, 0.0)
        f.step(((0, 0, 0), 0.5, 0.0), 0)
        self.assertTrue(f.settled())               # starts at its first target
        f.step(target, 0.1)
        self.assertFalse(f.settled())              # fading: update often
        for _ in range(100):
            f.step(target, 0.1)
        self.assertTrue(f.settled())               # arrived: once a second is enough


if __name__ == "__main__":
    unittest.main()
