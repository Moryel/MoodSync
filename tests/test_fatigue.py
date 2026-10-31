"""Tests for tiredness detection from typing rhythm (typing is simulated)."""

import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fatigue  # noqa: E402
import focus  # noqa: E402

MIN = 60


def type_for(log, start, seconds, interval, corrections, pause_every, seed=1):
    """Simulates typing: keys every ~interval s, some corrections, a 5 s pause every N keys."""
    rng = random.Random(seed)
    t, n = start, 0
    while t < start + seconds:
        log.add(t, rng.random() < corrections)
        n += 1
        t += interval * rng.uniform(0.7, 1.3)
        if n % pause_every == 0:
            t += 5
    return t


def fresh(log, start, seconds, seed=1):
    return type_for(log, start, seconds, 0.18, 0.03, 80, seed)


def tired(log, start, seconds, seed=2):
    return type_for(log, start, seconds, 0.30, 0.12, 25, seed)


class StatsTests(unittest.TestCase):
    def test_too_little_typing(self):
        log = fatigue.KeyLog()
        for i in range(10):
            log.add(i, False)
        self.assertIsNone(fatigue.typing_stats(log.snapshot(), 0, 100))

    def test_stats_follow_the_typing(self):
        log = fatigue.KeyLog()
        fresh(log, 0, 180)
        stats = fatigue.typing_stats(log.snapshot(), 0, 180)
        self.assertAlmostEqual(stats.interval, 0.18, delta=0.03)
        self.assertAlmostEqual(stats.corrections, 0.03, delta=0.03)

    def test_tired_typing_scores_high(self):
        a, b = fatigue.KeyLog(), fatigue.KeyLog()
        fresh(a, 0, 180)
        tired(b, 0, 180)
        normal = fatigue.typing_stats(a.snapshot(), 0, 180)
        self.assertLess(fatigue.tiredness(fatigue.typing_stats(a.snapshot(), 0, 180), normal), 0.1)
        self.assertGreater(fatigue.tiredness(fatigue.typing_stats(b.snapshot(), 0, 180), normal), 0.8)

    def test_log_forgets_old_keys(self):
        log = fatigue.KeyLog()
        log.add(0, False)
        log.add(fatigue.FRESH_SECONDS + fatigue.WINDOW_SECONDS + 10, False)
        self.assertEqual(len(log.snapshot()), 1)
        self.assertEqual(log.total, 2)


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.file = os.path.join(self.dir.name, "baseline.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_learns_then_detects_tiredness(self):
        log = fatigue.KeyLog()
        d = fatigue.FatigueDetector(log, self.file)
        d.new_block(0)
        self.assertTrue(d.learning)
        end = fresh(log, 0, 8 * MIN)
        d.update(end)
        self.assertFalse(d.learning)
        self.assertTrue(os.path.exists(self.file))
        self.assertLess(d.update(end), 0.1)

        # Same person, getting tired: the score climbs over a few checks
        t = end
        for i in range(10):
            t = tired(log, t, 30, seed=10 + i)
            score = d.update(t)
        self.assertGreater(score, 0.7)

    def test_baseline_survives_restart(self):
        log = fatigue.KeyLog()
        d = fatigue.FatigueDetector(log, self.file)
        d.new_block(0)
        d.update(fresh(log, 0, 8 * MIN))
        again = fatigue.FatigueDetector(fatigue.KeyLog(), self.file)
        self.assertFalse(again.learning)
        self.assertAlmostEqual(again.normal.interval, d.normal.interval)

    def test_no_typing_keeps_last_score(self):
        d = fatigue.FatigueDetector(fatigue.KeyLog(), None)
        d.new_block(0)
        d.score = 0.5
        self.assertEqual(d.update(10 * MIN), 0.5)

    def test_new_block_starts_at_zero(self):
        d = fatigue.FatigueDetector(fatigue.KeyLog(), None)
        d.score = 0.9
        d.new_block(100)
        self.assertEqual(d.score, 0)

    def test_tired_block_does_not_become_normal(self):
        log = fatigue.KeyLog()
        d = fatigue.FatigueDetector(log, None)
        d.new_block(0)
        d.update(fresh(log, 0, 8 * MIN))
        normal = d.normal.interval
        # Next block starts already tired
        d.new_block(30 * MIN)
        d.score = 0.8
        t = 30 * MIN
        for i in range(25):
            t = tired(log, t, 30, seed=30 + i)
            d.update(t)
        self.assertAlmostEqual(d.normal.interval, normal)


class AutoBreakTests(unittest.TestCase):
    def session(self, **kw):
        return focus.FocusSession(focus.FocusSettings(**kw), now=0)

    def test_sustained_tiredness_starts_break(self):
        s = self.session()
        self.assertIsNone(s.set_auto_fatigue(0.8, 11 * MIN))
        self.assertIsNone(s.set_auto_fatigue(0.8, 13 * MIN))
        self.assertEqual(s.set_auto_fatigue(0.8, 14 * MIN), focus.BREAK)
        self.assertEqual(s.auto_fatigue, 0)     # break resets it

    def test_short_spike_does_not(self):
        s = self.session()
        s.set_auto_fatigue(0.8, 11 * MIN)
        s.set_auto_fatigue(0.4, 12 * MIN)
        self.assertIsNone(s.set_auto_fatigue(0.8, 14 * MIN))
        self.assertEqual(s.phase, focus.FOCUS)

    def test_not_too_early_in_a_block(self):
        s = self.session()
        s.set_auto_fatigue(0.9, 1 * MIN)
        self.assertIsNone(s.set_auto_fatigue(0.9, 5 * MIN))

    def test_can_be_switched_off(self):
        s = self.session(auto_break=False)
        s.set_auto_fatigue(0.9, 11 * MIN)
        self.assertIsNone(s.set_auto_fatigue(0.9, 20 * MIN))
        # ...but the light still softens
        self.assertGreaterEqual(s.fatigue(20 * MIN, 12), 0.9)

    def test_detected_tiredness_softens_light(self):
        s = self.session()
        s.set_auto_fatigue(0.6, 5 * MIN)
        color, level, _ = s.target(5 * MIN, 12)
        self.assertLess(level, 0.9)
        self.assertLess(color[2], focus.FOCUS_COLOR[2])

    def test_new_block_counter(self):
        s = self.session()
        s.update(25 * MIN, 0)
        s.update(30 * MIN, 0)
        self.assertEqual(s.block, 2)


if __name__ == "__main__":
    unittest.main()
