import unittest

from watch_haptics import Session


class WatchSessionTests(unittest.TestCase):
    def ready(self):
        session = Session()
        self.assertTrue(session.subscribe("my-watch"))
        self.assertTrue(session.receive("my-watch", b"\x01\x00"))
        return session

    def test_connection_without_foreground_ready_cannot_buzz(self):
        session = Session()
        session.subscribe("my-watch")
        self.assertFalse(session.receive("other-watch", b"\x01\x00"))
        with self.assertRaises(RuntimeError):
            session.submit("notification")

    def test_ack_requires_exact_command_and_watch(self):
        session = self.ready()
        command = session.submit("notification")
        self.assertEqual(len(command.packet), 10)
        self.assertFalse(session.receive("other-watch", command.packet + b"\x00"))
        session.receive("my-watch", command.packet[:6] + b"\xff\xff\xff\xff\x00")
        self.assertFalse(command.done.is_set())
        session.receive("my-watch", command.packet + b"\x00")
        self.assertEqual(command.result, "play_called")
        self.assertTrue(command.done.is_set())

    def test_busy_and_disconnect_do_not_replay(self):
        session = self.ready()
        command = session.submit("click")
        with self.assertRaises(RuntimeError):
            session.submit("click")
        session.disconnect("my-watch")
        self.assertEqual(command.result, "disconnected")
        session.subscribe("my-watch")
        session.receive("my-watch", b"\x01\x00")
        self.assertIsNone(session.pending)

    def test_timeout_and_inactive_cancel_queued_commands(self):
        session = self.ready()
        command = session.submit("success")
        session.expire(command.deadline + 1)
        self.assertEqual(command.result, "timeout_not_retried")
        self.assertIsNone(session.pending)
        command = session.submit("click")
        session.receive("my-watch", b"\x01\xff")
        self.assertEqual(command.result, "watch_inactive")
        self.assertFalse(session.ready)

    def test_background_capability_accepts_alerts_but_rejects_continuous_pulses(self):
        session = self.ready()
        session.receive("my-watch", b"\x01\x01")
        self.assertFalse(session.snapshot()["watch_ready"])
        self.assertTrue(session.snapshot()["watch_can_alert"])
        with self.assertRaises(RuntimeError):
            session.submit("click")
        command = session.submit("match_request")
        session.receive("my-watch", command.packet + b"\x03")
        self.assertEqual(command.result, "notification_scheduled")
        command = session.submit("match_confirmed")
        session.receive("my-watch", command.packet + b"\x04")
        self.assertEqual(command.result, "notification_denied")

    def test_foreground_to_background_keeps_only_pending_alerts(self):
        session = self.ready()
        alert = session.submit("match_request")
        session.receive("my-watch", b"\x01\x01")
        self.assertFalse(alert.done.is_set())
        self.assertTrue(session.can_send(alert))
        session.receive("my-watch", b"\x01\xff")
        self.assertEqual(alert.result, "watch_inactive")
        session.receive("my-watch", b"\x01\x00")
        pulse = session.submit("click")
        session.receive("my-watch", b"\x01\x01")
        self.assertEqual(pulse.result, "watch_inactive")

    def test_stop_scope_rejects_late_http_and_clears_pending_notification(self):
        session = self.ready()
        scope = "a" * 32
        session.open_scope(scope)
        command = session.submit("click", scope)
        session.cancel_scope(scope)
        self.assertEqual(command.result, "cancelled")
        self.assertIsNone(session.pending)
        with self.assertRaises(RuntimeError):
            session.submit("click", scope)
        with self.assertRaises(RuntimeError):
            session.open_scope(scope)
        # A late scope-open after a cancellation is rejected as well.
        session.cancel_scope("b" * 32)
        with self.assertRaises(RuntimeError):
            session.open_scope("b" * 32)

    def test_inactive_ack_revokes_stale_foreground_readiness(self):
        session = self.ready()
        command = session.submit("click")
        session.receive("my-watch", command.packet + b"\x02")
        self.assertFalse(session.ready)
        with self.assertRaises(RuntimeError):
            session.submit("click")


if __name__ == "__main__":
    unittest.main()
