import asyncio
import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from band_config import BAND_NUMBER
from heart_rate import Band, HeartRateState, PulseDisplay, enable_temperature_animation
from raise_hand_runtime import RaiseHandMonitor
from temperature_animation import TemperatureAnimation
from tools.replay_raise_hand import replay
from vexo_open.transports.sim import SimTransport


def raise_samples(degrees=150, move_samples=30):
    """Synthetic down -> quick rotation -> held up, at 50 Hz; not wrist data."""
    samples = [dict(ax=0, az=1, gy=0) for _ in range(50)]
    for step in range(1, move_samples + 1):
        angle = math.radians(degrees * step / move_samples)
        samples.append(dict(ax=math.sin(angle), az=math.cos(angle),
                            gy=degrees / (move_samples * 0.02)))
    angle = math.radians(degrees)
    samples.extend(dict(ax=math.sin(angle), az=math.cos(angle), gy=0) for _ in range(26))
    return samples


def lower_samples():
    """Synthetic held up -> quick reverse rotation -> stable down, at 50 Hz."""
    angle = math.radians(150)
    samples = [dict(ax=math.sin(angle), az=math.cos(angle), gy=0) for _ in range(26)]
    for step in range(1, 31):
        angle = math.radians(150 * (1 - step / 30))
        samples.append(dict(ax=math.sin(angle), az=math.cos(angle), gy=-250))
    samples.extend(dict(ax=0, az=1, gy=0) for _ in range(26))
    return samples


class RaiseHandRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "events.jsonl"
        self.logs = []
        self.transport = SimTransport(BAND_NUMBER, auto_tap=False, realtime=False)
        self.band = await Band.connect(BAND_NUMBER, transport=self.transport, set_clock=False)
        self.monitor = RaiseHandMonitor(self.band, self.path, self.logs.append, simulated=True)

    async def asyncTearDown(self):
        self.monitor.close()
        await self.band.disconnect()
        self.directory.cleanup()

    def play(self, samples):
        self.transport.play_motion(samples)
        self.transport.step(len(samples) * 20)

    def play_raise(self):
        # A new movement after training, with different extent and timing.
        self.play(raise_samples(degrees=145, move_samples=32))

    def train(self):
        self.monitor.recalibrate()
        self.transport.play_motion(dict(ax=0, az=1, gy=0))
        self.transport.step(1000)
        self.monitor.begin_training()
        for count in range(1, 4):
            self.play(raise_samples())
            self.play(lower_samples())
            self.assertEqual(self.monitor.detector.training_counts,
                             {"raise": count, "lower": count})
            self.assertEqual(self.path.read_text(), "")
        self.assertTrue(self.monitor.detector.ready)
        self.assertFalse(self.monitor.detector.training)

    def calibrate_poses(self):
        for label, degrees in (("down", 0), ("up", 150)):
            self.monitor.calibrate_pose(label)
            angle = math.radians(degrees)
            self.play([dict(ax=math.sin(angle), az=math.cos(angle), gy=0)] * 60)
            self.assertIsNone(self.monitor.pose.calibrating)
        self.assertTrue(self.monitor.pose.ready)

    async def test_motion_callback_reports_one_event_without_overwriting_heart_rate_led(self):
        state = HeartRateState()
        state.receive(bytes([0, 80]), now=0)
        animation = TemperatureAnimation()
        await enable_temperature_animation(self.band, animation)
        display = PulseDisplay(self.band, state, animation=animation)
        await display.update(now=0)
        before = dict(await self.band.get_led())
        self.band.set_led = AsyncMock(wraps=self.band.set_led)
        await self.monitor.start(interactive=False)
        self.train()

        output = io.StringIO()
        with redirect_stdout(output):
            self.play_raise()

        records = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["type"], "hand_raise")
        self.assertEqual(record["band_number"], BAND_NUMBER)
        self.assertEqual(record["sequence"], 1)
        self.assertTrue(record["simulated"])
        self.assertEqual(record["detected_by"], "mac_imu_detector")
        self.assertEqual(json.loads(output.getvalue()), record)
        self.assertFalse(self.monitor.failure.done())
        self.assertEqual(dict(await self.band.get_led()), before)
        self.band.set_led.assert_not_awaited()
        self.assertTrue(self.band.streams["events"])
        self.assertEqual(self.band.streams["motion"], 50)
        # The same connection still delivers the double-tap animation gesture.
        self.assertIsNone(animation.started_at)
        self.assertTrue(self.transport.tap("double-tap"))
        self.assertIsNotNone(animation.started_at)

    async def test_event_file_write_error_reaches_the_monitor_task(self):
        await self.monitor.start(interactive=False)
        self.train()
        task = asyncio.create_task(self.monitor.run())
        failed_file = Mock()
        failed_file.write.side_effect = OSError("disk full")
        with patch.object(self.monitor.reporter, "_file", failed_file):
            self.play_raise()
            with self.assertRaisesRegex(OSError, "disk full"):
                await asyncio.wait_for(task, timeout=1)
        failed_file.write.assert_called_once()
        self.assertEqual(self.path.read_text(), "")

    async def test_close_stops_callbacks_reporting_and_the_monitor_task(self):
        await self.monitor.start(interactive=False)
        self.train()
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        stored = self.path.read_text()
        samples_before_close = self.monitor._samples
        task = asyncio.create_task(self.monitor.run())
        await asyncio.sleep(0)
        self.monitor.close()
        self.monitor.close()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        self.assertEqual(self.monitor._samples, samples_before_close)
        self.assertEqual(self.path.read_text(), stored)

    async def test_first_stationary_pose_cannot_calibrate_without_explicit_command(self):
        await self.monitor.start(interactive=False)
        self.transport.play_motion(dict(ax=0, az=-1, gy=0))
        self.transport.step(2000)
        self.assertIsNone(self.monitor.detector.baseline)
        self.assertFalse(self.monitor._enabled)
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        self.assertIsNone(self.monitor.detector.baseline)
        self.assertEqual(self.path.read_text(), "")
        self.assertFalse(self.monitor._profile_path.exists())

    async def test_published_current_pose_clears_at_shoulder_height_and_on_close(self):
        state_path = self.path.parent / f"sim_motion_state_{BAND_NUMBER}.json"
        await self.monitor.start(interactive=False)
        state = json.loads(state_path.read_text())
        self.assertTrue(state["connected"])
        self.assertFalse(state["ready"])
        self.assertFalse(state["raised"])
        self.assertFalse((self.path.parent / f"motion_state_{BAND_NUMBER}.json").exists())
        self.calibrate_poses()
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        state = json.loads(state_path.read_text())
        self.assertTrue(state["ready"])
        self.assertTrue(state["raised"])
        self.assertEqual(state["band_number"], BAND_NUMBER)
        self.assertFalse(self.monitor.detector.ready)
        self.assertEqual(self.path.read_text(), "")

        # A stable shoulder pose is enough to release MATCH, without rearming.
        shoulder = []
        for step in range(1, 16):
            radians = math.radians(145 - 55 * step / 15)
            shoulder.append(dict(ax=math.sin(radians), az=math.cos(radians), gy=-55 / .3))
        shoulder += [dict(ax=1, az=0, gy=0)] * 26
        self.play(shoulder)
        state = json.loads(state_path.read_text())
        self.assertFalse(state["raised"])
        self.assertTrue(state["ready"])
        self.assertEqual(state["phase"], "pose_unknown")

        self.play(lower_samples())
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        self.assertTrue(json.loads(state_path.read_text())["raised"])
        self.monitor.close()
        state = json.loads(state_path.read_text())
        self.assertFalse(state["connected"])
        self.assertFalse(state["ready"])
        self.assertFalse(state["raised"])
        self.assertEqual(state["phase"], "disconnected")

    async def test_explicit_state_path_keeps_pose_independent_of_gesture_retraining(self):
        self.monitor.close()
        custom_path = self.path.parent / "custom_state.json"
        self.monitor = RaiseHandMonitor(self.band, self.path, self.logs.append,
                                       simulated=True, state_path=custom_path)
        await self.monitor.start(interactive=False)
        self.train()
        self.calibrate_poses()
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        self.assertTrue(json.loads(custom_path.read_text())["raised"])
        pose_profile = self.monitor.pose.calibration_profile()
        self.monitor.begin_training()
        state = json.loads(custom_path.read_text())
        self.assertTrue(state["raised"])
        self.assertTrue(state["ready"])
        self.assertTrue(self.monitor.detector.training)
        self.monitor.recalibrate()
        state = json.loads(custom_path.read_text())
        self.assertTrue(state["raised"])
        self.assertTrue(state["ready"])
        self.assertEqual(self.monitor.pose.calibration_profile(), pose_profile)

        self.monitor.calibrate_pose("down")
        state = json.loads(custom_path.read_text())
        self.assertFalse(state["raised"])
        self.assertFalse(state["ready"])
        self.assertEqual(state["phase"], "calibrating_down")

    async def test_saved_down_pose_survives_restart_and_requires_actual_down_to_rearm(self):
        await self.monitor.start(interactive=False)
        self.train()
        baseline = self.monitor.detector.baseline
        saved = json.loads(self.monitor._profile_path.read_text())
        self.assertEqual(saved["band_number"], BAND_NUMBER)
        self.assertEqual(saved["profile"]["baseline"], list(baseline))
        self.assertEqual(saved["profile"]["version"], 2)
        self.assertEqual(len(saved["profile"]["templates"]), 6)

        # The old process ends during an unfinished raise. The new connection's
        # sequence begins at zero and must not finish that old candidate.
        self.transport.play_motion(raise_samples()[50:80])
        self.transport.step(600)
        self.assertEqual(self.monitor.detector.phase, "raising")
        self.monitor.close()
        await self.band.disconnect()
        self.transport = SimTransport(BAND_NUMBER, auto_tap=False, realtime=False)
        self.band = await Band.connect(BAND_NUMBER, transport=self.transport, set_clock=False)
        self.monitor = RaiseHandMonitor(self.band, self.path, self.logs.append, simulated=True)
        await self.monitor.start(interactive=False)
        self.assertEqual(self.monitor.detector.baseline, baseline)
        self.assertEqual(self.monitor.detector.phase, "wait_down")
        self.assertTrue(self.monitor.detector.ready)
        self.assertEqual(self.monitor.detector.calibration_profile(), saved["profile"])

        angle = math.radians(150)
        self.transport.play_motion(dict(ax=math.sin(angle), az=math.cos(angle), gy=0))
        self.transport.step(1000)
        self.assertEqual(self.monitor.detector.phase, "wait_down")
        self.assertEqual(self.monitor.detector.baseline, baseline)
        self.assertEqual(self.path.read_text(), "")

        self.transport.play_motion(dict(ax=0, az=1, gy=0))
        self.transport.step(280)
        self.assertEqual(self.monitor.detector.phase, "wait_down")
        self.transport.step(80)
        self.assertEqual(self.monitor.detector.phase, "armed")
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        self.assertEqual(len(self.path.read_text().splitlines()), 1)

    async def test_motion_sequence_restart_discards_an_inflight_candidate(self):
        await self.monitor.start(interactive=False)
        self.train()
        baseline = self.monitor.detector.baseline
        self.transport.play_motion(raise_samples()[50:80])
        self.transport.step(600)
        self.assertEqual(self.monitor.detector.phase, "raising")

        await self.band.configure(motion=False)
        await self.band.configure(motion=50, sensors="both")
        angle = math.radians(150)
        self.transport.play_motion(dict(ax=math.sin(angle), az=math.cos(angle), gy=0))
        self.transport.step(1000)
        self.assertEqual(self.monitor.detector.phase, "wait_down")
        self.assertEqual(self.monitor.detector.baseline, baseline)
        self.assertEqual(self.path.read_text(), "")

    async def test_legacy_down_pose_loads_but_cannot_report_before_training(self):
        profile_path = self.monitor._profile_path
        self.monitor.close()
        profile_path.write_text(json.dumps({
            "band_number": BAND_NUMBER,
            "simulated": True,
            "profile": {"version": 1, "baseline": [0, 0, 1]},
        }))
        self.monitor = RaiseHandMonitor(self.band, self.path, self.logs.append, simulated=True)
        await self.monitor.start(interactive=False)
        self.assertEqual(self.monitor.detector.baseline, (0, 0, 1))
        self.assertFalse(self.monitor.detector.ready)
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        self.assertEqual(self.path.read_text(), "")
        self.assertEqual(self.monitor.detector.training_counts, {"raise": 0, "lower": 0})

    async def test_other_bands_saved_profile_is_not_adopted(self):
        profile_path = self.monitor._profile_path
        self.monitor.close()
        profile_path.write_text(json.dumps({
            "band_number": BAND_NUMBER + 1,
            "simulated": True,
            "profile": {"version": 1, "baseline": [0, 0, 1]},
        }))
        self.monitor = RaiseHandMonitor(self.band, self.path, self.logs.append, simulated=True)
        await self.monitor.start(interactive=False)
        self.transport.play_motion(dict(ax=0, az=1, gy=0))
        self.transport.step(1000)
        self.assertIsNone(self.monitor.detector.baseline)
        self.assertFalse(self.monitor._enabled)
        self.assertTrue(any("未采用校准文件" in line for line in self.logs))

    async def test_record_commands_write_replayable_motion_only_and_stop(self):
        await self.monitor.start(interactive=False)
        state = HeartRateState()
        state.receive(bytes([0, 83]), now=0)
        await PulseDisplay(self.band, state).update(now=0)

        # Exercise the same command dispatch as r/c/x from the terminal.
        self.monitor._input_fd = 123
        try:
            with patch("raise_hand_runtime.os.read", return_value=b"r\nc\n"):
                self.monitor._read_commands()
            trace_path = self.monitor._trace_path
            self.transport.play_motion(dict(ax=0, az=1, gy=0))
            self.transport.step(1000)
            with patch("raise_hand_runtime.os.read", return_value=b"x\n"):
                self.monitor._read_commands()
        finally:
            self.monitor._input_fd = None
        self.assertIsNone(self.monitor._trace)
        rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
        self.assertEqual(rows[:2], [{"kind": "disabled", "simulated": True, "band_number": BAND_NUMBER},
                                   {"kind": "calibrate"}])
        samples = rows[2:]
        self.assertEqual(len(samples), 50)
        expected = {"t", "ax", "ay", "az", "gx", "gy", "gz", "n"}
        self.assertTrue(all(set(sample) == expected for sample in samples))
        self.assertEqual([sample["n"] for sample in samples], list(range(50)))
        stored = trace_path.read_text()
        self.transport.step(1000)
        self.assertEqual(trace_path.read_text(), stored)

        self.monitor.start_recording()
        restored_trace = self.monitor._trace_path
        self.monitor.stop_recording()
        header = json.loads(restored_trace.read_text())
        self.assertEqual(header["kind"], "restore_calibration")
        self.assertTrue(header["simulated"])
        self.assertEqual(header["band_number"], BAND_NUMBER)
        self.assertEqual(header["profile"], self.monitor.detector.calibration_profile())
        self.assertEqual(header["profile"]["version"], 2)

    async def test_recorded_training_and_new_gesture_replay_to_the_same_event(self):
        await self.monitor.start(interactive=False)
        self.monitor.start_recording()
        training_trace = self.monitor._trace_path
        with redirect_stdout(io.StringIO()):
            self.train()
            self.play_raise()
            self.play(lower_samples())
        self.monitor.stop_recording()
        live_events = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual(len(live_events), 1)

        output = io.StringIO()
        with redirect_stdout(output):
            result = replay(training_trace, expect_count=1)
        self.assertEqual(result, 0)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        replayed = [row for row in rows if row["kind"] == "detected_event"]
        self.assertEqual(len(replayed), 1)
        for key, value in replayed[0].items():
            if key not in ("kind", "line"):
                self.assertEqual(value, live_events[0][key])
        training = [row for row in rows if row["kind"] == "segment_diagnostic"
                    and row["observation"]["kind"] == "training_recorded"]
        self.assertEqual(len(training), 6)
        self.assertTrue(all(row["line"] < replayed[0]["line"] for row in training))
        summary = rows[-1]
        self.assertEqual(summary["mode"], "trained")
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["training_examples"], 6)
        self.assertEqual(summary["training_counts"], {"raise": 3, "lower": 3})
        self.assertTrue(summary["ready"])
        self.assertTrue(summary["count_matches"])

        # A later trace starts from its saved v2 templates without retraining.
        self.monitor.start_recording()
        restored_trace = self.monitor._trace_path
        with redirect_stdout(io.StringIO()):
            self.play_raise()
        self.monitor.stop_recording()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(replay(restored_trace, expect_count=1), 0)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["kind"], "restore_calibration")
        self.assertEqual(rows[0]["source_profile_version"], 2)
        self.assertEqual(rows[-1]["training_examples"], 0)
        self.assertEqual(rows[-1]["events"], 1)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(replay(restored_trace, expect_count=0), 1)

    async def test_simulated_calibration_neither_overwrites_nor_initializes_real_profile(self):
        real_path = self.path.parent / "real_events.jsonl"
        real_monitor = RaiseHandMonitor(self.band, real_path, self.logs.append, simulated=False)
        try:
            self.assertNotEqual(self.monitor._profile_path, real_monitor._profile_path)
            await self.monitor.start(interactive=False)
            self.monitor.recalibrate()
            self.transport.play_motion(dict(ax=0, az=1, gy=0))
            self.transport.step(1000)
            simulated_profile = self.monitor._profile_path.read_text()
            self.assertFalse(real_monitor._profile_path.exists())
            real_monitor._profile_path.write_text(simulated_profile)
        finally:
            real_monitor.close()

        # Even a simulated profile copied to the real filename must be rejected.
        real_monitor = RaiseHandMonitor(self.band, real_path, self.logs.append, simulated=False)
        try:
            self.assertIsNone(real_monitor.detector.baseline)
            self.assertFalse(real_monitor._enabled)
        finally:
            real_monitor.close()

    async def test_non_object_profile_requests_recalibration_instead_of_failing_startup(self):
        profile_path = self.monitor._profile_path
        self.monitor.close()
        for malformed in ([], None):
            with self.subTest(profile=malformed):
                profile_path.write_text(json.dumps(malformed))
                self.monitor = RaiseHandMonitor(self.band, self.path, self.logs.append, simulated=True)
                self.assertIsNone(self.monitor.detector.baseline)
                self.assertFalse(self.monitor._enabled)
                self.monitor.close()

    async def test_diagnostic_recording_stops_at_the_sample_limit(self):
        await self.monitor.start(interactive=False)
        self.monitor.start_recording()
        trace_path = self.monitor._trace_path
        self.transport.play_motion(dict(ax=0, az=1, gy=0))
        self.transport.step(122000)
        self.assertIsNone(self.monitor._trace)
        rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
        self.assertEqual(len(rows), 6001)
        self.assertEqual(rows[-1]["n"], 5999)
        self.assertIsNone(self.monitor.detector.baseline)

    async def test_stdin_eof_removes_reader_and_close_remains_safe(self):
        read_fd, write_fd = os.pipe()
        try:
            with patch("raise_hand_runtime.sys.stdin") as stdin:
                stdin.fileno.return_value = read_fd
                await self.monitor.start(interactive=True)
            self.assertEqual(self.monitor._input_fd, read_fd)
            os.close(write_fd)
            write_fd = None
            for _ in range(5):
                await asyncio.sleep(0)
                if self.monitor._input_fd is None:
                    break
            self.assertIsNone(self.monitor._input_fd)
            self.assertFalse(self.monitor.failure.done())
            self.monitor.close()
        finally:
            if write_fd is not None:
                os.close(write_fd)
            os.close(read_fd)

    async def test_band_77_owns_its_model_events_and_replayable_trace_beside_band_62(self):
        await self.monitor.start(interactive=False)
        self.train()
        profile_62_path = self.monitor._profile_path
        profile_62_bytes = profile_62_path.read_bytes()
        events_62_bytes = self.path.read_bytes()
        path_77 = self.path.parent / "events_77.jsonl"
        transport_77 = SimTransport(77, auto_tap=False, realtime=False)
        band_77 = await Band.connect(77, transport=transport_77, set_clock=False)
        monitor_77 = RaiseHandMonitor(band_77, path_77, self.logs.append,
                                     simulated=True, band_number=77)

        def play_77(samples):
            # A different wearing orientation ensures this model is distinct.
            tilt = math.radians(20)
            rotated = []
            for row in samples:
                x, z = row.get("ax", 0), row.get("az", 1)
                rotated.append({**row, "ax": x * math.cos(tilt) + z * math.sin(tilt),
                                "az": z * math.cos(tilt) - x * math.sin(tilt)})
            transport_77.play_motion(rotated)
            transport_77.step(len(rotated) * 20)

        try:
            self.assertEqual(monitor_77.band_number, 77)
            self.assertEqual(monitor_77._profile_path.name, "sim_raise_calibration_77.json")
            self.assertNotEqual(monitor_77._profile_path, profile_62_path)
            self.assertIsNone(monitor_77.detector.baseline)
            self.assertFalse(monitor_77._enabled)
            await monitor_77.start(interactive=False)
            monitor_77.recalibrate()
            play_77([dict(ax=0, az=1, gy=0)] * 50)
            monitor_77.begin_training()
            for _ in range(3):
                play_77(raise_samples())
                play_77(lower_samples())
            self.assertTrue(monitor_77.detector.ready)
            self.assertNotEqual(monitor_77.detector.baseline, self.monitor.detector.baseline)
            saved_77 = json.loads(monitor_77._profile_path.read_text())
            self.assertEqual(saved_77["band_number"], 77)
            self.assertEqual(profile_62_path.read_bytes(), profile_62_bytes)

            monitor_77.start_recording()
            trace_77 = monitor_77._trace_path
            with redirect_stdout(io.StringIO()):
                play_77(raise_samples(degrees=145, move_samples=32))
            monitor_77.stop_recording()
            event = json.loads(path_77.read_text())
            self.assertEqual(event["band_number"], 77)
            self.assertEqual(event["type"], "hand_raise")
            self.assertTrue(trace_77.name.startswith("sim_motion_77_"))
            header = json.loads(trace_77.read_text().splitlines()[0])
            self.assertEqual(header["band_number"], 77)
            self.assertEqual(header["profile"], saved_77["profile"])
            with redirect_stdout(io.StringIO()):
                self.assertEqual(replay(trace_77, expect_count=1), 0)

            monitor_77.close()
            await band_77.disconnect()
            transport_77 = SimTransport(77, auto_tap=False, realtime=False)
            band_77 = await Band.connect(77, transport=transport_77, set_clock=False)
            monitor_77 = RaiseHandMonitor(band_77, path_77, self.logs.append,
                                         simulated=True, band_number=77)
            restored = monitor_77.detector.calibration_profile()
            self.assertEqual(restored["templates"], saved_77["profile"]["templates"])
            self.assertEqual(restored["limit"], saved_77["profile"]["limit"])
            for actual, expected in zip(restored["baseline"], saved_77["profile"]["baseline"]):
                self.assertAlmostEqual(actual, expected)
            self.assertEqual(monitor_77.detector.phase, "wait_down")
            await monitor_77.start(interactive=False)
            with redirect_stdout(io.StringIO()):
                play_77(raise_samples(degrees=145, move_samples=32))
            records = [json.loads(line) for line in path_77.read_text().splitlines()]
            self.assertEqual([record["band_number"] for record in records], [77, 77])
            self.assertEqual(profile_62_path.read_bytes(), profile_62_bytes)
            self.assertEqual(self.path.read_bytes(), events_62_bytes)
            self.assertTrue(any(line.startswith("[手环 77]") for line in self.logs))
        finally:
            monitor_77.close()
            await band_77.disconnect()

    async def test_band_77_rejects_a_band_62_profile_copied_into_its_filename(self):
        profile_path = self.path.parent / "sim_raise_calibration_77.json"
        profile_path.write_text(json.dumps({"band_number": 62, "simulated": True,
                                           "profile": {"version": 1, "baseline": [0, 0, 1]}}))
        transport = SimTransport(77, auto_tap=False, realtime=False)
        band = await Band.connect(77, transport=transport, set_clock=False)
        monitor = RaiseHandMonitor(band, self.path.parent / "events_77.jsonl", self.logs.append,
                                   simulated=True, band_number=77)
        try:
            self.assertIsNone(monitor.detector.baseline)
            self.assertFalse(monitor._enabled)
            self.assertTrue(any("[手环 77] 未采用校准文件" in line for line in self.logs))
        finally:
            monitor.close()
            await band.disconnect()

    async def test_invalid_or_mismatched_band_number_is_rejected_before_creating_files(self):
        untouched = self.path.parent / "must_not_be_created.jsonl"
        for number in (True, 0, 65536, 77):
            with self.subTest(number=number), self.assertRaises(ValueError):
                RaiseHandMonitor(self.band, untouched, self.logs.append, band_number=number)
        self.assertFalse(untouched.exists())


if __name__ == "__main__":
    unittest.main()
