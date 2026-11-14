import math
import unittest

from raise_hand import RaiseHandDetector


def sample(t, angle=0, gyro=0, magnitude=1, n=None):
    radians = math.radians(angle)
    return dict(t=t, ax=magnitude * math.sin(radians), ay=0,
                az=magnitude * math.cos(radians), gx=0, gy=gyro, gz=0, n=n)


class Motion:
    def __init__(self, detector=None):
        self.detector = detector or RaiseHandDetector()
        self.t = -20
        self.events = []

    def feed(self, angle=0, gyro=0, dt=20, **kwargs):
        self.t += dt
        event = self.detector.feed(sample(self.t, angle, gyro, **kwargs))
        if event:
            self.events.append(event)
        return event

    def hold(self, angle, count, **kwargs):
        for _ in range(count):
            self.feed(angle, **kwargs)

    def calibrate(self, angle=0):
        self.hold(angle, 41)

    def raise_arm(self, base=0, gyro=300):
        for step in range(1, 26):
            self.feed(base + 6 * step, gyro)
        self.hold(base + 150, 9)

    def lower_arm(self):
        for step in range(24, -1, -1):
            self.feed(6 * step, -300)
        self.hold(0, 16)


class RaiseHandDetectorTests(unittest.TestCase):
    def test_calibration_uses_device_time_and_averages_a_unit_baseline(self):
        motion = Motion()
        motion.hold(40, 40)
        self.assertEqual(motion.detector.phase, "calibrating")
        self.assertIsNone(motion.detector.baseline)
        motion.feed(40)
        self.assertEqual(motion.detector.phase, "armed")
        self.assertEqual(motion.detector.sample_count, 41)
        self.assertAlmostEqual(math.hypot(*motion.detector.baseline), 1)
        self.assertAlmostEqual(motion.detector.baseline[0], math.sin(math.radians(40)))

    def test_motion_acceleration_and_slow_direction_drift_cannot_calibrate(self):
        for profile in (lambda i: dict(gyro=35),
                        lambda i: dict(magnitude=1.4),
                        lambda i: dict(angle=i)):
            with self.subTest(profile=profile):
                motion = Motion()
                for index in range(100):
                    motion.feed(**profile(index))
                self.assertIsNone(motion.detector.baseline)
                self.assertEqual(motion.detector.phase, "calibrating")
                motion.calibrate()
                self.assertEqual(motion.detector.phase, "armed")

    def test_quick_raise_emits_once_until_lowered_and_rearmed(self):
        motion = Motion()
        motion.calibrate()
        motion.raise_arm()
        self.assertEqual(len(motion.events), 1)
        event = motion.events[0]
        self.assertEqual(event["type"], "hand_raise")
        self.assertEqual(event["gesture"], "quick_overhead")
        self.assertEqual(event["device_time_ms"], motion.t)
        self.assertEqual(event["duration_ms"], 660)
        self.assertAlmostEqual(event["angle_deg"], 150)
        self.assertEqual(event["peak_gyro_dps"], 300)
        motion.hold(150, 100)
        self.assertEqual(len(motion.events), 1)
        self.assertEqual(motion.detector.phase, "wait_down")
        motion.lower_arm()
        self.assertEqual(motion.detector.phase, "armed")
        self.assertEqual(len(motion.events), 1)
        motion.raise_arm()
        self.assertEqual(len(motion.events), 2)

    def test_detection_is_relative_to_calibrated_wearing_orientation(self):
        motion = Motion()
        motion.calibrate(angle=30)
        motion.raise_arm(base=30)
        self.assertEqual(len(motion.events), 1)
        self.assertAlmostEqual(motion.events[0]["angle_deg"], 150)

    def test_slow_raise_times_out_and_cannot_restart_while_held_up(self):
        motion = Motion()
        motion.calibrate()
        for angle in range(1, 151):
            motion.feed(angle, gyro=50)
        motion.hold(150, 100)
        self.assertEqual(motion.events, [])
        self.assertEqual(motion.detector.phase, "wait_down")
        motion.hold(150, 10, gyro=300)
        motion.hold(150, 20)
        self.assertEqual(motion.events, [])
        motion.lower_arm()
        motion.raise_arm()
        self.assertEqual(len(motion.events), 1)

    def test_overhead_pose_without_required_fast_rotation_does_not_fire(self):
        motion = Motion()
        motion.calibrate()
        motion.raise_arm(gyro=119.9)
        motion.hold(150, 100)
        self.assertEqual(motion.events, [])
        self.assertEqual(motion.detector.phase, "wait_down")

    def test_double_tap_spikes_and_fast_small_swings_do_not_fire(self):
        motion = Motion()
        motion.calibrate()
        for _ in range(2):
            motion.feed(170, gyro=500, magnitude=2.5)
            motion.feed(0, gyro=-400)
        motion.hold(0, 20)
        for _ in range(5):
            motion.feed(30, gyro=300)
            motion.feed(5, gyro=-300)
        motion.hold(0, 20)
        self.assertEqual(motion.events, [])
        self.assertEqual(motion.detector.phase, "armed")

    def test_target_hold_requires_continuous_still_samples(self):
        motion = Motion()
        motion.calibrate()
        for angle in range(6, 151, 6):
            motion.feed(angle, gyro=300)
        motion.hold(150, 7)  # Only 120 ms of a required 150 ms window.
        motion.feed(150, gyro=40)
        motion.hold(150, 8)  # Fresh window: 140 ms, not accumulated with the old one.
        self.assertEqual(motion.events, [])
        motion.feed(150)
        self.assertEqual(len(motion.events), 1)

    def test_quick_raise_allows_settling_before_stable_overhead_confirmation(self):
        motion = Motion()
        motion.calibrate()
        # Synthetic version of the observed failure mode, without recorded data:
        # arrive overhead quickly, then take longer to settle into a steady pose.
        for elapsed in range(0, 781, 20):
            motion.feed(150 * elapsed / 780, gyro=200)
        for _ in range(800, 1441, 20):
            motion.feed(150, gyro=40)
        for angle in (140, 142, 144):  # Just 40 ms of stability at elapsed 1500 ms.
            motion.feed(angle, gyro=20)
        self.assertEqual(motion.events, [])
        # At 1520 ms the new direction resets the fixed stability anchor.
        # Another 160 ms of consistent 50 Hz samples completes confirmation.
        motion.hold(150, 9, gyro=20)
        self.assertEqual(len(motion.events), 1)
        self.assertEqual(motion.events[0]["duration_ms"], 1680)
        self.assertEqual(motion.events[0]["peak_gyro_dps"], 200)
        self.assertEqual(motion.detector.phase, "wait_down")

    def test_confirmation_at_exact_deadline_and_fast_peak_boundary(self):
        for delay, expected_events in ((0, 1), (20, 0)):
            with self.subTest(delay=delay):
                detector = RaiseHandDetector()
                motion = Motion(detector)
                motion.calibrate()
                for t in range(820, 2460 + delay, 20):
                    detector.feed(sample(t, min(129, (t - 820) / 1620 * 129), gyro=120))
                events = []
                for t in range(2460 + delay, 2640 + delay, 20):
                    event = detector.feed(sample(t, angle=140))
                    if event:
                        events.append(event)
                self.assertEqual(len(events), expected_events)
                if events:
                    self.assertEqual(events[0]["duration_ms"], 1800)
                    self.assertEqual(events[0]["peak_gyro_dps"], 120)

    def test_stream_faults_cancel_candidate_keep_baseline_and_require_down(self):
        for fault in ("nan", "missing", "duplicate", "backward", "gap", "sequence"):
            with self.subTest(fault=fault):
                motion = Motion()
                motion.calibrate()
                baseline = motion.detector.baseline
                motion.feed(60, gyro=300, n=10)
                broken = sample(motion.t + 20, angle=150, n=11)
                if fault == "nan":
                    broken["ax"] = float("nan")
                elif fault == "missing":
                    del broken["gz"]
                elif fault == "duplicate":
                    broken["t"] = motion.t
                elif fault == "backward":
                    broken["t"] = motion.t - 20
                elif fault == "gap":
                    broken["t"] = motion.t + 201
                else:
                    broken["n"] = 12
                self.assertIsNone(motion.detector.feed(broken))
                self.assertEqual(motion.detector.baseline, baseline)
                self.assertEqual(motion.detector.phase, "wait_down")
                motion.t = broken["t"]
                motion.hold(150, 20)
                self.assertEqual(motion.events, [])
                motion.lower_arm()
                self.assertEqual(motion.detector.phase, "armed")
                motion.raise_arm()
                self.assertEqual(len(motion.events), 1)

    def test_sequence_wrap_and_optional_sequence_are_supported(self):
        motion = Motion()
        motion.calibrate()
        for n in (0xFFFFFFFE, 0xFFFFFFFF, 0, 1, None, 72, 73):
            motion.feed(n=n)
            self.assertEqual(motion.detector.phase, "armed")

    def test_rearm_requires_continuous_down_pose_for_three_hundred_ms(self):
        motion = Motion()
        motion.calibrate()
        motion.raise_arm()
        motion.hold(0, 15)
        self.assertEqual(motion.detector.phase, "wait_down")
        motion.feed(0, gyro=40)
        motion.hold(0, 15)
        self.assertEqual(motion.detector.phase, "wait_down")
        motion.feed(0)
        self.assertEqual(motion.detector.phase, "armed")

    def test_explicit_calibration_discards_baseline_and_sample_count(self):
        motion = Motion()
        motion.calibrate()
        motion.raise_arm()
        motion.detector.calibrate()
        self.assertIsNone(motion.detector.baseline)
        self.assertIsNone(motion.detector.calibration_profile())
        self.assertEqual(motion.detector.phase, "calibrating")
        self.assertEqual(motion.detector.sample_count, 0)
        motion.calibrate(angle=60)
        self.assertEqual(motion.detector.phase, "armed")
        self.assertAlmostEqual(motion.detector.baseline[0], math.sin(math.radians(60)))

    def test_calibration_profile_round_trip_and_export_are_independent(self):
        motion = Motion()
        self.assertIsNone(motion.detector.calibration_profile())
        motion.calibrate(angle=40)
        profile = motion.detector.calibration_profile()
        self.assertEqual(profile["version"], 1)
        self.assertEqual(profile["baseline"], list(motion.detector.baseline))
        restored = RaiseHandDetector()
        restored.restore_calibration(profile)
        self.assertEqual(restored.phase, "wait_down")
        for actual, expected in zip(restored.baseline, motion.detector.baseline):
            self.assertAlmostEqual(actual, expected)
        profile["baseline"][0] = -999
        self.assertGreater(motion.detector.baseline[0], 0)
        self.assertGreater(restored.baseline[0], 0)

    def test_restored_baseline_requires_real_down_pose_before_arming(self):
        motion = Motion()
        motion.detector.restore_calibration({"baseline": [0, 0, 5]})
        self.assertEqual(motion.detector.baseline, (0, 0, 1))
        motion.hold(150, 50)
        self.assertEqual(motion.detector.phase, "wait_down")
        self.assertEqual(motion.events, [])
        motion.hold(0, 15)
        self.assertEqual(motion.detector.phase, "wait_down")
        motion.feed(0)
        self.assertEqual(motion.detector.phase, "armed")
        motion.raise_arm()
        self.assertEqual(len(motion.events), 1)

    def test_restoring_cancels_candidate_and_resets_device_time_and_sequence(self):
        motion = Motion()
        motion.calibrate()
        motion.feed(60, gyro=300, n=42)
        self.assertEqual(motion.detector.phase, "raising")
        motion.detector.restore_calibration(motion.detector.calibration_profile())
        self.assertEqual(motion.detector.phase, "wait_down")
        # A restarted device can begin with a different clock and sequence.
        for index in range(16):
            self.assertIsNone(motion.detector.feed(sample(index * 20, n=999 + index)))
        self.assertEqual(motion.detector.phase, "armed")

    def test_invalid_profiles_do_not_change_valid_baseline_or_candidate(self):
        motion = Motion()
        motion.calibrate()
        motion.feed(60, gyro=300)
        profile = motion.detector.calibration_profile()
        count = motion.detector.sample_count
        invalid_profiles = (
            None, [], {}, {"baseline": "001"}, {"baseline": [0, 1]},
            {"baseline": [0, 0, 1, 1]}, {"baseline": [0, 0, 0]},
            {"baseline": [True, 0, 1]}, {"baseline": [0, "0", 1]},
            {"baseline": [float("nan"), 0, 1]},
            {"baseline": [0, float("inf"), 1]},
            {"baseline": [0, 0, 10 ** 1000]},
            {"version": 2, "baseline": [0, 0, 1]},
            {"version": True, "baseline": [0, 0, 1]},
        )
        for invalid in invalid_profiles:
            with self.subTest(profile=invalid):
                with self.assertRaises(ValueError):
                    motion.detector.restore_calibration(invalid)
                self.assertEqual(motion.detector.calibration_profile(), profile)
                self.assertEqual(motion.detector.phase, "raising")
                self.assertEqual(motion.detector.sample_count, count)
        for angle in range(66, 151, 6):
            motion.feed(angle, gyro=300)
        motion.hold(150, 9)
        self.assertEqual(len(motion.events), 1)

    def test_finite_extreme_profiles_normalize_without_overflow_or_underflow(self):
        for size in (1.7e308, 1e-320):
            with self.subTest(size=size):
                detector = RaiseHandDetector()
                detector.restore_calibration({"baseline": [size, size, size]})
                self.assertAlmostEqual(math.hypot(*detector.baseline), 1)
                for axis in detector.baseline:
                    self.assertAlmostEqual(axis, 1 / math.sqrt(3))


if __name__ == "__main__":
    unittest.main()
