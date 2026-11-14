import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from motion_state import MotionStatePublisher, read_motion_states


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
