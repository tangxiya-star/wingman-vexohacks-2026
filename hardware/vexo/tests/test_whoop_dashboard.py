import asyncio
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError
from urllib.request import urlopen

from whoop_dashboard import DashboardState, arguments, make_server, run, source_worker
from motion_state import RUNTIME


class DashboardStateTests(unittest.TestCase):
    def test_stale_and_disconnect_clear_number_and_repeated_packets_recover(self):
        state = DashboardState("Confirmed WHOOP")
        self.assertEqual(state.snapshot(now=0, wall_now=1000)["status"], "waiting")
        state.receive(bytes([0, 80]), now=0, wall_now=1000)
        state.receive(bytes([0, 80]), now=14, wall_now=1014)
        live = state.snapshot(now=15, wall_now=1015)
        self.assertEqual((live["status"], live["bpm"]), ("live", 80))
        self.assertEqual(len(live["history"]), 2)
        stale = state.snapshot(now=29, wall_now=1029)
        self.assertEqual((stale["status"], stale["bpm"]), ("stale", None))
        self.assertEqual(stale["last_received_at"], 1014)
        state.receive(bytes([0, 80]), now=30, wall_now=1030)
        self.assertEqual(state.snapshot(now=30, wall_now=1030)["status"], "live")
        state.clear("心率源已断开")
        self.assertEqual(state.snapshot(now=30.1, wall_now=1030.1)["bpm"], None)
        self.assertEqual(state.snapshot(now=30.1, wall_now=1030.1)["status"], "disconnected")
        state.clear("等待心率源连接")
        self.assertEqual(state.snapshot(now=31, wall_now=1031)["status"], "disconnected")

    def test_invalid_measurement_and_memory_window(self):
        state = DashboardState("WHOOP")
        for tick in range(500):
            state.receive(bytes([0, 80]), now=tick / 10, wall_now=1000 + tick / 10)
        self.assertEqual(len(state.snapshot(now=50, wall_now=1050)["history"]), 180)
        state.receive(bytes([4, 80]), now=50, wall_now=1050)  # contact loss
        self.assertIsNone(state.snapshot(now=50, wall_now=1050)["bpm"])
        self.assertEqual(state.snapshot(now=111, wall_now=1111)["history"], [])


class SourceSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_confirmed_source_does_not_connect_to_nearby_whoop(self):
        other = (SimpleNamespace(address="other", name="WHOOP Nearby"),
                 SimpleNamespace(local_name="WHOOP Nearby"))
        receive = AsyncMock(side_effect=asyncio.CancelledError)
        with patch("whoop_dashboard.scan_sources", AsyncMock(return_value=[other])), \
             patch("whoop_dashboard.receive_heart_rate", receive):
            with self.assertRaises(asyncio.CancelledError):
                await source_worker(DashboardState("Mine"), "confirmed-id", 0.01)
        self.assertIsNone(receive.call_args.args[0])
        self.assertEqual(receive.call_args.kwargs["address"], "confirmed-id")


class DashboardHTTPTests(unittest.TestCase):
    def test_only_whitelisted_static_files_and_no_store_api_are_served(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            static = root / "dashboard"
            static.mkdir()
            (static / "index.html").write_text("<h1>Live</h1>")
            (root / "private.txt").write_text("must not be served")
            server = make_server(DashboardState("WHOOP"), 0, static)
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={"poll_interval": 0.01}, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                self.assertEqual(server.server_address[0], "127.0.0.1")
                with urlopen(base + "/") as response:
                    self.assertIn(b"Live", response.read())
                with urlopen(base + "/api/state?fresh=1") as response:
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
                    self.assertEqual(json.load(response)["status"], "waiting")
                for path in ("/private.txt", "/../private.txt", "/%2e%2e/private.txt", "/heart_rate.py"):
                    with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                        urlopen(base + path)
                    self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=1)


class DashboardRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_heart_rate_keeps_http_and_band_running_without_calling_source(self):
        started = asyncio.Event()
        band_closed = asyncio.Event()
        servers = []

        async def waiting_band(state, number, _scan_seconds, **options):
            self.assertEqual(number, 77)
            self.assertTrue(options["raise_hand"])
            self.assertIsNone(state.snapshot()["bpm"])
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                band_closed.set()

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "index.html").write_text("<h1>Motion dashboard</h1>")

            def capture_server(state, _port):
                server = make_server(state, 0, static_dir=root, motion_dir=root)
                servers.append(server)
                return server

            with patch("sys.argv", ["whoop_dashboard.py", "--source", "confirmed-id",
                                    "--band", "77", "--raise-hand", "--no-heart-rate"]):
                args = arguments()
            self.assertTrue(args.no_heart_rate)
            with patch("whoop_dashboard.make_server", side_effect=capture_server), \
                 patch("whoop_dashboard.source_worker", new_callable=AsyncMock) as receiver, \
                 patch("whoop_dashboard.band_worker", side_effect=waiting_band) as worker:
                task = asyncio.create_task(run(args))
                try:
                    await asyncio.wait_for(started.wait(), timeout=1)
                    receiver.assert_not_called()
                    worker.assert_awaited_once()
                    base = f"http://127.0.0.1:{servers[0].server_port}"

                    def read_http():
                        with urlopen(base + "/", timeout=1) as response:
                            page = response.read()
                        with urlopen(base + "/api/state", timeout=1) as response:
                            heart_rate = json.load(response)
                        with urlopen(base + "/api/motion", timeout=1) as response:
                            motion = json.load(response)
                        return page, heart_rate, motion

                    page, heart_rate, motion = await asyncio.to_thread(read_http)
                    self.assertIn(b"Motion dashboard", page)
                    self.assertIsNone(heart_rate["bpm"])
                    self.assertIn("暂停", heart_rate["message"])
                    self.assertFalse(motion["match"])
                    self.assertFalse(task.done())
                    self.assertFalse(band_closed.is_set())
                    receiver.assert_not_called()
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self.assertTrue(band_closed.is_set())
                self.assertEqual(servers[0].socket.fileno(), -1)
                receiver.assert_not_called()

    async def test_page_and_band_share_one_source_while_band_waits_for_connection(self):
        states = {}
        started = asyncio.Event()
        cancelled = set()
        servers = []

        def capture_server(state, _port):
            actual = make_server(state, 0)
            servers.append(actual)
            return actual

        async def source(state, _address, _scan_seconds):
            states["source"] = state
            state.receive(bytes([0, 86]))
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.add("source")

        async def waiting_band(state, number, _scan_seconds, **options):
            states["band"] = state
            self.assertEqual(number, 77)
            self.assertEqual(options, {"raise_hand": True, "events_path": Path("events77.jsonl"),
                                       "state_path": RUNTIME / "motion_state_77.json"})
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.add("band")

        args = SimpleNamespace(name="WHOOP Mine", source="confirmed-id", port=0,
                               scan_seconds=0.01, band=77, raise_hand=True,
                               events_file=Path("events77.jsonl"))
        with patch("whoop_dashboard.make_server", side_effect=capture_server), \
             patch("whoop_dashboard.source_worker", side_effect=source) as receiver, \
             patch("whoop_dashboard.band_worker", side_effect=waiting_band):
            task = asyncio.create_task(run(args))
            try:
                await asyncio.wait_for(started.wait(), timeout=1)
                self.assertIs(states["source"], states["band"])
                self.assertEqual(receiver.await_count, 1)
                base = f"http://127.0.0.1:{servers[0].server_port}/api/state"

                def read_state():
                    with urlopen(base, timeout=1) as response:
                        return json.load(response)

                live = await asyncio.to_thread(read_state)
                self.assertEqual((live["status"], live["bpm"]), ("live", 86))
                self.assertFalse(task.done())
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(cancelled, {"source", "band"})


class DashboardArgumentTests(unittest.TestCase):
    def parse(self, *extra):
        with patch("sys.argv", ["whoop_dashboard.py", "--source", "confirmed-id", *extra]):
            return arguments()

    def test_motion_defaults_to_the_selected_bands_event_file(self):
        args = self.parse("--band", "77", "--raise-hand")
        self.assertTrue(args.raise_hand)
        self.assertEqual(args.events_file.name, "hand_events_77.jsonl")
        self.assertEqual(args.events_file.parent.name, "runtime")
        self.assertTrue(args.events_file.is_absolute())
        custom = self.parse("--band", "77", "--raise-hand", "--events-file", "custom.jsonl")
        self.assertEqual(custom.events_file, Path("custom.jsonl"))

    def test_motion_requires_an_explicit_band_and_recording_requires_motion(self):
        for extra in (("--raise-hand",), ("--events-file", "custom.jsonl"),
                      ("--band", "77", "--events-file", "custom.jsonl")):
            with self.subTest(args=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.parse(*extra)
        self.assertFalse(self.parse("--band", "77").raise_hand)
        self.assertIsNone(self.parse().events_file)


if __name__ == "__main__":
    unittest.main()
