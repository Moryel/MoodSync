"""Tests for the color logic and device handling (no OpenRGB server or screen needed)."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main  # noqa: E402


def solid(color, size=(10, 10)):
    """An RGB image filled with one color."""
    return np.full((*size, 3), color, dtype=np.uint8)


class PickColorTests(unittest.TestCase):
    def test_average_of_solid_image(self):
        self.assertEqual(main.pick_color(solid((200, 100, 50)), "average"), (200, 100, 50))

    def test_average_ignores_black_bars(self):
        img = solid((0, 0, 0), (20, 10))
        img[5:15] = (0, 0, 255)
        self.assertEqual(main.pick_color(img, "average"), (0, 0, 255))

    def test_all_black_screen(self):
        self.assertEqual(main.pick_color(solid((5, 5, 5)), "average"), (0, 0, 0))

    def test_dominant_picks_largest_hue(self):
        img = solid((255, 0, 0), (10, 10))
        img[:3] = (0, 255, 0)
        img[3:4] = (128, 128, 128)
        self.assertEqual(main.pick_color(img, "dominant"), (255, 0, 0))

    def test_dominant_falls_back_to_average_on_grey(self):
        self.assertEqual(main.pick_color(solid((120, 120, 120)), "dominant"), (120, 120, 120))

    def test_center_uses_plain_mean(self):
        img = solid((0, 0, 0), (2, 1))
        img[0] = (100, 100, 100)
        self.assertEqual(main.pick_color(img, "center"), (50, 50, 50))


class AdjustTests(unittest.TestCase):
    def test_saturation_boost(self):
        r, g, b = main.adjust_color((200, 150, 150), 2.0, 1.0)
        self.assertEqual(r, 200)
        self.assertLess(g, 150)

    def test_neutral_settings_keep_color(self):
        self.assertEqual(main.adjust_color((10, 200, 30), 1.0, 1.0), (10, 200, 30))

    def test_brightness_cap(self):
        self.assertEqual(main.adjust_color((255, 255, 255), 1.0, 0.5), (128, 128, 128))

    def test_smoothing(self):
        self.assertEqual(main.smooth_color(None, (10, 10, 10), 0.5), (10, 10, 10))
        self.assertEqual(main.smooth_color((0, 0, 0), (100, 50, 0), 0.5), (50, 25, 0))
        self.assertEqual(main.smooth_color((0, 0, 0), (100, 50, 0), 0), (100, 50, 0))

    def test_color_changed(self):
        self.assertTrue(main.color_changed(None, (0, 0, 0), 10))
        self.assertFalse(main.color_changed((0, 0, 0), (10, 10, 10), 10))
        self.assertTrue(main.color_changed((0, 0, 0), (0, 11, 0), 10))


class ArgTests(unittest.TestCase):
    def test_defaults(self):
        args = main.parse_args([])
        self.assertEqual(args.monitor, main.MONITOR_INDEX)
        self.assertEqual(args.exit_color, (0, 0, 0))

    def test_hex_color(self):
        self.assertEqual(main.parse_hex_color("#ff8800"), (255, 136, 0))
        with self.assertRaises(ValueError):
            main.parse_hex_color("fff")

    def test_invalid_values_rejected(self):
        for bad in (["--fps", "0"], ["--smoothing", "1"], ["--brightness", "2"], ["--exit-color", "xyz"]):
            with self.assertRaises(SystemExit):
                main.parse_args(bad)


class FakeMode:
    def __init__(self, name):
        self.name = name


class FakeDevice:
    def __init__(self, name, modes=("Static", "Direct"), fail=None):
        self.name = name
        self.modes = [FakeMode(m) for m in modes]
        self.fail = fail
        self.mode = None
        self.colors = []

    def set_mode(self, index):
        self.mode = self.modes[index].name

    def set_color(self, color, fast=False):
        if self.fail:
            raise self.fail
        self.colors.append((color.red, color.green, color.blue, fast))


class FakeClient:
    def __init__(self, devices):
        self.devices = devices


class DeviceTests(unittest.TestCase):
    def test_direct_mode_and_colors(self):
        a, b = FakeDevice("Corsair RAM"), FakeDevice("Mouse", modes=("Static",))
        main.set_direct_mode([a, b])
        self.assertEqual(a.mode, "Direct")
        self.assertIsNone(b.mode)
        main.set_all_devices_color([a, b], 1, 2, 3)
        self.assertEqual(a.colors, [(1, 2, 3, True)])

    def test_busy_device_is_skipped(self):
        busy, ok = FakeDevice("Busy", fail=ValueError("busy")), FakeDevice("Ok")
        main.set_all_devices_color([busy, ok], 9, 9, 9)
        self.assertEqual(len(ok.colors), 1)

    def test_disconnect_is_raised(self):
        gone = FakeDevice("Gone", fail=main.OpenRGBDisconnected())
        with self.assertRaises(main.OpenRGBDisconnected):
            main.set_all_devices_color([gone], 0, 0, 0)

    def test_device_filter(self):
        client = FakeClient([FakeDevice("Razer Huntsman"), FakeDevice("Corsair Vengeance")])
        self.assertEqual([d.name for d in main.select_devices(client, ["corsair"])], ["Corsair Vengeance"])
        self.assertEqual(len(main.select_devices(client, None)), 2)


if __name__ == "__main__":
    unittest.main()
