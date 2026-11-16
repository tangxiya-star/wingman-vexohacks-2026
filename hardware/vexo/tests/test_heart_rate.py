import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from band_config import BAND_NUMBER
import heart_rate
from heart_rate import (
    Band, BandDisconnectedError, BleakError, HeartRateState, PulseDisplay, choose_source, cleanup,
    enable_temperature_animation,
)
from temperature_animation import TemperatureAnimation
from temperature_colour import TemperatureColour
from vexo_open import SimTransport, VexoError


class PulseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.band = await Band.connect(BAND_NUMBER, transport="sim", set_clock=False)
        self.state = HeartRateState()
        self.pulse = PulseDisplay(self.band, self.state)

    async def asyncTearDown(self):
        await self.band.disconnect()

    async def test_band_disconnect_has_a_specific_retryable_error(self):
        await self.band.disconnect()
        with self.assertRaises(BandDisconnectedError):
            await self.pulse.run()

    async def test_real_protocol_changes_red_flash_period(self):
        self.state.receive(bytes([0, 60]), now=0)
        await self.pulse.update(now=0)
        led = await self.band.get_led()
        self.assertEqual((led.r, led.g, led.b, led.pattern, led.period), (255, 0, 0, "blink", 1000))
        self.assertEqual(led.brightness, 1.0)
        self.state.receive(bytes([0, 120]), now=5)
        await self.pulse.update(now=5)
        self.assertEqual((await self.band.get_led()).period, 100)

    async def test_stale_stops_and_same_bpm_resumes(self):
        self.state.receive(bytes([0, 72]), now=0)
        await self.pulse.update(now=0)
        await self.pulse.update(now=15)
        self.assertEqual((await self.band.get_led()).pattern, "off")
        self.state.receive(bytes([0, 72]), now=16)
        await self.pulse.update(now=16)
        self.assertEqual((await self.band.get_led()).pattern, "blink")

    async def test_unchanged_bpm_refreshes_timeout_without_resetting_flash(self):
        self.band.set_led = AsyncMock(wraps=self.band.set_led)
        self.state.receive(bytes([0, 60]), now=0)
        await self.pulse.update(now=0)
        self.state.receive(bytes([0, 60]), now=14)
        await self.pulse.update(now=16)
        self.assertEqual((await self.band.get_led()).pattern, "blink")
        self.assertEqual(self.band.set_led.await_count, 1)

    async def test_contact_loss_invalid_packet_and_disconnect_stop_light(self):
        for invalid in (bytes([4, 72]), bytes([0, 0]), bytes([1, 72])):
            self.state.receive(bytes([0, 72]), now=0)
            await self.pulse.update(now=0)
            self.state.receive(invalid, now=1)
            await self.pulse.update(now=1)
            self.assertEqual((await self.band.get_led()).pattern, "off")
        self.state.receive(bytes([0, 72]), now=2)
        await self.pulse.update(now=2)
        self.state.clear("心率源已断开")
        await self.pulse.update(now=2.1)
        self.assertEqual((await self.band.get_led()).pattern, "off")


class PulseRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sim = SimTransport(BAND_NUMBER, auto_tap=False, realtime=False)
        self.band = await Band.connect(BAND_NUMBER, transport=sim, set_clock=False)
        self.state = HeartRateState()
        self.state.receive(bytes([0, 72]), now=0)
        self.pulse = PulseDisplay(self.band, self.state)

    async def asyncTearDown(self):
        await self.band.disconnect()

    async def test_applied_write_with_lost_ack_rewrites_old_cached_setting(self):
        self.state.receive(bytes([0, 60]), now=0)
        self.assertTrue(await self.pulse.update_with_retry(now=0))
        original_set_led = self.band.set_led

        async def apply_then_lose_ack(*args, **kwargs):
            await original_set_led(*args, **kwargs)
            raise VexoError("timeout", "No response to LED_SET")

        self.band.set_led = AsyncMock(side_effect=apply_then_lose_ack)
        self.state.receive(bytes([0, 120]), now=1)
        self.assertFalse(await self.pulse.update_with_retry(now=1))
        self.assertEqual((await self.band.get_led()).period, 100)

        # The desired state now equals the last acknowledged cache entry, but
        # the physical device changed during the command whose reply was lost.
        self.band.set_led = AsyncMock(wraps=original_set_led)
        self.state.receive(bytes([0, 60]), now=2)
        self.assertTrue(await self.pulse.update_with_retry(now=2))
        self.band.set_led.assert_awaited_once()
        self.assertEqual((await self.band.get_led()).period, 1000)

    async def test_uncertain_applied_write_is_turned_off_when_heart_rate_becomes_invalid(self):
        original_set_led = self.band.set_led

        async def apply_then_lose_ack(*args, **kwargs):
            await original_set_led(*args, **kwargs)
            raise VexoError("timeout", "No response to LED_SET")

        self.band.set_led = AsyncMock(side_effect=apply_then_lose_ack)
        self.assertFalse(await self.pulse.update_with_retry(now=0))
        self.assertEqual((await self.band.get_led()).pattern, "blink")
        self.state.clear("心率源已断开")
        self.assertTrue(await self.pulse.update_with_retry(now=1))
        self.assertEqual((await self.band.get_led()).pattern, "off")

    async def test_recovery_uses_current_animation_and_resets_timeout_budget(self):
        animation = TemperatureAnimation()
        animation.restart(now=0)
        pulse = PulseDisplay(self.band, self.state, animation=animation)
        original_set_led = self.band.set_led
        attempts = 0

        async def fail_twice_then_apply(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts % 3:
                raise VexoError("timeout", "No response to LED_SET")
            return await original_set_led(*args, **kwargs)

        self.band.set_led = AsyncMock(side_effect=fail_twice_then_apply)
        self.assertFalse(await pulse.update_with_retry(now=0))
        self.assertFalse(await pulse.update_with_retry(now=1))
        self.assertTrue(await pulse.update_with_retry(now=3))
        led = await self.band.get_led()
        self.assertEqual((led.r, led.g, led.b, led.period), (0, 255, 255, 900))

        # A successful recovery grants a fresh consecutive-timeout budget.
        self.state.receive(bytes([0, 76]), now=4)
        self.assertFalse(await pulse.update_with_retry(now=4))
        self.assertFalse(await pulse.update_with_retry(now=5))
        self.assertTrue(await pulse.update_with_retry(now=6))
        led = await self.band.get_led()
        self.assertEqual((led.r, led.g, led.b, led.period), (255, 255, 0, 800))

    async def test_third_consecutive_timeout_is_raised(self):
        error = VexoError("timeout", "No response to LED_SET")
        self.band.set_led = AsyncMock(side_effect=error)
        self.assertFalse(await self.pulse.update_with_retry(now=0))
        self.assertFalse(await self.pulse.update_with_retry(now=1))
        with self.assertRaises(VexoError) as raised:
            await self.pulse.update_with_retry(now=2)
        self.assertIs(raised.exception, error)
        self.assertEqual(self.band.set_led.await_count, 3)

    async def test_run_survives_one_timeout_and_continues_displaying(self):
        self.state.receive(bytes([0, 72]))
        original_set_led = self.band.set_led
        written = asyncio.Event()
        attempts = 0

        async def fail_once_then_apply(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise VexoError("timeout", "No response to LED_SET")
            result = await original_set_led(*args, **kwargs)
            written.set()
            return result

        self.band.set_led = AsyncMock(side_effect=fail_once_then_apply)
        task = asyncio.create_task(self.pulse.run())
        try:
            await asyncio.wait_for(written.wait(), timeout=1)
            self.assertFalse(task.done())
            self.assertEqual((await self.band.get_led()).period, 900)
            self.assertEqual(attempts, 2)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_nonretryable_protocol_errors_propagate_immediately(self):
        for code, message in (
            ("bad-arg", "Invalid LED setting"),
            ("denied", "LED command denied"),
            ("not-connected", "Band disconnected"),
            ("timeout", "The band answered LED_SET with the wrong response length"),
        ):
            with self.subTest(code=code, message=message):
                error = VexoError(code, message)
                self.band.set_led = AsyncMock(side_effect=error)
                with self.assertRaises(VexoError) as raised:
                    await self.pulse.update_with_retry(now=0)
                self.assertIs(raised.exception, error)
                self.band.set_led.assert_awaited_once()

    async def test_timeout_on_disconnected_band_is_not_retried(self):
        await self.band.disconnect()
        error = VexoError("timeout", "No response to LED_SET")
        self.band.set_led = AsyncMock(side_effect=error)
        with self.assertRaises(VexoError) as raised:
            await self.pulse.update_with_retry(now=0)
        self.assertIs(raised.exception, error)
        self.band.set_led.assert_awaited_once()

    async def test_readback_mismatch_is_not_swallowed(self):
        self.band.get_led = AsyncMock(return_value=SimpleNamespace(
            r=0, g=255, b=0, pattern="blink", period=900, brightness=1.0,
        ))
        with self.assertRaises(RuntimeError):
            await self.pulse.update_with_retry(now=0)
        self.band.get_led.assert_awaited_once()


class CombinedPulseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.band = await Band.connect(BAND_NUMBER, transport="sim", set_clock=False)
        self.state = HeartRateState()
        self.temperature = TemperatureColour()
        self.pulse = PulseDisplay(self.band, self.state, temperature=self.temperature)

    async def asyncTearDown(self):
        await self.band.disconnect()

    async def test_warmer_colour_keeps_heart_rate_period_and_brightness(self):
        self.state.receive(bytes([0, 72]), now=0)
        self.temperature.receive(30.0, now=0)
        await self.pulse.update(now=0)
        cool = await self.band.get_led()

        self.temperature.receive(31.0, now=1)
        await self.pulse.update(now=1)
        warm = await self.band.get_led()

        self.assertNotEqual((cool.r, cool.g, cool.b), (warm.r, warm.g, warm.b))
        self.assertGreater(warm.r, cool.r)
        self.assertLess(warm.b, cool.b)
        self.assertEqual((cool.pattern, cool.period, cool.brightness), ("blink", 900, 1.0))
        self.assertEqual((warm.pattern, warm.period, warm.brightness), ("blink", 900, 1.0))

    async def test_stale_or_invalid_temperature_stops_and_new_sample_resumes(self):
        self.state.receive(bytes([0, 72]), now=0)
        self.temperature.receive(30.0, now=0)
        await self.pulse.update(now=0)
        self.assertEqual((await self.band.get_led()).pattern, "blink")

        self.state.receive(bytes([0, 72]), now=5)
        await self.pulse.update(now=5)
        self.assertEqual((await self.band.get_led()).pattern, "off")

        self.temperature.receive(30.0, now=6)
        await self.pulse.update(now=6)
        self.assertEqual((await self.band.get_led()).pattern, "blink")

        self.temperature.receive(float("nan"), now=7)
        await self.pulse.update(now=7)
        self.assertEqual((await self.band.get_led()).pattern, "off")

        self.temperature.receive(30.5, now=8)
        await self.pulse.update(now=8)
        led = await self.band.get_led()
        self.assertEqual((led.pattern, led.period, led.brightness), ("blink", 900, 1.0))
        self.assertEqual(self.temperature.baseline, 30.0)

    async def test_fresh_temperature_cannot_keep_stale_heart_rate_flashing(self):
        self.state.receive(bytes([0, 72]), now=0)
        self.temperature.receive(30.0, now=0)
        await self.pulse.update(now=0)

        self.temperature.receive(30.25, now=15)
        await self.pulse.update(now=15)
        self.assertEqual((await self.band.get_led()).pattern, "off")

        self.state.receive(bytes([0, 72]), now=16)
        await self.pulse.update(now=16)
        self.assertEqual((await self.band.get_led()).pattern, "blink")

    async def test_invalid_temperature_during_led_write_stops_next_update_and_recovers(self):
        self.state.receive(bytes([0, 72]), now=0)
        self.temperature.receive(30.0, now=0)
        original_set_led = self.band.set_led

        async def write_then_receive_invalid_temperature(*args, **kwargs):
            result = await original_set_led(*args, **kwargs)
            self.temperature.receive(float("nan"), now=0.1)
            return result

        self.band.set_led = AsyncMock(side_effect=write_then_receive_invalid_temperature)
        await self.pulse.update(now=0)
        self.assertIsNone(self.temperature.celsius)
        self.assertEqual((await self.band.get_led()).pattern, "blink")
        self.band.set_led.assert_awaited_once()

        await self.pulse.update(now=0.2)
        self.assertEqual((await self.band.get_led()).pattern, "off")

        self.band.set_led = original_set_led
        self.temperature.receive(30.5, now=1)
        await self.pulse.update(now=1)
        led = await self.band.get_led()
        self.assertEqual((led.pattern, led.period, led.brightness), ("blink", 900, 1.0))
        self.assertEqual((led.r, led.g, led.b), (255, 210, 63))

    async def test_identical_inputs_refresh_both_timeouts_without_rewriting_led(self):
        self.band.set_led = AsyncMock(wraps=self.band.set_led)
        for now in range(0, 18, 2):
            self.state.receive(bytes([0, 72]), now=now)
            self.temperature.receive(30.0, now=now)
            await self.pulse.update(now=now)

        led = await self.band.get_led()
        self.assertEqual((led.pattern, led.period, led.brightness), ("blink", 900, 1.0))
        self.band.set_led.assert_awaited_once()


class AnimatedPulseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sim = SimTransport(BAND_NUMBER, auto_tap=False, realtime=False)
        self.band = await Band.connect(BAND_NUMBER, transport=self.sim, set_clock=False)
        # Exercise a persisted event mask that previously disabled double taps.
        await self.band.set_events(kinds=["tap"])
        self.animation = TemperatureAnimation()
        await enable_temperature_animation(self.band, self.animation)
        self.state = HeartRateState()
        self.pulse = PulseDisplay(self.band, self.state, animation=self.animation)

    async def asyncTearDown(self):
        await self.band.disconnect()

    def double_tap(self, now):
        # The real SDK event decoder/dispatcher invokes the subscribed callback.
        with patch("temperature_animation.time.monotonic", return_value=now):
            self.assertTrue(self.sim.tap("double-tap"))
        self.assertEqual(self.animation.started_at, now)

    async def assert_led(self, rgb, period=900):
        led = await self.band.get_led()
        self.assertEqual((led.r, led.g, led.b), rgb)
        self.assertEqual((led.pattern, led.period, led.brightness), ("blink", period, 1.0))

    async def test_idle_blue_follows_bpm_and_single_tap_does_not_start_animation(self):
        self.assertCountEqual((await self.band.get_events()).kinds, ["tap", "double-tap"])
        self.assertTrue(self.band.streams["events"])
        self.state.receive(bytes([0, 72]), now=0)
        await self.pulse.update(now=0)
        await self.assert_led((0, 0, 255))

        self.assertTrue(self.sim.tap("tap"))
        self.assertIsNone(self.animation.started_at)
        self.state.receive(bytes([0, 120]), now=7)
        await self.pulse.update(now=7)
        await self.assert_led((0, 0, 255), period=100)
        self.assertFalse(self.animation.is_active)

    async def test_sdk_double_tap_plays_each_colour_for_three_seconds_then_returns_blue(self):
        self.double_tap(now=100)
        checkpoints = (
            (0, (0, 0, 255)),
            (2.999, (0, 0, 255)),
            (3, (0, 255, 255)),
            (6, (255, 255, 0)),
            (9, (255, 128, 0)),
            (12, (255, 0, 0)),
            (14.999, (255, 0, 0)),
            (15, (0, 0, 255)),
            (18, (0, 0, 255)),
        )
        for elapsed, rgb in checkpoints:
            with self.subTest(elapsed=elapsed):
                self.state.receive(bytes([0, 72]), now=100 + elapsed)
                await self.pulse.update(now=100 + elapsed)
                await self.assert_led(rgb)
                self.assertEqual(self.animation.is_active, elapsed < 15)

    async def test_second_sdk_double_tap_restarts_full_animation_from_blue(self):
        colours = ((0, 0, 255), (0, 255, 255), (255, 255, 0), (255, 128, 0), (255, 0, 0))
        for index, rgb in enumerate(colours):
            with self.subTest(restarting_from=rgb):
                started_at = 100 * (index + 1)
                self.double_tap(now=started_at)
                restart_at = started_at + 3 * index + 1
                self.state.receive(bytes([0, 72]), now=restart_at)
                await self.pulse.update(now=restart_at)
                await self.assert_led(rgb)

                self.double_tap(now=restart_at)
                checkpoints = tuple((3 * step, colour) for step, colour in enumerate(colours))
                checkpoints += ((14.999, (255, 0, 0)), (15, (0, 0, 255)))
                for elapsed, expected in checkpoints:
                    now = restart_at + elapsed
                    self.state.receive(bytes([0, 72]), now=now)
                    await self.pulse.update(now=now)
                    await self.assert_led(expected)
                    self.assertEqual(self.animation.is_active, elapsed < 15)

    async def test_double_taps_cannot_override_missing_invalid_or_stale_heart_rate(self):
        self.double_tap(now=0)
        await self.pulse.update(now=0)
        self.assertEqual((await self.band.get_led()).pattern, "off")

        self.state.receive(bytes([0, 72]), now=0)
        await self.pulse.update(now=0)
        await self.assert_led((0, 0, 255))
        self.state.receive(bytes([0, 0]), now=1)
        self.double_tap(now=1)
        await self.pulse.update(now=1)
        self.assertEqual((await self.band.get_led()).pattern, "off")

        self.state.receive(bytes([0, 72]), now=2)
        await self.pulse.update(now=2)
        await self.assert_led((0, 0, 255))
        self.double_tap(now=17)
        await self.pulse.update(now=17)
        self.assertEqual((await self.band.get_led()).pattern, "off")

        self.state.receive(bytes([0, 72]), now=18)
        await self.pulse.update(now=18)
        await self.assert_led((0, 0, 255))

    async def test_bpm_changes_within_one_display_band_do_not_rewrite_led(self):
        self.band.set_led = AsyncMock(wraps=self.band.set_led)
        for now, bpm in ((0, 71), (14, 72), (28, 75), (42, 71)):
            self.state.receive(bytes([0, bpm]), now=now)
            await self.pulse.update(now=now)
            await self.assert_led((0, 0, 255))
        self.band.set_led.assert_awaited_once()

        self.state.receive(bytes([0, 76]), now=43)
        await self.pulse.update(now=43)
        await self.assert_led((0, 0, 255), period=800)
        self.assertEqual(self.band.set_led.await_count, 2)


class RunStatePathTests(unittest.IsolatedAsyncioTestCase):
    async def test_custom_event_logs_keep_real_and_simulated_status_in_shared_runtime(self):
        original_start = heart_rate.RaiseHandMonitor.start

        async def noninteractive_start(monitor):
            await original_start(monitor, interactive=False)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shared = root / "shared_runtime"
            for simulated in (False, True):
                with self.subTest(simulated=simulated):
                    events = root / "custom_logs" / f"events_{simulated}.jsonl"
                    cli = (["--sim"] if simulated else ["--demo-bpm", "80"])
                    cli += ["--raise-hand", "--events-file", str(events), "--seconds", "0.01"]
                    with patch("sys.argv", ["heart_rate.py", *cli]):
                        args = heart_rate.arguments()
                    band = await Band.connect(BAND_NUMBER, transport=SimTransport(
                        BAND_NUMBER, auto_tap=False, realtime=False), set_clock=False)
                    try:
                        with patch("heart_rate.RUNTIME", shared), \
                             patch("heart_rate.Band.connect", AsyncMock(return_value=band)), \
                             patch("heart_rate.RaiseHandMonitor.start", noninteractive_start):
                            self.assertEqual(await heart_rate.run(args), 0)
                        filename = f"{'sim_' if simulated else ''}motion_state_{BAND_NUMBER}.json"
                        state = json.loads((shared / filename).read_text())
                        self.assertEqual(state["band_number"], BAND_NUMBER)
                        self.assertFalse(state["connected"])
                        self.assertTrue(events.exists())
                        self.assertFalse((events.parent / filename).exists())
                    finally:
                        await band.disconnect()
            self.assertEqual(len(list(shared.glob("*motion_state_*.json"))), 2)


class SelectionTests(unittest.TestCase):
    def device(self, name, address):
        return (SimpleNamespace(name=name, address=address), SimpleNamespace(local_name=name))

    def test_never_chooses_an_arbitrary_heart_rate_source(self):
        with self.assertRaises(RuntimeError):
            choose_source([self.device("Other Sensor", "other")])

    def test_single_heartcast_still_requires_explicit_identity(self):
        sources = [self.device("HeartCast", "unconfirmed")]
        with self.assertRaises(RuntimeError):
            choose_source(sources)
        self.assertEqual(choose_source(sources, "unconfirmed")[0].address, "unconfirmed")

    def test_multiple_heartcast_sources_require_explicit_identity(self):
        sources = [self.device("HeartCast", "mine"), self.device("HeartCast-2", "other")]
        with self.assertRaises(RuntimeError):
            choose_source(sources)
        self.assertEqual(choose_source(sources, "mine")[0].address, "mine")

    def test_reconnect_cannot_switch_to_new_device(self):
        with self.assertRaises(RuntimeError):
            choose_source([self.device("HeartCast", "other")], "mine")


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    def args(self, **changes):
        return SimpleNamespace(**(dict(reconnect=True, scan=False, sim=False, usb=False,
                                      seconds=None, source="confirmed-id") | changes))

    async def test_disconnect_retries_only_after_previous_run_cleanup_and_delay(self):
        order = []

        async def run_once(args):
            self.assertEqual(args.source, "confirmed-id")
            if not order:
                try:
                    order.append("first")
                    raise BandDisconnectedError("link lost")
                finally:
                    order.append("cleanup")
            order.append("second")
            return 0

        async def delay(seconds):
            self.assertEqual(seconds, 3)
            self.assertEqual(order, ["first", "cleanup"])
            order.append("delay")

        with patch("heart_rate.run", side_effect=run_once) as run, \
             patch("heart_rate.asyncio.sleep", side_effect=delay):
            self.assertEqual(await heart_rate.run_with_reconnect(self.args()), 0)
        self.assertEqual(run.await_count, 2)
        self.assertEqual(order, ["first", "cleanup", "delay", "second"])

    async def test_known_link_errors_retry_but_configuration_disk_and_cancellation_do_not(self):
        retryable = [VexoError("not-connected", "lost"), VexoError("not-found-nearby", "nearby"),
                     VexoError("timeout", "No response to LED_SET"), BleakError("link lost"), TimeoutError()]
        for error in retryable:
            with self.subTest(error=error), patch("heart_rate.run", AsyncMock(side_effect=[error, 0])) as run, \
                 patch("heart_rate.asyncio.sleep", AsyncMock()) as delay:
                self.assertEqual(await heart_rate.run_with_reconnect(self.args()), 0)
                self.assertEqual(run.await_count, 2)
                delay.assert_awaited_once_with(3)

        fatal = [VexoError("wrong-band", "wrong device"), VexoError("bad-arg", "bad setting"),
                 VexoError("timeout", "The band answered LED_SET with the wrong response length"),
                 OSError("disk full"), RuntimeError("readback mismatch"), ValueError("configuration"),
                 asyncio.CancelledError()]
        for error in fatal:
            with self.subTest(error=error), patch("heart_rate.run", AsyncMock(side_effect=error)) as run, \
                 patch("heart_rate.asyncio.sleep", AsyncMock()) as delay:
                with self.assertRaises(type(error)):
                    await heart_rate.run_with_reconnect(self.args())
                run.assert_awaited_once()
                delay.assert_not_awaited()

    async def test_finite_scanning_simulated_usb_and_non_opt_in_runs_do_not_retry(self):
        for changes in ({"seconds": 1}, {"scan": True}, {"sim": True}, {"usb": True}, {"reconnect": False}):
            with self.subTest(changes=changes), \
                 patch("heart_rate.run", AsyncMock(side_effect=BandDisconnectedError("lost"))) as run, \
                 patch("heart_rate.asyncio.sleep", AsyncMock()) as delay:
                with self.assertRaises(BandDisconnectedError):
                    await heart_rate.run_with_reconnect(self.args(**changes))
                run.assert_awaited_once()
                delay.assert_not_awaited()

    async def test_cancel_during_reconnect_delay_never_starts_another_session(self):
        with patch("heart_rate.run", AsyncMock(side_effect=BandDisconnectedError("lost"))) as run, \
             patch("heart_rate.asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await heart_rate.run_with_reconnect(self.args())
            run.assert_awaited_once()


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_led_write_failure_still_disconnects_band(self):
        band = SimpleNamespace(
            connected=True,
            led_off=AsyncMock(side_effect=BleakError("BLE write failed")),
            disconnect=AsyncMock(),
        )
        await cleanup(band, [])
        band.led_off.assert_awaited_once()
        band.disconnect.assert_awaited_once()

    async def test_slow_source_cleanup_does_not_delay_band_shutdown(self):
        source_started = asyncio.Event()
        display_started = asyncio.Event()
        release_source = asyncio.Event()
        source_cleanup_started = asyncio.Event()
        order = []

        async def source():
            source_started.set()
            try:
                await asyncio.Future()
            finally:
                source_cleanup_started.set()
                await release_source.wait()
                order.append("source_finished")

        async def display():
            display_started.set()
            try:
                await asyncio.Future()
            finally:
                order.append("display_stopped")

        async def led_off():
            self.assertTrue(source_cleanup_started.is_set())
            self.assertIn("display_stopped", order)
            self.assertNotIn("source_finished", order)
            order.append("led_off")

        async def disconnect():
            order.append("band_disconnected")
            release_source.set()

        band = SimpleNamespace(
            connected=True,
            led_off=AsyncMock(side_effect=led_off),
            disconnect=AsyncMock(side_effect=disconnect),
        )
        tasks = [asyncio.create_task(source()), asyncio.create_task(display())]
        try:
            await asyncio.gather(source_started.wait(), display_started.wait())
            # The source cannot finish until disconnect releases it. Waiting for
            # the source before shutting down the band would time out here.
            await asyncio.wait_for(cleanup(band, tasks), timeout=1)
            self.assertEqual(order, ["display_stopped", "led_off", "band_disconnected", "source_finished"])
            band.led_off.assert_awaited_once()
            band.disconnect.assert_awaited_once()
            self.assertTrue(all(task.done() for task in tasks))
        finally:
            release_source.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
