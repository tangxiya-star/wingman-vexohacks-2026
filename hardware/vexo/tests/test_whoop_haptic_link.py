"""Offline control/transport contract tests; never scans or opens Bluetooth."""

import asyncio
import struct
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from whoop_haptic_link import WhoopHapticLink
from whoop_haptics_protocol import NOTIFY_UUIDS, frame, parse_frame

WHOOP_UUID = "00000000-0000-4000-8000-000000000001"
WHOOP_SERIAL = "TEST-SERIAL"


def response(command, request_sequence, *, body=None, result=1):
    body = (b"\x01\x05" if command == 19 else b"\x01\x00") if body is None else body
    packet = bytearray(frame(command, 20, bytes((request_sequence, result)) + body))
    packet[8] = 38
    packet[-4:] = struct.pack("<I", zlib.crc32(packet[8:-4]))
    return bytes(packet)


class Client:
    def __init__(self, serial=WHOOP_SERIAL):
        self.is_connected = False
        self.serial = serial
        self.callback = None
        self.notifications = {}
        self.writes = []
        self.pulse_seen = asyncio.Event()
        self.pulse_behavior = "success"
        self.stop_behavior = "success"
        self.services = SimpleNamespace(get_service=lambda _uuid: object(),
                                        get_characteristic=lambda _uuid: object())
        self._backend = SimpleNamespace(get_rssi=AsyncMock(return_value=-64))

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        if self.callback:
            self.callback(self)

    async def read_gatt_char(self, uuid):
        return {"2a25": self.serial.encode(), "2a24": b"5.0", "2a26": b"50.43.2.0"}[uuid[4:8]]

    async def start_notify(self, uuid, callback):
        self.notifications[uuid] = callback

    def emit(self, packet):
        self.notifications[NOTIFY_UUIDS[0]](None, packet)

    async def write_gatt_char(self, _uuid, data, response):
        if not response:
            raise AssertionError("All control writes require ATT response")
        packet = parse_frame(data)
        self.writes.append(packet)
        if packet.command == 145:
            if self.notifications:
                raise AssertionError("HELLO must precede private subscriptions")
            return
        if packet.command == 19:
            self.pulse_seen.set()
            behavior = self.pulse_behavior
        else:
            behavior = self.stop_behavior
        if behavior == "write_timeout":
            raise TimeoutError("Uncertain ATT write")
        if behavior == "disconnect":
            await self.disconnect()
        elif behavior == "success":
            # Exercise real CRC parsing, pending status, and response correlation.
            self.emit(globals()["response"](packet.command, packet.sequence, result=2))
            self.emit(globals()["response"](packet.command, packet.sequence))


class LinkTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, client=None, **options):
        client = client or Client()
        finder = AsyncMock(return_value=SimpleNamespace(address=WHOOP_UUID))

        def factory(_device, *, timeout, disconnected_callback):
            client.callback = disconnected_callback
            return client

        link = WhoopHapticLink(source=WHOOP_UUID, serial=WHOOP_SERIAL,
                              finder=finder, client_factory=factory,
                              command_timeout=.05, write_timeout=.05, stop_timeout=.05,
                              **options)
        return link, client, finder

    async def test_wrong_identity_never_writes_or_subscribes(self):
        link, client, finder = await self.make(Client(serial="another-person"))
        with self.assertRaisesRegex(RuntimeError, "serial mismatch"):
            await link.connect()
        finder.assert_awaited_once_with(WHOOP_UUID, timeout=12)
        self.assertFalse(client.is_connected)
        self.assertEqual(client.writes, [])
        self.assertEqual(client.notifications, {})
        self.assertFalse(link.ready)

    async def test_successful_pulses_are_serialized_with_unique_requests_and_stop(self):
        link, client, _ = await self.make()
        await link.connect()
        result = await link.buzz()
        self.assertEqual(result["result"], "buzz_completed")
        self.assertTrue(result["stop_confirmed"])
        await link.buzz("one-second")
        self.assertEqual([p.command for p in client.writes], [145, 19, 122, 19, 122])
        seqs = [p.sequence for p in client.writes[1:]]
        self.assertEqual(len(seqs), len(set(seqs)))
        self.assertEqual(client.writes[3].payload[:3], b"\x01\x10\x00")
        self.assertTrue(link.ready)

    async def test_uncertain_write_stops_once_without_pulse_retry(self):
        link, client, _ = await self.make()
        await link.connect()
        client.pulse_behavior = "write_timeout"
        with self.assertRaises(TimeoutError):
            await link.buzz()
        self.assertEqual([p.command for p in client.writes], [145, 19, 122])
        self.assertEqual(link.last_result, "uncertain_not_retried")
        self.assertFalse(link.busy)

    async def test_stale_ack_cannot_complete_new_pulse_and_busy_is_not_queued(self):
        link, client, _ = await self.make()
        await link.connect()
        await link.buzz()
        old_seq = client.writes[1].sequence
        client.pulse_behavior = "silent"
        client.pulse_seen.clear()
        task = asyncio.create_task(link.buzz())
        await client.pulse_seen.wait()
        client.emit(response(19, old_seq))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        with self.assertRaisesRegex(RuntimeError, "no pulse was queued"):
            await link.buzz()
        current_seq = client.writes[-1].sequence
        client.emit(response(19, current_seq))
        self.assertEqual((await task)["result"], "buzz_completed")
        self.assertEqual(sum(p.command == 19 for p in client.writes), 2)

    async def test_stop_coalesces_with_inflight_cleanup(self):
        link, client, _ = await self.make()
        await link.connect()
        client.pulse_behavior = "silent"
        task = asyncio.create_task(link.buzz())
        await client.pulse_seen.wait()
        result = await link.stop()
        self.assertTrue(result["stop_confirmed"])
        self.assertEqual((await task)["result"], "stopped")
        self.assertEqual([p.command for p in client.writes], [145, 19, 122])

    async def test_disconnect_terminates_wait_without_reconnecting_or_replaying(self):
        link, client, finder = await self.make()
        await link.connect()
        client.pulse_behavior = "disconnect"
        with self.assertRaises(ConnectionError):
            await link.buzz()
        self.assertEqual([p.command for p in client.writes], [145, 19])
        self.assertFalse(link.connected)
        self.assertFalse(link.ready)
        self.assertEqual(finder.await_count, 1)

    async def test_unconfirmed_stop_disarms_link_until_explicit_reconnect(self):
        link, client, _ = await self.make()
        await link.connect()
        client.stop_behavior = "silent"
        result = await link.buzz()
        self.assertFalse(result["stop_confirmed"])
        self.assertFalse(link.ready)
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            await link.buzz()
        self.assertEqual([p.command for p in client.writes], [145, 19, 122])

    async def test_connected_rssi_invalid_sample_clears_freshness(self):
        link, client, _ = await self.make()
        await link.connect()
        self.assertEqual(await link.read_rssi(), -64)
        self.assertIsNotNone(link.snapshot()["rssi_age"])
        client._backend.get_rssi.return_value = 127
        with self.assertRaises(ValueError):
            await link.read_rssi()
        self.assertIsNone(link.snapshot()["rssi"])
        self.assertIsNone(link.snapshot()["rssi_age"])

    async def test_rssi_from_connection_lost_during_read_is_not_published(self):
        link, client, _ = await self.make()
        await link.connect()
        started, release = asyncio.Event(), asyncio.Event()

        async def read():
            started.set()
            await release.wait()
            return -40

        client._backend.get_rssi.side_effect = read
        task = asyncio.create_task(link.read_rssi())
        await started.wait()
        await client.disconnect()
        release.set()
        with self.assertRaises(ConnectionError):
            await task
        self.assertIsNone(link.snapshot()["rssi"])

    async def test_old_connection_callback_cannot_ack_new_connection(self):
        link, first, _ = await self.make()
        await link.connect()
        old_callback = first.notifications[NOTIFY_UUIDS[0]]
        await link.disconnect()
        second = Client()

        def factory(_device, *, timeout, disconnected_callback):
            second.callback = disconnected_callback
            return second

        link._client_factory = factory
        await link.connect()
        second.pulse_behavior = "silent"
        task = asyncio.create_task(link.buzz())
        await second.pulse_seen.wait()
        packet = response(19, second.writes[-1].sequence)
        old_callback(None, packet)
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        second.emit(packet)
        self.assertEqual((await task)["result"], "buzz_completed")

    async def test_cancelled_pulse_still_gets_one_stop_and_no_replay(self):
        link, client, _ = await self.make()
        await link.connect()
        client.pulse_behavior = "silent"
        task = asyncio.create_task(link.buzz())
        await client.pulse_seen.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual([p.command for p in client.writes], [145, 19, 122])
        self.assertFalse(link.busy)

    async def test_sequence_wrap_quarantines_recent_ids(self):
        link, _, _ = await self.make()
        values = [link._sequence() for _ in range(254)]
        self.assertEqual(values, list(range(2, 256)))
        with self.assertRaisesRegex(RuntimeError, "cooldown exhausted"):
            link._sequence()


if __name__ == "__main__":
    unittest.main()
