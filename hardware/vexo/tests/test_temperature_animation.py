import unittest
from unittest.mock import patch

from temperature_animation import TemperatureAnimation


class TemperatureAnimationTests(unittest.TestCase):
    def test_idle_stays_blue_until_started(self):
        animation = TemperatureAnimation()
        self.assertEqual(animation.colour(now=0), "#0000ff")
        self.assertEqual(animation.colour(now=300), "#0000ff")
        self.assertFalse(animation.is_active)
        self.assertIsNone(animation.started_at)

    def test_each_colour_lasts_three_seconds(self):
        animation = TemperatureAnimation()
        animation.restart(now=100)
        for seconds, colour in (
            (0, "#0000ff"), (2.999, "#0000ff"),
            (3, "#00ffff"), (5.999, "#00ffff"),
            (6, "#ffff00"), (8.999, "#ffff00"),
            (9, "#ff8000"), (11.999, "#ff8000"),
            (12, "#ff0000"), (14.999, "#ff0000"),
        ):
            with self.subTest(seconds=seconds):
                self.assertEqual(animation.colour(now=100 + seconds), colour)
                self.assertTrue(animation.is_active)
                self.assertEqual(animation.started_at, 100)

    def test_finishing_at_fifteen_seconds_returns_to_idle_blue(self):
        animation = TemperatureAnimation()
        animation.restart(now=100)
        self.assertEqual(animation.colour(now=115), "#0000ff")
        self.assertFalse(animation.is_active)
        self.assertIsNone(animation.started_at)
        self.assertEqual(animation.colour(now=160), "#0000ff")

    def test_another_double_tap_restarts_the_full_animation(self):
        colours = ("#0000ff", "#00ffff", "#ffff00", "#ff8000", "#ff0000")
        for index, colour in enumerate(colours):
            with self.subTest(restarting_from=colour):
                animation = TemperatureAnimation()
                animation.restart(now=0)
                restart_at = 3 * index + 1
                self.assertEqual(animation.colour(now=restart_at), colour)
                animation.restart(now=restart_at)
                self.assertEqual(animation.started_at, restart_at)
                for elapsed, expected in enumerate(colours):
                    self.assertEqual(animation.colour(now=restart_at + 3 * elapsed), expected)
                    self.assertTrue(animation.is_active)
                self.assertEqual(animation.colour(now=restart_at + 14.999), "#ff0000")
                self.assertEqual(animation.colour(now=restart_at + 15), "#0000ff")
                self.assertFalse(animation.is_active)

    def test_restart_works_after_a_completed_animation(self):
        animation = TemperatureAnimation()
        animation.restart(now=0)
        animation.colour(now=60)
        animation.restart(now=70)
        self.assertTrue(animation.is_active)
        self.assertEqual(animation.colour(now=70), "#0000ff")
        self.assertEqual(animation.colour(now=73), "#00ffff")

    def test_default_clock_is_monotonic(self):
        animation = TemperatureAnimation()
        with patch("temperature_animation.time.monotonic", side_effect=[100, 106]):
            animation.restart()
            self.assertEqual(animation.started_at, 100)
            self.assertEqual(animation.colour(), "#ffff00")


if __name__ == "__main__":
    unittest.main()
