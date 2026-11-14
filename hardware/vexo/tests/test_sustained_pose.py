import copy
import math
import unittest

from sustained_pose import SustainedPoseEstimator


def direction(angle):
    radians = math.radians(angle)
    return (math.sin(radians), 0.0, math.cos(radians))


class Motion:
    def __init__(self, estimator=None, mounted=False):
        self.pose = estimator or SustainedPoseEstimator()
        self.t, self.n = -20, -1
        self.mounted = mounted

    def feed(self, angle=0, *, gyro=0, magnitude=1, dt=20, **overrides):
        self.t += dt
        self.n = (self.n + 1) & 0xFFFFFFFF
        vector = direction(angle)
        if self.mounted:
            # A fixed device mounting rotation: sensor Z becomes sensor Y.
            vector = (vector[2], vector[0], vector[1])
        row = dict(t=self.t, n=self.n, ax=vector[0] * magnitude,
                   ay=vector[1] * magnitude, az=vector[2] * magnitude,
                   gx=0, gy=gyro, gz=0)
        row.update(overrides)
        return self.pose.feed(row)

    def hold(self, angle, count=51, **kwargs):
        for _ in range(count):
            self.feed(angle, **kwargs)

    def calibrate(self):
        self.pose.begin_calibration("down")
        self.hold(0)
        self.pose.begin_calibration("up")
        self.hold(150)


class SustainedPoseTests(unittest.TestCase):
    def test_explicit_two_pose_calibration_and_slow_raise_need_no_gesture(self):
        motion = Motion()
        motion.hold(150, 100)
        self.assertFalse(motion.pose.ready)
        self.assertEqual(motion.pose.state, "unknown")
        motion.pose.begin_calibration("down")
        motion.hold(0, 40)
        self.assertIsNotNone(motion.pose.calibrating)  # Only 780 ms.
        motion.feed(0)
        self.assertIsNone(motion.pose.calibrating)
        self.assertFalse(motion.pose.ready)
        motion.pose.begin_calibration("up")
        motion.hold(150, 41)
        self.assertTrue(motion.pose.ready)
        self.assertFalse(motion.pose.raised)  # Calibration is never a pose result.
        motion.hold(0, 20)
        self.assertEqual(motion.pose.state, "down")
        for step in range(1, 251):  # Five seconds: outside strict gesture limits.
            motion.feed(150 * step / 250, gyro=30)
        motion.hold(150, 20)
        self.assertEqual(motion.pose.state, "up")
        motion.hold(150, 200)
        self.assertTrue(motion.pose.raised)

    def test_each_mounting_learns_its_own_coordinate_system(self):
        normal, rotated = Motion(), Motion(mounted=True)
        normal.calibrate()
        rotated.calibrate()
        self.assertNotEqual(normal.pose.calibration_profile(), rotated.pose.calibration_profile())
        for motion in (normal, rotated):
            motion.hold(0, 20)
            self.assertEqual(motion.pose.state, "down")
            motion.hold(150, 20)
            self.assertTrue(motion.pose.raised)
            motion.hold(90, 20)
            self.assertEqual(motion.pose.state, "unknown")

    def test_noisy_held_up_tolerates_isolated_outliers_but_movement_clears(self):
        motion = Motion()
        motion.calibrate()
        motion.hold(150, 20)
        for index in range(100):
            noisy = index % 20 == 0
            motion.feed(40 if noisy else 150 + 3 * math.sin(index), gyro=220 if noisy else 15)
            self.assertTrue(motion.pose.raised)
        motion.hold(150, 20, gyro=300)
        self.assertEqual(motion.pose.state, "unknown")
        motion.hold(150, 20)
        self.assertTrue(motion.pose.raised)
        motion.hold(150, 20, magnitude=1.8)
        self.assertEqual(motion.pose.state, "unknown")

    def test_shoulder_pose_and_direction_blur_do_not_latch_an_old_up(self):
        motion = Motion()
        motion.calibrate()
        motion.hold(150, 20)
        for index in range(20):
            motion.feed(120 if index % 2 else 175)
        self.assertEqual(motion.pose.state, "unknown")
        motion.hold(150, 20)
        self.assertTrue(motion.pose.raised)
        motion.hold(90, 20)
        self.assertEqual(motion.pose.state, "unknown")
        motion.hold(0, 20)
        self.assertEqual(motion.pose.state, "down")

    def test_close_anchors_still_require_a_clear_margin(self):
        motion = Motion()
        motion.pose.restore_calibration({"version": 1, "down": direction(0), "up": direction(60)})
        motion.hold(28, 20)  # Within 30 degrees of down, but only 4 degrees nearer.
        self.assertEqual(motion.pose.state, "unknown")
        motion.hold(5, 20)
        self.assertEqual(motion.pose.state, "down")

    def test_gap_bad_samples_and_uint32_wrap(self):
        motion = Motion()
        motion.calibrate()
        profile = motion.pose.calibration_profile()
        for overrides in ({"dt": 220}, {"n": 9999}, {"ax": math.nan}, {"t": -1}, {"gz": True}):
            motion.hold(150, 25)
            self.assertTrue(motion.pose.raised)
            motion.feed(150, **overrides)
            self.assertEqual(motion.pose.state, "unknown")
            self.assertEqual(motion.pose.calibration_profile(), profile)
        motion.pose.restore_calibration(profile)
        motion.n = 0xFFFFFFF8
        motion.hold(150, 25)
        self.assertTrue(motion.pose.raised)
        del_sample = dict(t=motion.t + 20, ax=0, ay=0, az=1, gx=0, gy=0)
        motion.pose.feed(del_sample)
        self.assertEqual(motion.pose.last_observation["reason"], "invalid_sample")

    def test_failure_and_cancel_preserve_previously_valid_calibration(self):
        motion = Motion()
        motion.calibrate()
        profile = motion.pose.calibration_profile()
        revision = motion.pose.model_revision
        motion.pose.begin_calibration("up")
        motion.hold(10, 41)
        self.assertEqual(motion.pose.last_observation["kind"], "calibration_rejected")
        self.assertEqual(motion.pose.calibration_profile(), profile)
        self.assertEqual(motion.pose.model_revision, revision)
        motion.pose.begin_calibration("down")
        motion.hold(50, 60, gyro=200)
        self.assertEqual(motion.pose.calibrating, "down")
        motion.pose.cancel_calibration()
        self.assertEqual(motion.pose.calibration_profile(), profile)
        self.assertEqual(motion.pose.model_revision, revision)
        motion.hold(150, 20)
        self.assertTrue(motion.pose.raised)

    def test_restore_validates_atomically_and_restored_up_needs_fresh_window(self):
        motion = Motion()
        motion.calibrate()
        profile = motion.pose.calibration_profile()
        restored = SustainedPoseEstimator()
        restored.restore_calibration(profile)
        self.assertTrue(restored.ready)
        self.assertFalse(restored.raised)
        fresh = Motion(restored)
        fresh.hold(150, 10)
        self.assertFalse(restored.raised)
        fresh.feed(150)
        self.assertTrue(restored.raised)
        bad_profiles = [
            {**profile, "version": True}, {**profile, "version": 2},
            {**profile, "down": [0, 0, 0]}, {**profile, "up": [0, 0, 2]},
            {**profile, "up": [math.nan, 0, 1]}, {**profile, "down": [True, 0, 0]},
            {**profile, "up": direction(30)}, {"version": 1, "up": direction(150)},
        ]
        for bad in bad_profiles:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                restored.restore_calibration(bad)
            self.assertEqual(restored.calibration_profile(), profile)
            self.assertTrue(restored.raised)
        altered = copy.deepcopy(profile)
        restored.restore_calibration(altered)
        altered["up"][0] = 100
        self.assertEqual(restored.calibration_profile(), profile)
        restored.restore_calibration({"version": 1, "down": direction(0), "up": None})
        self.assertFalse(restored.ready)
        self.assertFalse(restored.raised)

    def test_calibration_accepts_jittered_sample_times(self):
        for intervals in ((19, 21), (17, 23, 22)):
            with self.subTest(intervals=intervals):
                motion = Motion()
                for pose, angle in (("down", 0), ("up", 150)):
                    motion.pose.begin_calibration(pose)
                    for index in range(50):
                        motion.feed(angle, dt=intervals[index % len(intervals)])
                    self.assertIsNone(motion.pose.calibrating)
                self.assertTrue(motion.pose.ready)
                motion.hold(150, 15)
                self.assertTrue(motion.pose.raised)

    def test_unstable_calibration_times_out_without_late_relabel_or_data_loss(self):
        motion = Motion()
        motion.calibrate()
        profile = motion.pose.calibration_profile()
        revision = motion.pose.model_revision
        motion.pose.begin_calibration("down")
        motion.hold(90, 501, gyro=200)
        self.assertIsNone(motion.pose.calibrating)
        self.assertEqual(motion.pose.last_observation["kind"], "calibration_failed")
        self.assertEqual(motion.pose.last_observation["reason"], "unstable_timeout")
        self.assertEqual(motion.pose.calibration_profile(), profile)
        self.assertEqual(motion.pose.model_revision, revision)
        motion.hold(90, 60)
        self.assertEqual(motion.pose.calibration_profile(), profile)

    def test_successful_new_down_requires_new_up_but_does_not_require_gestures(self):
        motion = Motion()
        motion.calibrate()
        revision = motion.pose.model_revision
        motion.pose.begin_calibration("down")
        motion.hold(150, 41)  # New mounting down can even coincide with old up.
        self.assertEqual(motion.pose.model_revision, revision + 1)
        self.assertFalse(motion.pose.ready)
        self.assertIsNone(motion.pose.calibration_profile()["up"])
        motion.pose.begin_calibration("up")
        motion.hold(0, 60)
        self.assertTrue(motion.pose.ready)
        self.assertTrue(motion.pose.raised)


if __name__ == "__main__":
    unittest.main()
