"""Offline round, cancellation, and RSSI checks. No Bluetooth or HTTP requests."""

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from haptic_demo import Demo, Proximity


class FakeWhoop:
    def __init__(self):
        self.ready = True
        self.pulses = []
        self.stops = 0
        self.stop_gate = None
        self.stop_entered = asyncio.Event()
        self.buzz_result = "buzz_completed"

    def snapshot(self):
        return dict(connected=self.ready, ready=self.ready, busy=False)

    async def buzz(self, pattern="notification"):
        self.pulses.append(pattern)
        return {"result": self.buzz_result, "stop_confirmed": True, "duration": 0}

    async def stop(self):
        self.stops += 1
        self.stop_entered.set()
        if self.stop_gate is not None:
            await self.stop_gate.wait()
        return {"result": "stopped", "stop_confirmed": True}

    async def connect(self):
        self.ready = True


class FakeWatch:
    def __init__(self):
        self.calls = []
        self.opened = set()
        self.revoked = set()

    async def status(self):
        return dict(watch_connected=True, watch_ready=True, watch_can_alert=True)

    async def open_scope(self, scope):
        if scope in self.revoked:
            return {"error": "revoked"}
        self.opened.add(scope)
        return {"scope_status": "opened", "scope": scope}

    async def cancel_scope(self, scope):
        self.revoked.add(scope)
        self.opened.discard(scope)
        return {"scope_status": "cancelled", "scope": scope}

    async def buzz(self, kind, scope=None):
        if scope is not None and (scope not in self.opened or scope in self.revoked):
            return {"error": "scope rejected"}
        self.calls.append(kind)
        return {"result": "play_called"}


class DelayedWatch(FakeWatch):
    """Model an uncancellable urllib worker arriving after stop's HTTP request."""

    def __init__(self):
        super().__init__()
        self.thread_started = threading.Event()
        self.release_thread = threading.Event()
        self.thread_finished = threading.Event()
        self.rejected = False
        self.attempted_scope = None

    async def buzz(self, kind, scope=None):
        def request():
            self.attempted_scope = scope
            self.thread_started.set()
            self.release_thread.wait(2)
            try:
                if scope is not None and (scope not in self.opened or scope in self.revoked):
                    self.rejected = True
                    return {"error": "scope rejected"}
                self.calls.append(kind)
                return {"result": "play_called"}
            finally:
                self.thread_finished.set()
        return await asyncio.to_thread(request)


class RoundTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.whoop = FakeWhoop()
        self.watch = FakeWatch()
        self.demo = Demo(self.whoop, self.watch, directory=self.directory)
        self.demo.watch_state = await self.watch.status()
        self.tasks = []
        self.publish("initial", triggered=True)

    async def asyncTearDown(self):
        self.whoop.stop_gate = None
        if self.demo.round_task and not self.demo.round_task.done():
            await self.demo.stop()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.temporary.cleanup()

    def publish(self, generation, *, triggered=False, age=0):
        stamp = time.time() - age
        bands = []
        for number in (62, 77):
            record = dict(version=1, band_number=number, connected=True, ready=True,
                          raised=False, phase="latched" if triggered else "armed",
                          updated_at=stamp, mode="accel-latch", triggered=triggered,
                          active=triggered, reset_generation=generation)
            (self.directory / f"motion_state_{number}.json").write_text(json.dumps(record))
            bands.append(record)
        self.demo.motion = dict(mode="accel-latch", reset_generation=generation,
                                bands=bands, match=triggered)

    async def wait_for(self, predicate, timeout=1):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail(f"condition timed out; phase={self.demo.phase}, detail={self.demo.detail}")
            await asyncio.sleep(.002)

    async def begin(self, event_id="round-one"):
        await self.demo.invite(event_id)
        self.publish(self.demo.generation, triggered=False)
        await self.wait_for(lambda: self.demo.phase == "awaiting_actions")

    async def test_startup_old_latched_state_never_sends_an_invitation(self):
        self.assertTrue(self.demo.motion["match"])
        self.demo.snapshot()
        await asyncio.sleep(0)
        self.assertEqual(self.demo.phase, "idle")
        self.assertIsNone(self.demo.round_task)
        self.assertEqual(self.watch.calls, [])
        self.assertEqual(self.whoop.pulses, [])

    async def test_fresh_pair_starts_once_without_a_start_button(self):
        await self.demo.dispatch("/api/motion/reset", {})
        generation = self.demo.auto_generation
        self.publish("initial", triggered=True)
        await self.demo.match_detected_gestures()
        self.assertIsNone(self.demo.round_task)

        self.publish(generation, triggered=False)
        self.demo.motion["bands"][0]["triggered"] = True
        await self.demo.match_detected_gestures()
        self.assertIsNone(self.demo.round_task)

        self.demo.proximity.feed(-70, self.demo.clock())
        self.demo.watch_state.update(watch_connected=False, watch_ready=False)
        self.publish(generation, triggered=True)
        await self.demo.match_detected_gestures()
        self.assertTrue(self.demo.snapshot()["matched"])
        await self.wait_for(lambda: self.demo.phase == "approaching")
        self.assertEqual(self.whoop.pulses, ["one-second"])
        await self.demo.stop()
        await self.demo.match_detected_gestures()
        self.assertEqual(self.whoop.pulses, ["one-second"])

    async def test_reconnect_releases_still_connected_whoop_after_failed_stop(self):
        # A failed STOP can disarm the control channel while Bluetooth remains
        # connected. This is the state observed on the actual demo after a buzz.
        from unittest.mock import AsyncMock

        connected = True
        self.whoop.ready = False
        self.whoop.snapshot = lambda: dict(connected=connected, ready=self.whoop.ready)

        async def disconnect():
            nonlocal connected
            connected = False

        async def connect():
            nonlocal connected
            if connected:
                raise RuntimeError("WHOOP link is not ready; disconnect before reconnecting")
            connected = self.whoop.ready = True

        self.whoop.disconnect = AsyncMock(side_effect=disconnect)
        self.whoop.connect = connect
        result = await self.demo.connect()
        self.whoop.disconnect.assert_awaited_once()
        self.assertTrue(result["whoop"]["ready"])
        self.assertEqual(self.whoop.pulses, [])

    async def test_invitation_waits_for_both_bands_to_ack_new_reset(self):
        await self.demo.invite("clear-old-latches")
        await asyncio.sleep(.02)
        self.assertEqual(self.watch.calls, [])
        self.assertEqual(self.whoop.pulses, [])
        self.assertEqual(self.demo.phase, "preparing")
        self.publish(self.demo.generation, triggered=False)
        await self.wait_for(lambda: self.demo.phase == "awaiting_actions")
        self.assertEqual(self.watch.calls, ["match_request"])
        self.assertEqual(self.whoop.pulses, ["one-second"])

    async def test_dashboard_matches_both_fresh_gestures_before_sending_any_pulse(self):
        # Old latched gestures must never trigger the silent arm path.
        await self.demo.dispatch("/api/arm", {"event_id": "gesture-first"})
        self.publish(self.demo.generation, triggered=False)
        await self.wait_for(lambda: self.demo.phase == "awaiting_actions")
        self.assertEqual(self.watch.calls, [])
        self.assertEqual(self.whoop.pulses, [])

        self.demo.motion["bands"][0]["triggered"] = True
        await self.wait_for(lambda: any("Vexo 62" in log["message"] for log in self.demo.history))
        self.assertFalse(self.demo.snapshot()["matched"])
        self.assertEqual(self.whoop.pulses, [])

        self.demo.watch_state.update(watch_ready=False, watch_connected=False)
        self.demo.proximity.feed(-55, self.demo.clock())
        self.demo.proximity.band = 3
        self.publish(self.demo.generation, triggered=True)
        await self.wait_for(lambda: self.demo.phase == "approaching")
        self.assertTrue(self.demo.snapshot()["matched"])
        self.assertEqual(self.watch.calls, [])
        self.assertEqual(self.whoop.pulses, ["one-second"])
        self.assertIsNotNone(self.demo.paused_reason)

        self.demo.motion["bands"][1]["connected"] = False
        self.demo.watch_state.update(watch_ready=True, watch_connected=True)
        await self.wait_for(lambda: self.watch.calls == ["click"])
        self.assertEqual(self.whoop.pulses, ["one-second", "notification"])
        self.assertEqual(self.demo.phase, "approaching")

        self.demo.motion["reset_generation"] = "external-reset"
        await self.wait_for(lambda: self.demo.phase == "failed")
        self.assertEqual(self.whoop.pulses, ["one-second", "notification"])

    async def test_same_id_does_not_reset_or_repeat_even_after_restart(self):
        await self.begin()
        generation = self.demo.generation
        duplicate = await self.demo.invite("round-one")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(self.demo.generation, generation)
        self.assertEqual(self.watch.calls, ["match_request"])
        self.assertEqual(self.whoop.pulses, ["one-second"])
        await self.demo.stop()
        restarted = Demo(self.whoop, self.watch, directory=self.directory)
        self.assertTrue((await restarted.invite("round-one"))["duplicate"])
        self.assertIsNone(restarted.round_task)
        self.assertEqual(self.watch.calls, ["match_request"])

    async def test_stop_preparing_prevents_later_ready_or_motion_from_sending(self):
        await self.demo.invite("stopped-before-invite")
        await self.demo.stop()
        self.publish(self.demo.generation, triggered=True)
        await asyncio.sleep(.02)
        self.assertEqual(self.demo.phase, "stopped")
        self.assertEqual(self.watch.calls, [])
        self.assertEqual(self.whoop.pulses, [])

    async def test_changed_reset_generation_stops_without_match_confirmation(self):
        await self.begin()
        self.publish("a-new-external-round", triggered=True)
        await self.wait_for(lambda: self.demo.phase == "failed")
        self.assertEqual(self.watch.calls, ["match_request"])
        self.assertEqual(self.whoop.pulses, ["one-second"])

    async def test_stale_motion_stops_without_match_confirmation(self):
        await self.begin()
        self.publish(self.demo.generation, triggered=True, age=5)
        await self.wait_for(lambda: self.demo.phase == "failed")
        self.assertEqual(self.watch.calls, ["match_request"])
        self.assertEqual(self.whoop.pulses, ["one-second"])

    async def test_stopped_whoop_pulse_is_not_reported_as_successful_invitation(self):
        self.whoop.buzz_result = "stopped"
        await self.demo.invite("stopped-whoop")
        self.publish(self.demo.generation, triggered=False)
        await self.wait_for(lambda: self.demo.phase == "failed")
        self.assertEqual(self.watch.calls, ["match_request"])

    async def test_new_invite_is_rejected_until_stop_cleanup_finishes(self):
        await self.begin()
        self.whoop.stop_entered.clear()
        self.whoop.stop_gate = asyncio.Event()
        stopping = asyncio.create_task(self.demo.stop())
        self.tasks.append(stopping)
        await self.whoop.stop_entered.wait()
        try:
            with self.assertRaises(RuntimeError):
                await self.demo.invite("must-not-start-during-stop")
            with self.assertRaises(RuntimeError):
                await self.demo.connect()
        finally:
            self.whoop.stop_gate.set()
            await stopping
        self.assertEqual(self.demo.phase, "stopped")
        self.assertEqual(self.watch.calls, ["match_request"])

    async def test_late_uncancellable_watch_request_is_rejected_after_stop(self):
        delayed = DelayedWatch()
        self.demo.watch = delayed
        await self.demo.invite("stop-late-http")
        self.publish(self.demo.generation, triggered=False)
        await self.wait_for(delayed.thread_started.is_set)
        try:
            await self.demo.stop()
            delayed.release_thread.set()
            await self.wait_for(delayed.thread_finished.is_set)
            self.assertIsNotNone(delayed.attempted_scope)
            self.assertTrue(delayed.rejected)
            self.assertEqual(delayed.calls, [])
            self.assertEqual(self.demo.phase, "stopped")
        finally:
            delayed.release_thread.set()

    async def test_terminal_round_cleanup_blocks_a_new_invitation(self):
        await self.begin()
        old_round = self.demo.round_task
        self.whoop.stop_entered.clear()
        self.whoop.stop_gate = asyncio.Event()
        self.publish(self.demo.generation, triggered=False, age=5)
        await self.whoop.stop_entered.wait()
        # New samples alone must not make a still-cleaning round reusable.
        self.publish(self.demo.generation, triggered=False)
        try:
            with self.assertRaises(RuntimeError):
                await self.demo.invite("during-terminal-cleanup")
            with self.assertRaises(RuntimeError):
                await self.demo.connect()
        finally:
            self.whoop.stop_gate.set()
            await old_round

    async def test_whoop_disconnect_aborts_action_wait_without_more_haptics(self):
        await self.begin()
        self.whoop.ready = False
        self.publish(self.demo.generation, triggered=True)
        await self.wait_for(lambda: self.demo.phase == "failed")
        self.assertEqual(self.watch.calls, ["match_request"])
        self.assertEqual(self.whoop.pulses, ["one-second"])

    async def test_stale_rssi_ends_approach_without_a_proximity_pulse(self):
        await self.begin()
        self.demo.proximity.feed(-60, self.demo.clock())
        self.publish(self.demo.generation, triggered=True)
        await self.wait_for(lambda: self.demo.phase == "approaching")
        self.demo.proximity.updated = self.demo.clock() - 5
        await self.wait_for(lambda: self.demo.phase == "failed")
        self.assertEqual(self.watch.calls, ["match_request", "match_confirmed"])
        self.assertEqual(self.whoop.pulses, ["one-second", "notification"])

    async def test_watch_active_race_pauses_without_retrying_the_completed_whoop_pulse(self):
        self.demo.scope = "a" * 32
        await self.watch.open_scope(self.demo.scope)

        async def inactive(_kind, scope=None):
            return {"result": "watch_inactive"}

        self.watch.buzz = inactive
        await self.demo._deliver(self.demo.epoch, "click", "notification")
        self.assertIsNotNone(self.demo.paused_reason)
        await asyncio.sleep(.02)
        self.assertEqual(self.whoop.pulses, ["notification"])


class ProximityTests(unittest.TestCase):
    def test_outlier_is_filtered_and_expired_signal_has_no_cadence(self):
        proximity = Proximity()
        for index in range(5):
            proximity.feed(-80, index * .5)
        proximity.feed(-20, 2.5)
        self.assertEqual(proximity.band, 0)
        self.assertEqual(proximity.smooth, -80)
        for index in range(20):
            proximity.feed(-50, 3 + index * .5)
        self.assertEqual(proximity.band, 3)
        self.assertEqual(proximity.snapshot(12.5)["interval"], .6)
        self.assertFalse(proximity.fresh(16))
        self.assertIsNone(proximity.snapshot(16)["interval"])
        self.assertIsNone(proximity.snapshot(16)["raw_rssi"])

    def test_calibration_needs_samples_freshness_and_separated_points(self):
        proximity = Proximity()
        with self.assertRaises(ValueError):
            proximity.calibrate("far", 0)
        for index in range(5):
            proximity.feed(-80, index * .5)
        with self.assertRaises(ValueError):
            proximity.calibrate("far", 6)
        proximity.calibrate("far", 2)
        for index in range(5):
            proximity.feed(-78, 2.5 + index * .5)
        with self.assertRaises(ValueError):
            proximity.calibrate("near", 4.5)
        self.assertFalse(proximity.snapshot(4.5)["calibrated"])
        for index in range(5):
            proximity.feed(-50, 5 + index * .5)
        proximity.calibrate("near", 7)
        self.assertTrue(proximity.snapshot(7)["calibrated"])
        self.assertEqual((proximity.far, proximity.near), (-80, -50))


if __name__ == "__main__":
    unittest.main()
