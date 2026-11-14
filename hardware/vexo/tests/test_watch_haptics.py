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


if __name__ == "__main__":
    unittest.main()
