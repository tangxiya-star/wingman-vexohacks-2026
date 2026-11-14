import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from motion_state import MotionStatePublisher
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
