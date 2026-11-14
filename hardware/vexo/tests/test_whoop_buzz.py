import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from whoop_buzz import run
from whoop_haptics_protocol import CLIENT_HELLO, parse_frame


class FakeClient:
    def __init__(self, serial="DEMO000001", fail_command=None):
        self.is_connected = True
        self.exited = False
        self.fail_command = fail_command
        self.callbacks = {}
        self.services = SimpleNamespace(
            get_service=lambda _uuid: object(),
            get_characteristic=lambda _uuid: object(),
        )
        self.read_gatt_char = AsyncMock(side_effect=lambda uuid: {
            "2a25": serial.encode(), "2a24": b"5.0", "2a26": b"50.43.2.0",
        }[uuid[4:8]])
        self.write_gatt_char = AsyncMock(side_effect=self._write)
        self.start_notify = AsyncMock(side_effect=self._notify)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.is_connected = False
        self.exited = True

    async def _notify(self, uuid, callback):
        self.callbacks[uuid] = callback

    async def _write(self, _uuid, data, response):
        command = parse_frame(data).command
        if command == self.fail_command:
            raise TimeoutError("simulated write timeout")
        if command == 19:
            next(iter(self.callbacks.values()))(None, b"buzz-complete")
        if command == 122:
            # Exercise the probe's real queue/correlation path without BLE.
            next(iter(self.callbacks.values()))(None, b"stop-complete")


class FakeResponseDecoder:
    def feed(self, data):
        if data == b"buzz-complete":
            return [SimpleNamespace(packet_type=38, command=19, response_sequence=2,
                                    result=1, result_name="success", body=b"\x01\x05")]
        if data != b"stop-complete":
            return []
        return [SimpleNamespace(packet_type=38, command=122, response_sequence=3,
                                result=1, result_name="success", body=b"\x01")]


class OneBuzzGuardsTests(unittest.IsolatedAsyncioTestCase):
    def args(self, pattern="notification"):
        return SimpleNamespace(source="confirmed-mac-uuid", serial="DEMO000001",
                               buzz=True, pattern=pattern)

    async def exercise(self, client, pattern="notification"):
        scan = AsyncMock(return_value=SimpleNamespace(address="confirmed-mac-uuid"))
        with patch("whoop_buzz.BleakScanner.find_device_by_address", scan), \
             patch("whoop_buzz.BleakClient", return_value=client), \
             patch("whoop_buzz.Reassembler", FakeResponseDecoder), \
             patch("whoop_buzz.log"):
            try:
                await run(self.args(pattern))
            finally:
                scan.assert_awaited_once_with("confirmed-mac-uuid", timeout=12)

    async def test_wrong_serial_performs_zero_writes_and_disconnects(self):
        client = FakeClient(serial="wrong-serial")
        with self.assertRaisesRegex(RuntimeError, "序列号不匹配"):
            await self.exercise(client)
        client.write_gatt_char.assert_not_awaited()
        client.start_notify.assert_not_awaited()
        self.assertTrue(client.exited)

    async def test_failed_handshake_never_subscribes_or_buzzes(self):
        client = FakeClient(fail_command=145)
        with self.assertRaises(TimeoutError):
            await self.exercise(client)
        self.assertEqual(client.write_gatt_char.await_count, 1)
        self.assertEqual(client.write_gatt_char.call_args.args[1], CLIENT_HELLO)
        client.start_notify.assert_not_awaited()
        self.assertTrue(client.exited)

    async def test_uncertain_buzz_write_is_stopped_once_never_repeated(self):
        client = FakeClient(fail_command=19)
        with self.assertRaises(TimeoutError):
            await self.exercise(client)
        commands = [parse_frame(call.args[1]).command
                    for call in client.write_gatt_char.await_args_list]
        self.assertEqual(commands, [145, 19, 122])
        self.assertTrue(all(call.kwargs["response"]
                            for call in client.write_gatt_char.await_args_list))
        self.assertTrue(client.exited)

    def assert_one_second_sent_once_then_stopped(self, client):
        writes = client.write_gatt_char.await_args_list
        packets = [parse_frame(call.args[1]) for call in writes]
        self.assertEqual([packet.command for packet in packets], [145, 19, 122])
        self.assertEqual(packets[1].sequence, 2)
        # Revision 1, ROM effect 16, terminator, zero repeat fields; final byte is padding.
        self.assertEqual(packets[1].payload, bytes.fromhex(
            "01 10 00 00 00 00 00 00 00 00 00 00 00"))
        self.assertEqual(packets[2].sequence, 3)
        self.assertEqual(packets[2].payload, b"\x01")
        self.assertTrue(all(call.kwargs["response"] for call in writes))
        self.assertTrue(client.exited)

    async def test_one_second_success_uses_single_effect_and_cleanup_stop(self):
        client = FakeClient()
        await self.exercise(client, pattern="one-second")
        self.assert_one_second_sent_once_then_stopped(client)

    async def test_one_second_uncertain_write_timeout_stops_without_retry(self):
        client = FakeClient(fail_command=19)
        with self.assertRaisesRegex(TimeoutError, "simulated write timeout"):
            await self.exercise(client, pattern="one-second")
        self.assert_one_second_sent_once_then_stopped(client)


if __name__ == "__main__":
    unittest.main()
