"""SDK integration for the acceleration demo; all motion is synthetic."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock

from heart_rate import Band, HeartRateState, PulseDisplay, enable_temperature_animation
from motion_state import read_reset_generation, request_motion_reset
from raise_hand_runtime import RaiseHandMonitor
from temperature_animation import TemperatureAnimation
from vexo_open.transports.sim import SimTransport


class QuickMotionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.monitors = []
        self.bands = []
        self.logs = []

    async def asyncTearDown(self):
        for monitor in self.monitors:
            monitor.close()
        for band in self.bands:
            if band.connected:
                await band.disconnect()
        self.directory.cleanup()

    async def create(self, number=62):
        transport = SimTransport(number, auto_tap=False, realtime=False)
        band = await Band.connect(number, transport=transport, set_clock=False)
        self.bands.append(band)
        monitor = RaiseHandMonitor(
            band, self.root / f"events_{number}.jsonl", self.logs.append,
            simulated=True, band_number=number, motion_mode="accel-latch")
        self.monitors.append(monitor)
        return transport, band, monitor

    def play(self, transport, monitor, *, magnitude=1.0, milliseconds=600):
        # Use the actual SDK notification callback, not detector.feed directly.
        transport.play_motion(dict(ax=0, ay=0, az=magnitude, gx=0, gy=0, gz=0))
        with redirect_stdout(io.StringIO()):
            transport.step(milliseconds)
        if monitor.failure.done() and not monitor.failure.cancelled():
            monitor.failure.result()

    def trigger(self, transport, monitor):
        self.play(transport, monitor)
        self.play(transport, monitor, magnitude=2.1, milliseconds=200)
        self.assertTrue(monitor.quick_motion.latched)

    def state(self, number):
        return json.loads((self.root / f"sim_motion_state_{number}.json").read_text())

    def events(self, number):
        return [json.loads(line) for line in
                (self.root / f"events_{number}.jsonl").read_text().splitlines()]

    async def test_no_calibration_callback_latches_without_touching_hr_or_animation(self):
        transport, band, monitor = await self.create()
        heart_rate = HeartRateState()
        heart_rate.receive(bytes([0, 80]), now=0)
        animation = TemperatureAnimation()
        await enable_temperature_animation(band, animation)
        display = PulseDisplay(band, heart_rate, animation=animation)
        await display.update(now=0)
        led_before = dict(await band.get_led())
        band.set_led = AsyncMock(wraps=band.set_led)

        await monitor.start(interactive=False)
        self.trigger(transport, monitor)
        records = self.events(62)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "quick_motion")
        self.assertEqual(records[0]["band_number"], 62)
        self.assertTrue(records[0]["simulated"])
        self.assertEqual(records[0]["detected_by"], "mac_acceleration_detector")
        self.assertIsNone(monitor.detector.baseline)
        self.assertFalse(monitor.detector.ready)
        self.assertFalse(monitor.pose.ready)
        self.assertFalse(monitor._profile_path.exists())
        self.assertFalse(monitor._pose_path.exists())
        state = self.state(62)
        self.assertEqual(state["mode"], "accel-latch")
        self.assertTrue(state["ready"])
        self.assertTrue(state["triggered"])
        self.assertTrue(state["active"])
        self.assertFalse(state["raised"])
        self.assertFalse((self.root / "motion_state_62.json").exists())

        # Rest, a new burst, and sustained acceleration cannot repeat the event.
        self.play(transport, monitor)
        self.play(transport, monitor, magnitude=2.1, milliseconds=1200)
        self.assertEqual(self.events(62), records)
        self.assertTrue(self.state(62)["triggered"])
        self.assertEqual(dict(await band.get_led()), led_before)
        band.set_led.assert_not_awaited()
        self.assertTrue(band.streams["events"])
        self.assertEqual(band.streams["motion"], 50)
        self.assertIsNone(animation.started_at)
        self.assertTrue(transport.tap("double-tap"))
        self.assertIsNotNone(animation.started_at)
        await display.update(now=0)
        band.set_led.assert_not_awaited()

    async def test_one_simulation_reset_clears_both_bands_without_resetting_real_mode(self):
        request_motion_reset(self.root)
        real_generation = read_reset_generation(self.root)
        devices = [await self.create(number) for number in (62, 77)]
        for transport, _, monitor in devices:
            await monitor.start(interactive=False)
            self.trigger(transport, monitor)
        self.assertEqual(devices[0][2]._reset_dir, self.root / "sim_motion")
        self.assertEqual(devices[1][2]._reset_dir, devices[0][2]._reset_dir)
        before = read_reset_generation(devices[0][2]._reset_dir)
        request_motion_reset(devices[0][2]._reset_dir)
        after = read_reset_generation(devices[0][2]._reset_dir)
        self.assertNotEqual(after, before)

        for transport, _, monitor in devices:
            # Movement during reset cannot immediately re-trigger: first rest.
            self.play(transport, monitor, magnitude=2.1, milliseconds=200)
            state = self.state(monitor.band_number)
            self.assertFalse(state["triggered"])
            self.assertFalse(state["active"])
            self.assertFalse(state["raised"])
            self.assertEqual(state["reset_generation"], after)
            self.assertEqual(len(self.events(monitor.band_number)), 1)
            self.trigger(transport, monitor)
            records = self.events(monitor.band_number)
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["band_number"] == monitor.band_number
                                and record["simulated"] for record in records))
        self.assertEqual(read_reset_generation(self.root), real_generation)

    async def test_lighter_motion_and_brief_shock_do_not_latch_new_demo_mode(self):
        transport, _, monitor = await self.create()
        await monitor.start(interactive=False)
        self.play(transport, monitor)
        self.play(transport, monitor, magnitude=1.6, milliseconds=300)
        self.assertFalse(monitor.quick_motion.latched)
        self.assertEqual(self.events(62), [])
        self.play(transport, monitor, magnitude=2.1, milliseconds=100)
        self.assertFalse(monitor.quick_motion.latched)
        self.assertEqual(self.events(62), [])

        # The below-threshold sample separates the two shocks: do not combine
        # their durations. These values are synthetic, not a recorded wrist.
        self.play(transport, monitor, milliseconds=40)
        self.play(transport, monitor, magnitude=2.1, milliseconds=200)
        self.assertTrue(monitor.quick_motion.latched)
        events = self.events(62)
        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0]["duration_ms"], 120)

    async def test_reconnect_restores_latch_but_offline_reset_prevents_resurrection(self):
        transport, band, monitor = await self.create()
        await monitor.start(interactive=False)
        self.trigger(transport, monitor)
        monitor.close()
        await band.disconnect()
        state = self.state(62)
        self.assertTrue(state["triggered"])
        self.assertFalse(state["active"])
        self.assertFalse(state["connected"])
        self.assertFalse(state["raised"])

        transport, band, restored = await self.create()
        self.assertTrue(restored.quick_motion.latched)
        await restored.start(interactive=False)
        self.assertTrue(self.state(62)["triggered"])
        self.assertFalse(self.state(62)["active"])
        self.play(transport, restored)
        self.assertTrue(self.state(62)["active"])
        self.play(transport, restored, magnitude=2.1, milliseconds=300)
        self.assertEqual(len(self.events(62)), 1)
        restored.close()
        await band.disconnect()
        request_motion_reset(restored._reset_dir)

        transport, _, reset = await self.create()
        self.assertFalse(reset.quick_motion.latched)
        await reset.start(interactive=False)
        self.assertFalse(self.state(62)["triggered"])
        self.play(transport, reset, magnitude=2.1, milliseconds=300)
        self.assertEqual(len(self.events(62)), 1)
        self.trigger(transport, reset)
        self.assertEqual(len(self.events(62)), 2)

    async def test_corrupt_reset_preserves_latch_until_a_valid_new_round(self):
        transport, band, monitor = await self.create()
        request_motion_reset(monitor._reset_dir)
        reset_path = monitor._reset_dir / "motion_reset.json"
        valid_reset = reset_path.read_bytes()
        generation = read_reset_generation(monitor._reset_dir)
        await monitor.start(interactive=False)
        self.trigger(transport, monitor)
        original_events = self.events(62)

        reset_path.write_text("{broken JSON", encoding="utf-8")
        self.play(transport, monitor, magnitude=2.1, milliseconds=600)
        state = self.state(62)
        self.assertTrue(monitor.quick_motion.latched)
        self.assertTrue(state["triggered"])
        self.assertFalse(state["ready"])
        self.assertFalse(state["active"])
        self.assertEqual(state["reset_generation"], generation)
        self.assertEqual(self.events(62), original_events)

        # Restarting while the reset file is broken must preserve the last
        # known round and latch, rather than turning a read failure into reset.
        monitor.close()
        await band.disconnect()
        transport, _, restored = await self.create()
        await restored.start(interactive=False)
        self.play(transport, restored, magnitude=2.1, milliseconds=300)
        self.assertTrue(restored.quick_motion.latched)
        self.assertTrue(self.state(62)["triggered"])
        self.assertFalse(self.state(62)["active"])
        self.assertEqual(self.state(62)["reset_generation"], generation)
        self.assertEqual(self.events(62), original_events)

        reset_path.write_bytes(valid_reset)
        self.play(transport, restored)
        self.assertTrue(self.state(62)["ready"])
        self.assertTrue(self.state(62)["active"])
        self.assertTrue(self.state(62)["triggered"])
        self.assertEqual(self.events(62), original_events)

        request_motion_reset(restored._reset_dir)
        self.play(transport, restored, magnitude=2.1, milliseconds=200)
        self.assertFalse(restored.quick_motion.latched)
        self.assertFalse(self.state(62)["triggered"])
        self.assertFalse(self.state(62)["active"])
        self.assertNotEqual(self.state(62)["reset_generation"], generation)
        self.assertEqual(self.events(62), original_events)
        self.trigger(transport, restored)
        self.assertEqual(len(self.events(62)), 2)


if __name__ == "__main__":
    unittest.main()
