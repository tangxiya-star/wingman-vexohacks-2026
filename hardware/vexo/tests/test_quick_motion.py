import json
import math
import unittest

from quick_motion import QuickMotionDetector


class Motion:
    def __init__(self, detector=None, direction=(1, 0, 0)):
        self.detector = detector or QuickMotionDetector()
        self.direction = direction
        self.t, self.n = -20, -1
        self.events = []

    def feed(self, magnitude=1, dt=20, **overrides):
        self.t += dt
        self.n = (self.n + 1) & 0xFFFFFFFF
        row = dict(t=self.t, n=self.n, ax=self.direction[0] * magnitude,
                   ay=self.direction[1] * magnitude, az=self.direction[2] * magnitude)
        row.update(overrides)
        event = self.detector.feed(row)
        if event is not None:
            self.events.append(event)
        return event

    def hold(self, magnitude=1, count=21, **kwargs):
        for _ in range(count):
            self.feed(magnitude, **kwargs)


class QuickMotionTests(unittest.TestCase):
    def test_new_defaults_require_both_stronger_and_longer_motion(self):
        motion = Motion()
        motion.hold()
        motion.hold(1.7, 9)  # 0.7 g deviation for 160 ms is too light.
        self.assertFalse(motion.detector.latched)
        motion.feed(1)
        motion.hold(2.0, 6)  # Strong enough, but only 100 ms.
        self.assertFalse(motion.detector.latched)
        event = motion.feed(2.0)
        self.assertEqual(event["duration_ms"], 120)
        self.assertEqual(event["peak_acceleration_g"], 2.0)

    def test_old_threshold_remains_available_only_when_explicitly_configured(self):
        motion = Motion(QuickMotionDetector(threshold_g=.5, sustain_ms=80))
        motion.hold()
        motion.hold(1.7, 4)
        self.assertFalse(motion.detector.latched)
        event = motion.feed(1.7)
        self.assertEqual(event["duration_ms"], 80)

    def test_quiet_arming_then_multisample_pulse_triggers_one_derived_event(self):
        motion = Motion()
        motion.hold(1.8, 20)
        self.assertFalse(motion.detector.ready)
        motion.hold(1, 15)
        self.assertFalse(motion.detector.ready)  # 280 ms, not 300 ms.
        motion.feed()
        self.assertTrue(motion.detector.ready)
        motion.hold(2.0, 6)
        self.assertFalse(motion.detector.latched)  # 100 ms, not 120 ms.
        event = motion.feed(2.1)
        self.assertEqual(event["type"], "quick_motion")
        self.assertEqual(event["duration_ms"], 120)
        self.assertAlmostEqual(event["peak_acceleration_g"], 2.1)
        self.assertAlmostEqual(event["peak_deviation_g"], 1.1)
        self.assertEqual(json.loads(json.dumps(event, allow_nan=False)), event)
        self.assertNotIn("ax", event)
        self.assertNotIn("heart_rate", event)
        motion.hold(1, 30)
        motion.hold(2, 30)
        self.assertEqual(len(motion.events), 1)
        self.assertEqual(motion.detector.phase, "latched")

    def test_orientation_independent_and_does_not_read_gyro(self):
        for direction in ((1, 0, 0), (0, -1, 0), (1/3, 2/3, 2/3)):
            with self.subTest(direction=direction):
                motion = Motion(direction=direction)
                motion.hold(gx=math.nan, gy="ignored", gz=None)
                motion.hold(2.0, 7, gx=math.nan)
                self.assertTrue(motion.detector.latched)
        motion = Motion()
        motion.hold()
        for index in range(100):
            angle = index * .5
            motion.feed(ax=math.sin(angle), ay=0, az=math.cos(angle))
        self.assertEqual(motion.events, [])

    def test_noise_single_shocks_and_short_or_interrupted_pulses_do_not_trigger(self):
        motion = Motion()
        for index in range(30):
            motion.feed(1 + .06 * math.sin(index))
        self.assertTrue(motion.detector.ready)
        for _ in range(5):
            motion.feed(3)
            motion.hold(1, 10)
            motion.hold(2.0, 6)
            motion.feed(1)
        motion.hold(1.45, 30)
        self.assertEqual(motion.events, [])
        motion.hold(2.0, 7)
        self.assertEqual(len(motion.events), 1)

    def test_low_acceleration_pulse_is_generic_motion_not_overhead(self):
        motion = Motion()
        motion.hold()
        motion.hold(.1, 7)
        event = motion.events[0]
        self.assertAlmostEqual(event["peak_acceleration_g"], .1)
        self.assertAlmostEqual(event["peak_deviation_g"], .9)
        self.assertNotIn("gesture", event)

    def test_manual_reset_requires_cooldown_and_a_new_quiet_window(self):
        motion = Motion()
        motion.hold()
        motion.hold(2.0, 7)
        motion.detector.reset()
        self.assertFalse(motion.detector.latched)
        self.assertFalse(motion.detector.ready)
        motion.hold(1.8, 30)
        self.assertEqual(len(motion.events), 1)
        motion.hold(1, 16)
        self.assertTrue(motion.detector.ready)
        motion.hold(2.0, 7)
        self.assertEqual(len(motion.events), 2)
        motion.detector.reset()
        motion.hold(1, 16)
        self.assertFalse(motion.detector.ready)  # Quiet, but only 300 ms of cooldown.
        motion.hold(1, 5)
        self.assertTrue(motion.detector.ready)

    def test_invalid_and_backwards_samples_preserve_latch_but_clear_readiness(self):
        motion = Motion()
        motion.hold()
        motion.hold(2.0, 7)
        for overrides in ({"n": 0}, {"t": 0}, {"ax": math.nan}, {"t": -1}, {"ay": True}):
            with self.subTest(overrides=overrides):
                motion.feed(**overrides)
                self.assertTrue(motion.detector.latched)
                self.assertFalse(motion.detector.ready)
                motion.hold(1, 25)
                self.assertTrue(motion.detector.ready)
                self.assertTrue(motion.detector.latched)
        self.assertEqual(len(motion.events), 1)

    def test_short_forward_packet_loss_keeps_armed_but_cannot_join_a_pulse(self):
        motion = Motion()
        motion.hold()
        motion.hold(2.0, 6)
        motion.n += 2  # Two missing samples: the next number advances by three.
        self.assertIsNone(motion.feed(2.0, dt=60))
        self.assertTrue(motion.detector.ready)
        self.assertFalse(motion.detector.latched)
        self.assertIsNone(motion.feed(2.0))
        self.assertEqual(motion.events, [])
        motion.hold(2.0, 6)  # Seven new consecutive samples after the gap.
        self.assertEqual(len(motion.events), 1)
        self.assertEqual(motion.events[0]["duration_ms"], 120)

    def test_latched_forward_packet_loss_keeps_ready_without_an_extra_event(self):
        motion = Motion()
        motion.hold()
        motion.hold(2.0, 7)
        for dt, delta in ((60, 3), (100, 5), (140, 7)):
            motion.n += delta - 1
            self.assertIsNone(motion.feed(1.8, dt=dt))
            self.assertTrue(motion.detector.ready)
            self.assertTrue(motion.detector.latched)
            self.assertEqual(motion.detector.phase, "latched")
        self.assertEqual(len(motion.events), 1)

    def test_packet_loss_cannot_count_toward_initial_or_restored_quiet_arming(self):
        for restore in (False, True):
            with self.subTest(restore=restore):
                motion = Motion()
                if restore:
                    motion.detector.restore_latch()
                motion.hold(1, 14)
                motion.n += 2
                motion.feed(1, dt=60)
                motion.hold(1, 10)
                self.assertFalse(motion.detector.ready)
                motion.hold(1, 6)
                self.assertTrue(motion.detector.ready)
                self.assertEqual(motion.detector.latched, restore)

    def test_gap_cancels_candidate_and_sequence_wrap_is_continuous(self):
        motion = Motion()
        motion.hold()
        motion.hold(2.0, 6)
        motion.feed(1.8, dt=120)
        self.assertFalse(motion.detector.latched)
        self.assertFalse(motion.detector.ready)
        motion.hold(1.8, 10)
        self.assertEqual(motion.events, [])
        motion.hold()
        motion.hold(2.0, 7)
        self.assertEqual(len(motion.events), 1)
        wrapped = Motion()
        wrapped.n = 0xFFFFFFF8
        wrapped.hold()
        wrapped.hold(2.0, 7)
        self.assertTrue(wrapped.detector.latched)

    def test_restored_latch_requires_live_quiet_and_can_only_be_reset_explicitly(self):
        motion = Motion()
        motion.detector.restore_latch()
        self.assertTrue(motion.detector.latched)
        self.assertFalse(motion.detector.ready)
        motion.hold(1.8, 20)
        self.assertFalse(motion.detector.ready)
        motion.hold()
        self.assertTrue(motion.detector.ready)
        self.assertTrue(motion.detector.latched)
        self.assertEqual(motion.events, [])
        motion.detector.reset()
        motion.hold(1, 22)
        motion.hold(2.0, 7)
        self.assertEqual(len(motion.events), 1)

    def test_configurable_threshold_and_real_timestamp_duration(self):
        motion = Motion(QuickMotionDetector(threshold_g=.7, sustain_ms=100))
        motion.hold()
        motion.hold(1.6, 20)
        self.assertEqual(motion.events, [])
        for dt in (19, 21, 17, 23, 22):
            motion.feed(1.9, dt=dt)
        self.assertFalse(motion.detector.latched)  # Four intervals: 83 ms.
        event = motion.feed(1.9, dt=20)
        self.assertEqual(event["duration_ms"], 103)
        for kwargs in ({"threshold_g": math.nan}, {"min_pulse_samples": True},
                       {"min_pulse_samples": 2}, {"quiet_deviation_g": .9}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                QuickMotionDetector(**kwargs)


if __name__ == "__main__":
    unittest.main()
