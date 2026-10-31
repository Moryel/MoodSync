"""Tests for the focus rhythm and its light (time is simulated)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import focus  # noqa: E402

MIN = 60
NOON = 12


def session(**overrides):
    return focus.FocusSession(focus.FocusSettings(**overrides), now=0)


class RhythmTests(unittest.TestCase):
    def test_focus_then_break_then_focus(self):
        s = session()
        self.assertIsNone(s.update(10 * MIN, idle_seconds=0))
        self.assertEqual(s.update(25 * MIN, 0), focus.BREAK)
        self.assertEqual(s.update(30 * MIN, 0), focus.FOCUS)
        self.assertEqual(s.cycle, 2)

    def test_long_break_after_last_cycle(self):
        s = session(cycles=2)
        s.update(25 * MIN, 0)              # break
        s.update(30 * MIN, 0)              # focus 2
        self.assertEqual(s.update(55 * MIN, 0), focus.LONG_BREAK)
        self.assertEqual(s.update(70 * MIN, 0), focus.FOCUS)
        self.assertEqual(s.cycle, 1)

    def test_idle_during_break_is_fine(self):
        s = session()
        s.update(25 * MIN, 0)
        self.assertIsNone(s.update(27 * MIN, idle_seconds=2 * MIN))
        self.assertEqual(s.phase, focus.BREAK)

    def test_short_absence_pauses_focus_timer(self):
        s = session()
        self.assertEqual(s.update(13 * MIN, idle_seconds=3 * MIN), focus.AWAY)
        self.assertIsNone(s.update(14 * MIN, idle_seconds=4 * MIN))
        self.assertEqual(s.update(14 * MIN, idle_seconds=1), focus.FOCUS)
        # Input stopped at 10:00, so 10 minutes were worked and 15 remain
        self.assertAlmostEqual(s.remaining(14 * MIN), 15 * MIN, delta=1)
        self.assertEqual(s.cycle, 1)

    def test_long_absence_counts_as_break(self):
        s = session()
        s.update(13 * MIN, idle_seconds=3 * MIN)
        self.assertEqual(s.update(30 * MIN, idle_seconds=0), focus.FOCUS)
        self.assertEqual(s.cycle, 2)
        self.assertAlmostEqual(s.remaining(30 * MIN), 25 * MIN)

    def test_unknown_idle_never_goes_away(self):
        s = session()
        self.assertIsNone(s.update(20 * MIN, idle_seconds=None))


class LightTests(unittest.TestCase):
    def test_fresh_focus_is_bright_and_cool(self):
        s = session()
        color, level, breathing = s.target(0, NOON)
        self.assertEqual(color, focus.FOCUS_COLOR)
        self.assertEqual((level, breathing), (1.0, 0.0))

    def test_tiredness_grows_in_second_half(self):
        s = session()
        self.assertEqual(s.fatigue(10 * MIN, NOON), 0)
        self.assertGreater(s.fatigue(20 * MIN, NOON), 0.3)
        color, level, _ = s.target(24 * MIN, NOON)
        self.assertLess(level, 1.0)
        self.assertGreater(color[0], focus.FOCUS_COLOR[0])   # warmer
        self.assertLess(color[2], focus.FOCUS_COLOR[2])      # less blue

    def test_later_blocks_and_evening_start_warmer(self):
        s = session()
        s.cycle = 3
        self.assertAlmostEqual(s.fatigue(0, NOON), 0.2)
        self.assertGreaterEqual(session().fatigue(0, 21), 0.4)
        self.assertEqual(session(evening_hour=-1).fatigue(0, 21), 0)

    def test_tired_command(self):
        s = session()
        s.tired = True
        self.assertEqual(s.target(0, NOON)[0], focus.TIRED_COLOR)
        s.update(25 * MIN, 0)
        self.assertFalse(s.tired)   # a break resets it

    def test_break_is_warm_dim_and_breathing(self):
        s = session()
        s.update(25 * MIN, 0)
        color, level, breathing = s.target(26 * MIN, NOON)
        self.assertEqual(color, focus.REST_COLOR)
        self.assertLess(level, 0.5)
        self.assertGreater(breathing, 0)

    def test_breathing_rises_and_falls(self):
        state = [255, 130, 40, 1.0, 0.5]
        top = focus.light_color(state, 0, 10, 1.0)
        bottom = focus.light_color(state, 5, 10, 1.0)
        self.assertEqual(top, (255, 130, 40))
        self.assertEqual(bottom, (128, 65, 20))

    def test_brightness_cap(self):
        self.assertEqual(focus.light_color([200, 100, 0, 1.0, 0], 0, 10, 0.5), (100, 50, 0))

    def test_fader_moves_gradually(self):
        f = focus.Fader(fade_seconds=30)
        f.step(((0, 0, 0), 1.0, 0.0), 0)
        halfway = f.step(((255, 255, 255), 1.0, 0.0), 5)[0]
        self.assertTrue(0 < halfway < 255)
        for _ in range(100):
            final = f.step(((255, 255, 255), 1.0, 0.0), 1)[0]
        self.assertAlmostEqual(final, 255, delta=1)


class ScreenTests(unittest.TestCase):
    TARGET = ((170, 210, 255), 1.0, 0.0)

    def test_screen_hue_is_mixed_in(self):
        color, level, _ = focus.with_screen(self.TARGET, (100, 0, 0), 1.0, 0.5, True)
        self.assertGreater(color[0], 170)          # more red
        self.assertLess(color[2], 255)
        self.assertEqual(level, 1.0)               # bright screen, full light

    def test_dark_screen_dims_the_light(self):
        _, level, _ = focus.with_screen(self.TARGET, (10, 10, 10), 0.0, 0.3, True)
        self.assertAlmostEqual(level, 0.6)
        _, level, _ = focus.with_screen(self.TARGET, (10, 10, 10), 0.0, 0.3, False)
        self.assertEqual(level, 1.0)

    def test_dark_hue_does_not_darken_color(self):
        color, _, _ = focus.with_screen(self.TARGET, (0, 0, 40), 0.5, 1.0, False)
        self.assertEqual(color, (0, 0, 255))

    def test_no_mix(self):
        self.assertEqual(focus.with_screen(self.TARGET, (255, 0, 0), 1.0, 0, False), self.TARGET)

    def test_black_screen_keeps_color(self):
        color, _, _ = focus.with_screen(self.TARGET, (0, 0, 0), 0.0, 0.5, False)
        self.assertEqual(color, self.TARGET[0])


class IdleTests(unittest.TestCase):
    def test_idle_seconds_is_number_or_none(self):
        value = focus.idle_seconds()
        self.assertTrue(value is None or value >= 0)


if __name__ == "__main__":
    unittest.main()
