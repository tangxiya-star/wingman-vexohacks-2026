import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from motion_state import MotionStatePublisher, read_reset_generation
from whoop_dashboard import DashboardState, make_server


class MotionHTTPTests(unittest.TestCase):
    def test_two_process_state_files_drive_match_independent_of_heart_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            server = make_server(DashboardState("WHOOP"), port=0, motion_dir=directory)
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={"poll_interval": 0.01}, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            writers = {n: MotionStatePublisher(Path(directory) / f"motion_state_{n}.json", n)
                       for n in (62, 77)}

            def read():
                with urlopen(base + "/api/motion", timeout=2) as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    return json.load(response)

            try:
                self.assertFalse(read()["match"])
                writers[62].publish(connected=True, ready=True, raised=True, phase="wait_down")
                self.assertFalse(read()["match"])
                writers[77].publish(connected=True, ready=True, raised=True, phase="wait_down")
                self.assertTrue(read()["match"])
                with urlopen(base + "/api/state", timeout=2) as response:
                    self.assertIsNone(json.load(response)["bpm"])
                writers[77].publish(connected=True, ready=True, raised=False, phase="wait_down")
                self.assertFalse(read()["match"])
                writers[77].publish(connected=False, ready=True, raised=True, phase="wait_down")
                self.assertFalse(read()["match"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)


class MotionResetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.server = make_server(DashboardState("WHOOP"), port=0, motion_dir=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.writers = {number: MotionStatePublisher(self.root / f"motion_state_{number}.json", number)
                        for number in (62, 77)}
        for number in self.writers:
            self.publish(number)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
        self.directory.cleanup()

    def publish(self, number, generation="initial", triggered=True):
        self.writers[number].publish(connected=True, ready=True, raised=False, phase="latched",
                                     mode="accel-latch", triggered=triggered,
                                     reset_generation=generation, force=True)

    def get(self, path="/api/motion"):
        with urlopen(self.base + path, timeout=2) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            return json.load(response)

    def post(self, *, headers=None, body=b"{}"):
        headers = {"Origin": self.base, "Content-Type": "application/json"} if headers is None else headers
        with urlopen(Request(self.base + "/api/motion/reset", data=body, headers=headers,
                             method="POST"), timeout=2) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            return json.load(response)

    def test_reset_roundtrip_invalidates_both_old_triggers_before_monitor_acknowledgement(self):
        self.assertTrue(self.get()["match"])
        reset = self.post()
        generation = reset["generation"]
        self.assertNotEqual(generation, "initial")
        self.assertEqual(reset["reset_generation"], generation)
        self.assertFalse(reset["match"])
        self.assertTrue(all(band["status"] == "arming" for band in reset["bands"]))
        self.assertFalse(any(band["triggered"] or band["active"] for band in reset["bands"]))
        self.assertFalse(self.get()["match"])
        self.publish(62, generation)
        self.assertFalse(self.get()["match"])
        self.publish(77, generation, triggered=False)
        self.assertEqual(self.get()["bands"][1]["status"], "waiting_motion")
        self.publish(77, generation)
        self.assertTrue(self.get()["match"])
        self.assertIsNone(self.get("/api/state")["bpm"])

    def test_reset_rejects_get_cross_origin_and_non_json_without_mutating_round(self):
        with self.assertRaises(HTTPError) as error:
            self.get("/api/motion/reset")
        self.assertEqual(error.exception.code, 404)
        for headers, body, status in (
            ({"Content-Type": "application/json"}, b"{}", 403),
            ({"Origin": "https://other.example", "Content-Type": "application/json"}, b"{}", 403),
            ({"Origin": self.base, "Sec-Fetch-Site": "cross-site", "Content-Type": "application/json"}, b"{}", 403),
            ({"Origin": "http://other.example", "Host": "other.example", "Content-Type": "application/json"}, b"{}", 403),
            ({"Origin": self.base, "Content-Type": "text/plain"}, b"{}", 415),
            ({"Origin": self.base, "Content-Type": "application/json"}, b"[]", 400),
        ):
            with self.subTest(headers=headers, body=body), self.assertRaises(HTTPError) as error:
                self.post(headers=headers, body=body)
            self.assertEqual(error.exception.code, status)
            self.assertEqual(read_reset_generation(self.root), "initial")
            self.assertTrue(self.get()["match"])

    def test_failed_reset_reports_error_and_preserves_current_round(self):
        with patch("whoop_dashboard.request_motion_reset", side_effect=OSError("disk full")), \
             self.assertRaises(HTTPError) as error:
            self.post()
        self.assertEqual(error.exception.code, 503)
        self.assertEqual(read_reset_generation(self.root), "initial")
        self.assertTrue(self.get()["match"])

    def test_exported_dashboard_contains_reset_controls_without_an_external_redirect(self):
        with urlopen(self.base + "/", timeout=2) as response:
            page = response.read().decode("utf-8")
        for element in ("motion-reset", "motion-feedback", "motion-description", "bpm", "chart"):
            self.assertIn(f'id="{element}"', page)
        self.assertNotIn('http-equiv="refresh"', page)
