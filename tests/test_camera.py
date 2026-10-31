"""Tests for camera tiredness signals (frames are simulated, no camera needed)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import camera  # noqa: E402

FPS = 10


def feed(tracker, start, seconds, closed_every=None, closed_for=0.1, jaw=0.0, face=True):
    """Simulates frames: eyes closed for closed_for s every closed_every s."""
    frames = int(seconds * FPS)
    for i in range(frames):
        t = start + i / FPS
        closed = closed_every is not None and (t - start) % closed_every < closed_for
        eyes = (0.9 if closed else 0.05) if face else None
        tracker.add(t, eyes, jaw)
    return start + frames / FPS


class EyeTrackerTests(unittest.TestCase):
    def test_alert_person(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 60, closed_every=4, closed_for=0.15)   # ~15 short blinks a minute
        self.assertLess(t.score(end), 0.1)

    def test_drowsy_person(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 60, closed_every=4, closed_for=0.9)    # slow, long blinks
        closure, long_blinks, _ = t.readings(end)
        self.assertGreater(closure, 0.15)
        self.assertGreater(long_blinks, 10)
        self.assertGreater(t.score(end), 0.7)

    def test_yawns_count(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 20)
        end = feed(t, end, 3, jaw=0.9)       # a yawn
        end = feed(t, end, 20)
        end = feed(t, end, 2, jaw=0.9)       # another
        end = feed(t, end, 20)
        self.assertEqual(t.readings(end)[2], 2)

    def test_talking_is_not_yawning(self):
        t = camera.EyeTracker()
        end = 0
        for _ in range(20):
            end = feed(t, end, 0.5, jaw=0.9)
            end = feed(t, end, 0.5)
        end = feed(t, end, 20)
        self.assertEqual(t.readings(end)[2], 0)

    def test_no_face_means_no_judgement(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 60, face=False)
        self.assertIsNone(t.score(end))

    def test_too_few_frames(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 2)
        self.assertIsNone(t.score(end))

    def test_old_frames_are_forgotten(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 60, closed_every=4, closed_for=0.9)
        end = feed(t, end, 61, closed_every=4, closed_for=0.15)
        self.assertLess(t.score(end), 0.1)


class BlinkTests(unittest.TestCase):
    def test_counts_normal_blinking(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 60, closed_every=3.5, closed_for=0.15)    # ~17 a minute
        self.assertAlmostEqual(t.blink_rate(end), 17, delta=2)

    def test_screen_stare(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 60, closed_every=12, closed_for=0.15)     # 5 a minute
        self.assertLess(t.blink_rate(end), camera.LOW_BLINK_RATE)

    def test_needs_a_full_minute(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 30, closed_every=12)
        self.assertIsNone(t.blink_rate(end))

    def test_closed_eyes_are_not_blinks(self):
        t = camera.EyeTracker()
        end = feed(t, 0, 60, closed_every=10, closed_for=3)        # looking down / eyes shut
        self.assertEqual(t.blink_rate(end), 0)

    def test_reminder_timing(self):
        r = camera.BlinkReminder()
        self.assertFalse(r.update(0, 5))
        self.assertFalse(r.update(60, 5))
        self.assertTrue(r.update(120, 5))          # low for 2 minutes
        self.assertFalse(r.update(300, 5))         # cooldown
        self.assertFalse(r.update(400, None))      # face lost resets
        self.assertFalse(r.update(700, 5))
        self.assertTrue(r.update(820, 5))

    def test_normal_rate_resets(self):
        r = camera.BlinkReminder()
        r.update(0, 5)
        r.update(100, 15)
        self.assertFalse(r.update(130, 5))


if __name__ == "__main__":
    unittest.main()
