import copy
import math
import unittest

from trained_raise import TrainedRaiseDetector


def sample(t, angle=0, gyro=0, axis="gy", **extra):
    radians = math.radians(angle)
    row = dict(t=t, ax=math.sin(radians), ay=0, az=math.cos(radians), gx=0, gy=0, gz=0, n=None)
    row[axis] = gyro
    row.update(extra)
    return row


class Motion:
    def __init__(self, detector=None):
        self.detector = detector or TrainedRaiseDetector()
        self.t = -20
        self.events = []

    def feed(self, angle=0, gyro=0, dt=20, **extra):
        self.t += dt
        event = self.detector.feed(sample(self.t, angle, gyro, **extra))
        if event:
            self.events.append(event)
        return event

    def hold(self, angle, count=51):
        for _ in range(count):
            self.feed(angle)

    def move(self, start, end, steps=30, gyro=None):
        gyro = (end - start) / (steps * .02) if gyro is None else gyro
        for step in range(1, steps + 1):
            self.feed(start + (end - start) * step / steps, gyro)
        self.hold(end)

    def train(self):
        self.detector.calibrate()
        self.detector.begin_training()
        self.hold(0)
        for steps in (30, 31, 29):
            self.move(0, 150, steps)
            self.move(150, 0, steps)


class TrainedRaiseTests(unittest.TestCase):
    def test_three_rounds_train_positive_and_negative_then_recognize_new_raise(self):
        motion = Motion()
        motion.train()
        detector = motion.detector
        self.assertEqual(motion.events, [])
        self.assertFalse(detector.raised)
        self.assertEqual(detector.training_counts, {"raise": 3, "lower": 3})
        self.assertTrue(detector.ready)
        self.assertFalse(detector.training)
        self.assertEqual(detector.model_revision, 7)  # Explicit calibration + six recordings.
        self.assertEqual(detector.phase, "armed")
        self.assertGreaterEqual(detector.limit, .5)
        self.assertTrue(all(len(item["shape"]) == 144 for item in detector.calibration_profile()["templates"]))

        motion.move(0, 150, steps=32)
        self.assertEqual(len(motion.events), 1)
        event = motion.events[0]
        self.assertEqual((event["type"], event["gesture"]), ("hand_raise", "quick_overhead"))
        self.assertLessEqual(event["match_distance"], detector.limit)
        self.assertEqual(detector.phase, "wait_down")
        self.assertTrue(detector.raised)
        motion.move(150, 0, steps=32)
        self.assertEqual(len(motion.events), 1)
        self.assertEqual(detector.last_observation["label"], "lower")
        self.assertEqual(detector.phase, "armed")
        self.assertFalse(detector.raised)

    def test_high_pose_repetition_is_latched_and_unknown_motion_is_not_a_raise(self):
        motion = Motion()
        motion.train()
        motion.move(0, 150)
        motion.move(0, 150)  # Similar signal, but no actual stable return down.
        self.assertEqual(len(motion.events), 1)
        motion.move(150, 0)
        for step in range(30):
            motion.feed(20 * math.sin(step / 29 * math.pi), 900, axis="gx")
        motion.hold(0)
        self.assertIsNone(motion.detector.last_observation["label"])
        self.assertEqual(len(motion.events), 1)
        motion.move(0, 150)
        self.assertEqual(len(motion.events), 2)

    def test_profile_round_trip_requires_actual_down_and_keeps_models_independent(self):
        trained = Motion()
        trained.train()
        profile = trained.detector.calibration_profile()
        restored = TrainedRaiseDetector()
        restored.restore_calibration(profile)
        motion = Motion(restored)
        self.assertTrue(restored.ready)
        self.assertEqual(restored.phase, "wait_down")
        motion.hold(150)
        self.assertEqual(restored.phase, "wait_down")
        motion.move(150, 0)
        self.assertEqual(restored.phase, "armed")
        motion.move(0, 150, steps=32)
        self.assertEqual(len(motion.events), 1)
        profile["templates"][0]["shape"][0] = 999
        self.assertNotEqual(restored.calibration_profile()["templates"][0]["shape"][0], 999)

    def test_invalid_model_imports_do_not_pollute_a_valid_model(self):
        motion = Motion()
        motion.train()
        original = motion.detector.calibration_profile()
        variants = [None, {"version": 3}, {"version": 2, "baseline": [0, 0, 0]}]
        for mutation in (lambda p: p.update(limit=float("nan")),
                         lambda p: p["templates"][0].update(label="other"),
                         lambda p: p["templates"][0].update(label=[]),
                         lambda p: p["templates"][0].update(shape=[0] * 143),
                         lambda p: p["templates"][0]["shape"].__setitem__(0, True),
                         lambda p: p["templates"].append(copy.deepcopy(p["templates"][0]))):
            invalid = copy.deepcopy(original)
            mutation(invalid)
            variants.append(invalid)
        for invalid in variants:
            with self.subTest(profile=invalid):
                with self.assertRaises(ValueError):
                    motion.detector.restore_calibration(invalid)
                self.assertEqual(motion.detector.calibration_profile(), original)
                self.assertEqual(motion.detector.phase, "armed")

    def test_legacy_baseline_can_train_and_recalibration_discards_old_templates(self):
        detector = TrainedRaiseDetector()
        detector.restore_calibration({"version": 1, "baseline": [0, 0, 2]})
        self.assertEqual(detector.baseline, (0, 0, 1))
        self.assertFalse(detector.ready)
        self.assertFalse(detector.training)
        motion = Motion(detector)
        detector.begin_training()
        motion.hold(0)
        motion.move(0, 150)
        self.assertEqual(detector.training_counts, {"raise": 1, "lower": 0})
        detector.calibrate()
        self.assertIsNone(detector.calibration_profile())
        self.assertEqual(detector.training_counts, {"raise": 0, "lower": 0})

    def test_stream_interruptions_cancel_segments_without_losing_templates(self):
        trained = Motion()
        trained.train()
        profile = trained.detector.calibration_profile()
        for fault in ("invalid", "gap", "sequence"):
            with self.subTest(fault=fault):
                detector = TrainedRaiseDetector()
                detector.restore_calibration(profile)
                motion = Motion(detector)
                motion.hold(0)
                for angle in range(5, 76, 5):
                    motion.feed(angle, 250, n=angle // 5)
                if fault == "invalid":
                    motion.feed(80, 250, ax=float("nan"))
                elif fault == "gap":
                    motion.feed(80, 250, dt=220)
                else:
                    motion.feed(80, 250, n=99)
                for angle in range(85, 151, 5):
                    motion.feed(angle, 250)
                motion.hold(150)
                self.assertEqual(motion.events, [])
                self.assertEqual(detector.phase, "wait_down")
                self.assertEqual(detector.calibration_profile(), profile)
                motion.move(150, 0)
                motion.move(0, 150)
                self.assertEqual(len(motion.events), 1)

    def test_template_similarity_does_not_override_fast_or_duration_guards(self):
        motion = Motion(TrainedRaiseDetector(match_limit=2))
        motion.train()
        motion.move(0, 150, gyro=119)
        self.assertEqual(motion.detector.last_observation["label"], "raise")
        self.assertEqual(motion.events, [])
        motion.move(150, 0)
        motion.move(0, 150, steps=121, gyro=250)
        self.assertEqual(motion.detector.last_observation["label"], "raise")
        self.assertEqual(motion.events, [])

    def test_raised_clears_at_shoulder_height_without_rearming(self):
        motion = Motion()
        motion.train()
        motion.move(0, 150)
        self.assertTrue(motion.detector.raised)
        motion.hold(150)
        self.assertTrue(motion.detector.raised)
        motion.move(150, 90, steps=15)
        self.assertFalse(motion.detector.raised)
        self.assertEqual(motion.detector.phase, "wait_down")
        self.assertEqual(len(motion.events), 1)
        motion.move(90, 150)
        self.assertFalse(motion.detector.raised)
        self.assertEqual(len(motion.events), 1)
        motion.move(150, 0)
        motion.move(0, 150)
        self.assertTrue(motion.detector.raised)
        self.assertEqual(len(motion.events), 2)

    def test_raised_requires_sustained_pose_departure_and_clears_on_resets(self):
        trained = Motion()
        trained.train()
        profile = trained.detector.calibration_profile()
        for reset in ("calibrate", "train", "restore", "invalid", "gap", "sequence"):
            with self.subTest(reset=reset):
                detector = TrainedRaiseDetector()
                detector.restore_calibration(profile)
                motion = Motion(detector)
                motion.hold(0)
                motion.move(0, 150)
                self.assertTrue(detector.raised)
                motion.feed(90)  # A brief displacement cannot clear held state.
                motion.feed(150)
                motion.hold(150, 10)
                self.assertTrue(detector.raised)
                if reset == "calibrate":
                    detector.calibrate()
                elif reset == "train":
                    detector.begin_training()
                elif reset == "restore":
                    detector.restore_calibration(profile)
                elif reset == "invalid":
                    motion.feed(150, ax=float("nan"))
                elif reset == "gap":
                    motion.feed(150, dt=220)
                else:
                    motion.feed(150, n=10)
                    motion.feed(150, n=12)
                self.assertFalse(detector.raised)
                self.assertNotEqual(detector.phase, "armed")

if __name__ == "__main__":
    unittest.main()
