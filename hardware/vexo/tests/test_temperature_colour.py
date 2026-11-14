import unittest

from temperature_colour import TemperatureColour


class TemperatureColourTests(unittest.TestCase):
    def test_baseline_stays_at_first_valid_sample(self):
        state = TemperatureColour()
        self.assertIsNone(state.colour(now=0))
        self.assertTrue(state.receive(30, now=0))
        self.assertEqual(state.colour(now=0), "#0066ff")
        state.receive(30.25, now=1)
        self.assertEqual(state.baseline, 30)
        self.assertEqual(state.celsius, 30.25)
        self.assertEqual(state.delta, 0.25)
        self.assertEqual(state.colour(now=1), "#00d4ff")

    def test_quarter_degree_measurements_reach_warmer_colours(self):
        state = TemperatureColour()
        state.receive(30, now=0)
        for delta, colour in ((0.5, "#ffd23f"), (0.75, "#ff7a00"), (1, "#ff2400")):
            with self.subTest(delta=delta):
                state.receive(30 + delta, now=1)
                self.assertEqual(state.colour(now=1), colour)

    def test_colours_clamp_without_clamping_temperature(self):
        state = TemperatureColour()
        state.receive(30, now=0)
        state.receive(28, now=1)
        self.assertEqual(state.colour(now=1), "#0066ff")
        self.assertEqual(state.delta, -2)
        state.receive(34, now=2)
        self.assertEqual(state.colour(now=2), "#ff2400")
        self.assertEqual(state.delta, 4)

    def test_stale_sample_stops_output_and_fresh_sample_restores_it(self):
        state = TemperatureColour(stale_after=5)
        state.receive(30, now=0)
        self.assertEqual(state.colour(now=4.99), "#0066ff")
        self.assertIsNone(state.colour(now=5))
        state.receive(30.25, now=6)
        self.assertEqual(state.baseline, 30)
        self.assertEqual(state.colour(now=6), "#00d4ff")

    def test_invalid_measurements_clear_output_but_not_baseline(self):
        for invalid in (float("nan"), float("inf"), -40.25, 85.25, None, True):
            with self.subTest(invalid=invalid):
                state = TemperatureColour()
                self.assertFalse(state.receive(invalid, now=0))
                self.assertIsNone(state.baseline)
                state.receive(30, now=1)
                self.assertFalse(state.receive(invalid, now=2))
                self.assertIsNone(state.colour(now=2))
                self.assertIsNone(state.celsius)
                self.assertIsNone(state.delta)
                self.assertEqual(state.baseline, 30)
                self.assertTrue(state.receive(30.25, now=3))
                self.assertEqual(state.colour(now=3), "#00d4ff")

    def test_warming_range_is_configurable(self):
        state = TemperatureColour(warm_delta=2)
        state.receive(30, now=0)
        state.receive(31, now=1)
        self.assertEqual(state.colour(now=1), "#ffd23f")


if __name__ == "__main__":
    unittest.main()
