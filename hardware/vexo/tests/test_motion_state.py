import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motion_state import (MotionStatePublisher, read_motion_states,
                          read_reset_generation, request_motion_reset)


class MotionStateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def publish(self, number, raised=True, connected=True, ready=True, now=100):
        writer = MotionStatePublisher(self.root / f"motion_state_{number}.json", number)
        with patch("motion_state.time.time", return_value=now):
            writer.publish(connected=connected, ready=ready, raised=raised, phase="wait_down")
        return writer

    def test_match_requires_two_fresh_ready_raised_bands_and_clears_on_release(self):
        self.publish(62)
        self.assertFalse(read_motion_states(self.root, now=100)["match"])
        self.publish(77)
        self.assertTrue(read_motion_states(self.root, now=100)["match"])
        self.publish(77, raised=False, now=100.1)
        self.assertFalse(read_motion_states(self.root, now=100.1)["match"])
        self.assertEqual(read_motion_states(self.root, now=100.1)["bands"][1]["status"], "lowered")

    def test_disconnect_untrained_stale_and_future_data_never_match(self):
        self.publish(62)
        for kwargs, status in (({"connected": False}, "disconnected"),
                               ({"ready": False}, "untrained"),
                               ({"now": 97}, "stale"),
                               ({"now": 102}, "stale")):
            with self.subTest(kwargs=kwargs):
                self.publish(77, **kwargs)
                state = read_motion_states(self.root, now=100)
                self.assertFalse(state["match"])
                self.assertFalse(state["bands"][1]["raised"])
                self.assertEqual(state["bands"][1]["status"], status)

    def test_wrong_identity_and_corrupt_files_are_not_live_states(self):
        self.publish(62)
        self.publish(77)
        path = self.root / "motion_state_77.json"
        for content in ("{", "[]", '{"version":1,"band_number":62}',
                        '{"version":1,"band_number":77,"updated_at":NaN}',
                        '{"version":1,"band_number":77,"updated_at":100,"connected":"yes"}'):
            with self.subTest(content=content):
                path.write_text(content)
                self.assertFalse(read_motion_states(self.root, now=100)["match"])

    def test_unknown_pose_stays_ready_but_cannot_match(self):
        self.publish(62)
        writer = self.publish(77)
        self.assertTrue(read_motion_states(self.root, now=100)["match"])
        with patch("motion_state.time.time", return_value=100.1):
            writer.publish(connected=True, ready=True, raised=False, phase="pose_unknown")
        state = read_motion_states(self.root, now=100.1)
        self.assertFalse(state["match"])
        self.assertTrue(state["bands"][1]["connected"])
        self.assertTrue(state["bands"][1]["ready"])
        self.assertFalse(state["bands"][1]["raised"])
        self.assertEqual(state["bands"][1]["status"], "unknown")

    def test_unchanged_sample_heartbeat_is_throttled_but_release_is_immediate(self):
        path = self.root / "motion_state_77.json"
        writer = MotionStatePublisher(path, 77)
        with patch("motion_state.time.monotonic", side_effect=[10, 10.05, 10.06, 10.3]), \
             patch("motion_state.time.time", side_effect=[100, 100.06, 100.3]):
            writer.publish(connected=True, ready=True, raised=True, phase="wait_down")
            first = path.read_bytes()
            writer.publish(connected=True, ready=True, raised=True, phase="wait_down")
            self.assertEqual(path.read_bytes(), first)
            writer.publish(connected=True, ready=True, raised=False, phase="wait_down")
            self.assertFalse(json.loads(path.read_text())["raised"])
            writer.publish(connected=True, ready=True, raised=False, phase="wait_down")
        self.assertEqual(json.loads(path.read_text())["updated_at"], 100.3)
        self.assertFalse(path.with_suffix(".tmp").exists())

    def publish_latch(self, number, *, triggered=True, ready=True, connected=True,
                      generation="initial", now=100):
        writer = MotionStatePublisher(self.root / f"motion_state_{number}.json", number)
        with patch("motion_state.time.time", return_value=now):
            writer.publish(connected=connected, ready=ready, raised=True, phase="latched",
                           mode="accel-latch", triggered=triggered, reset_generation=generation)
        return writer

    def test_latches_match_without_claiming_a_raised_pose_and_require_fresh_ready_connections(self):
        self.publish_latch(62)
        self.publish_latch(77)
        state = read_motion_states(self.root, now=100)
        self.assertTrue(state["match"])
        self.assertEqual(state["mode"], "accel-latch")
        self.assertTrue(all(band["active"] and band["triggered"] for band in state["bands"]))
        self.assertFalse(any(band["raised"] for band in state["bands"]))
        stored = json.loads((self.root / "motion_state_77.json").read_text())
        self.assertFalse(stored["raised"])
        self.assertTrue(stored["active"])
        for options, status in (({"triggered": False}, "waiting_motion"),
                                ({"ready": False}, "arming"),
                                ({"connected": False}, "disconnected"),
                                ({"now": 97}, "stale")):
            with self.subTest(options=options):
                self.publish_latch(77, **options)
                state = read_motion_states(self.root, now=100)
                self.assertFalse(state["match"])
                self.assertFalse(state["bands"][1]["active"])
                self.assertEqual(state["bands"][1]["status"], status)

    def test_reset_suppresses_old_round_until_both_monitors_acknowledge_and_trigger_again(self):
        self.assertEqual(read_reset_generation(self.root), "initial")
        self.publish_latch(62)
        self.publish_latch(77)
        self.assertTrue(read_motion_states(self.root, now=100)["match"])
        generation = request_motion_reset(self.root)
        self.assertEqual(read_reset_generation(self.root), generation)
        state = read_motion_states(self.root, now=100)
        self.assertFalse(state["match"])
        self.assertEqual(state["reset_generation"], generation)
        self.assertTrue(all(band["status"] == "arming" for band in state["bands"]))
        self.assertFalse(any(band["active"] or band["triggered"] for band in state["bands"]))
        self.publish_latch(62, generation=generation)
        self.assertFalse(read_motion_states(self.root, now=100)["match"])
        self.publish_latch(77, generation=generation, triggered=False)
        self.assertFalse(read_motion_states(self.root, now=100)["match"])
        self.publish_latch(77, generation=generation)
        self.assertTrue(read_motion_states(self.root, now=100)["match"])
        self.assertNotEqual(request_motion_reset(self.root), generation)
        self.assertFalse(read_motion_states(self.root, now=100)["match"])
        self.assertEqual(list(self.root.glob(".motion_reset_*.tmp")), [])

    def test_mixed_modes_and_corrupt_reset_data_cannot_match(self):
        self.publish(62)
        self.publish_latch(77)
        state = read_motion_states(self.root, now=100)
        self.assertTrue(all(band["active"] for band in state["bands"]))
        self.assertEqual(state["mode"], "mixed")
        self.assertFalse(state["match"])
        self.publish_latch(62)
        for invalid in ("{", "[]", '{"version":1,"generation":false}'):
            with self.subTest(invalid=invalid):
                (self.root / "motion_reset.json").write_text(invalid)
                self.assertFalse(read_motion_states(self.root, now=100)["match"])

    def test_legacy_pose_files_remain_compatible_after_a_latch_reset(self):
        for number in (62, 77):
            self.publish(number)
            path = self.root / f"motion_state_{number}.json"
            record = json.loads(path.read_text())
            for key in ("mode", "active", "triggered", "reset_generation"):
                record.pop(key)
            path.write_text(json.dumps(record))
        request_motion_reset(self.root)
        state = read_motion_states(self.root, now=100)
        self.assertTrue(state["match"])
        self.assertEqual(state["mode"], "pose")
