import asyncio
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from heart_rate import Band
from raise_hand_runtime import RaiseHandMonitor
from vexo_open import SimTransport
from whoop_band import band_worker, close_band, prepare_display
from whoop_dashboard import DashboardState


class WhoopBandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sim = SimTransport(77, realtime=False, auto_tap=False)
        self.band = await Band.connect(77, transport=self.sim, set_clock=False)
        self.state = DashboardState("WHOOP confirmed")

    async def asyncTearDown(self):
        await self.band.disconnect()

    async def test_shared_state_drives_full_brightness_animation_and_source_loss(self):
        await self.band.set_led("#ff0000")
        await self.band.configure(motion=25, temperature=True, mic_level=True)
        display = await prepare_display(self.band, self.state)
        self.assertEqual((await self.band.get_led()).pattern, "off")
        self.assertIs(display.state, self.state)
        for key, value in self.band.streams.items():
            self.assertEqual(bool(value), key == "events", key)

        for seconds, rgb in ((0, (0, 0, 255)), (3, (0, 255, 255)),
                             (6, (255, 255, 0)), (9, (255, 128, 0)),
                             (12, (255, 0, 0)), (15, (0, 0, 255))):
            if seconds == 0:
                with patch("temperature_animation.time.monotonic", return_value=100):
                    self.assertTrue(self.sim.tap("double-tap"))
            self.state.receive(bytes([0, 80]), now=100 + seconds)
            await display.update(now=100 + seconds)
            led = await self.band.get_led()
            self.assertEqual((led.r, led.g, led.b), rgb)
            self.assertEqual((led.brightness, led.period), (1.0, 800))

        with patch("temperature_animation.time.monotonic", return_value=120):
            self.sim.tap("double-tap")
        self.state.receive(bytes([0, 90]), now=126)
        await display.update(now=126)
        self.assertEqual((await self.band.get_led()).r, 255)  # yellow
        with patch("temperature_animation.time.monotonic", return_value=127):
            self.sim.tap("double-tap")
        await display.update(now=127)
        led = await self.band.get_led()
        self.assertEqual((led.r, led.g, led.b, led.period), (0, 0, 255, 600))
        self.assertEqual(self.state.snapshot(now=127)["bpm"], 90)
        self.state.clear("心率源已断开")
        await display.update(now=128)
        self.assertEqual((await self.band.get_led()).pattern, "off")
        self.assertIsNone(self.state.snapshot(now=128)["bpm"])

    async def test_failed_connection_retries_only_selected_band_and_cleans_up(self):
        self.state.receive(bytes([0, 80]))
        ready = asyncio.Event()
        original_set_led = self.band.set_led

        async def observe_led(*args, **kwargs):
            result = await original_set_led(*args, **kwargs)
            ready.set()
            return result

        self.band.set_led = AsyncMock(side_effect=observe_led)
        self.band.led_off = AsyncMock(wraps=self.band.led_off)
        connect = AsyncMock(side_effect=[RuntimeError("temporarily unavailable"), self.band])
        with patch("whoop_band.Band.connect", connect):
            task = asyncio.create_task(band_worker(self.state, 77, scan_seconds=0.01,
                                                  retry_seconds=0))
            try:
                await asyncio.wait_for(ready.wait(), timeout=1)
                self.assertEqual(self.state.snapshot()["bpm"], 80)
                self.assertEqual(connect.await_count, 2)
                for call in connect.await_args_list:
                    self.assertEqual(call.args, (77,))
                    self.assertFalse(call.kwargs["set_clock"])
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(self.band.connected)
        self.assertGreaterEqual(self.band.led_off.await_count, 2)

    async def test_off_timeout_still_disconnects(self):
        fake = SimpleNamespace(connected=True, led_off=AsyncMock(side_effect=asyncio.Event().wait),
                               disconnect=AsyncMock())
        await close_band(fake, 77, off_timeout=0.01)
        fake.disconnect.assert_awaited_once()


def motion_samples(start, end):
    def pose(degrees, gyro=0):
        angle = math.radians(degrees)
        return dict(ax=math.sin(angle), az=math.cos(angle), gy=gyro)

    return ([pose(start) for _ in range(50)]
            + [pose(start + (end - start) * step / 30, (end - start) / 0.6)
               for step in range(1, 31)]
            + [pose(end) for _ in range(26)])


class WhoopMotionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "hand_events_77.jsonl"
        self.sim = SimTransport(77, realtime=False, auto_tap=False)
        self.band = await Band.connect(77, transport=self.sim, set_clock=False)
        self.state = DashboardState("WHOOP confirmed")
        self.state.receive(bytes([0, 80]))
        self.started = asyncio.Queue()
        self.monitors = []

    async def asyncTearDown(self):
        for monitor in self.monitors:
            monitor.close()
        await self.band.disconnect()
        self.directory.cleanup()

    def monitor_factory(self, band, path, log, **kwargs):
        # Real runtime and classifier, but all hardware and output are synthetic.
        monitor = RaiseHandMonitor(band, path, log, simulated=True, **kwargs)
        original_start = monitor.start

        async def start(*args, **options):
            await original_start(*args, **options)
            self.started.put_nowait(monitor)

        monitor.start = AsyncMock(side_effect=start)
        self.monitors.append(monitor)
        return monitor

    def play(self, start, end):
        samples = motion_samples(start, end)
        self.sim.play_motion(samples)
        self.sim.step(len(samples) * 20)

    def train(self, monitor):
        monitor.recalibrate()
        self.sim.play_motion(dict(ax=0, az=1, gy=0))
        self.sim.step(1000)
        monitor.begin_training()
        for _ in range(3):
            self.play(0, 150)
            self.play(150, 0)
        self.assertTrue(monitor.detector.ready)
        self.assertEqual(self.path.read_text(), "")

    async def test_same_band_receives_motion_after_whoop_loss_and_retains_animation(self):
        led_ready, led_off = asyncio.Event(), asyncio.Event()
        original_set, original_off = self.band.set_led, self.band.led_off

        async def set_led(*args, **kwargs):
            await original_set(*args, **kwargs)
            led_ready.set()

        async def off():
            await original_off()
            led_off.set()

        self.band.set_led = AsyncMock(side_effect=set_led)
        self.band.led_off = AsyncMock(side_effect=off)
        connect = AsyncMock(return_value=self.band)
        state_path = self.path.parent / "shared" / "motion_state_77.json"
        with patch("whoop_band.Band.connect", connect), \
             patch("whoop_band.RaiseHandMonitor", side_effect=self.monitor_factory):
            task = asyncio.create_task(band_worker(
                self.state, 77, raise_hand=True, events_path=self.path,
                interactive=False, state_path=state_path))
            try:
                monitor = await asyncio.wait_for(self.started.get(), timeout=1)
                await asyncio.wait_for(led_ready.wait(), timeout=1)
                self.assertIs(monitor.band, self.band)
                self.assertEqual(monitor.state_publisher.path, state_path)
                self.assertTrue(state_path.exists())
                self.assertEqual(self.band.streams["motion"], 50)
                self.assertTrue(self.band.streams["events"])
                self.train(monitor)
                self.assertTrue(self.sim.tap("double-tap"))
                led_off.clear()
                self.state.clear("心率源已断开")
                await asyncio.wait_for(led_off.wait(), timeout=1)
                received_before = monitor._samples
                with redirect_stdout(io.StringIO()):
                    self.play(0, 145)
                records = [json.loads(line) for line in self.path.read_text().splitlines()]
                self.assertEqual(len(records), 1)
                self.assertEqual((records[0]["type"], records[0]["band_number"]), ("hand_raise", 77))
                self.assertTrue(records[0]["simulated"])
                self.assertGreater(monitor._samples, received_before)
                self.assertTrue(self.band.connected)
                self.assertIsNone(self.state.snapshot()["bpm"])
                self.assertEqual((await self.band.get_led()).pattern, "off")
                connect.assert_awaited_once()
                self.assertEqual(connect.await_args.args, (77,))
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(monitor._closed)
        self.assertIsNone(monitor._input_fd)
        self.assertFalse(self.band.connected)

    async def test_monitor_failure_is_logged_and_cleaned_without_clearing_whoop(self):
        disconnected = asyncio.Event()
        led_waiting, led_cancelled = asyncio.Event(), asyncio.Event()
        original_disconnect = self.band.disconnect

        async def stalled_led(*_args, **_kwargs):
            led_waiting.set()
            try:
                await asyncio.Event().wait()
            finally:
                led_cancelled.set()

        async def disconnect():
            await original_disconnect()
            disconnected.set()

        self.band.set_led = AsyncMock(side_effect=stalled_led)
        self.band.disconnect = AsyncMock(side_effect=disconnect)
        with patch("whoop_band.Band.connect", AsyncMock(return_value=self.band)), \
             patch("whoop_band.RaiseHandMonitor", side_effect=self.monitor_factory), \
             patch("whoop_band.log") as log:
            task = asyncio.create_task(band_worker(
                self.state, 77, retry_seconds=10, raise_hand=True,
                events_path=self.path, interactive=False))
            try:
                monitor = await asyncio.wait_for(self.started.get(), timeout=1)
                await asyncio.wait_for(led_waiting.wait(), timeout=1)
                monitor.failure.set_exception(OSError("event file unavailable"))
                await asyncio.wait_for(disconnected.wait(), timeout=1)
                self.assertTrue(monitor._closed)
                self.assertTrue(led_cancelled.is_set())
                self.assertTrue(any("event file unavailable" in call.args[0]
                                    for call in log.call_args_list))
                self.assertEqual(self.state.snapshot()["bpm"], 80)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_reconnect_restores_only_the_selected_bands_trained_model(self):
        next_sim = SimTransport(77, realtime=False, auto_tap=False)
        next_band = await Band.connect(77, transport=next_sim, set_clock=False)
        connect = AsyncMock(side_effect=[self.band, next_band])
        try:
            with patch("whoop_band.Band.connect", connect), \
                 patch("whoop_band.RaiseHandMonitor", side_effect=self.monitor_factory):
                task = asyncio.create_task(band_worker(
                    self.state, 77, retry_seconds=0, raise_hand=True,
                    events_path=self.path, interactive=False))
                try:
                    first = await asyncio.wait_for(self.started.get(), timeout=1)
                    self.train(first)
                    profile = first.detector.calibration_profile()
                    self.assertIn("77", first._profile_path.name)
                    self.sim.drop_link()
                    restored = await asyncio.wait_for(self.started.get(), timeout=1)
                    self.assertTrue(first._closed)
                    self.assertIsNone(first._input_fd)
                    self.assertTrue(restored.detector.ready)
                    self.assertEqual(restored.detector.calibration_profile(), profile)
                    self.assertEqual(restored.detector.phase, "wait_down")
                    self.assertEqual(next_band.streams["motion"], 50)
                    self.assertEqual(connect.await_count, 2)
                    self.assertTrue(all(call.args == (77,) for call in connect.await_args_list))
                    self.assertEqual(self.state.snapshot()["bpm"], 80)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        finally:
            await next_band.disconnect()


if __name__ == "__main__":
    unittest.main()
