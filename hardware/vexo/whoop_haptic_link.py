"""Persistent, serial-verified WHOOP 5 haptics and connected RSSI for the demo.

No connection or command happens on import. Each pulse has zero repeats and one
cleanup STOP; an uncertain pulse is never resent. Calls must share one asyncio
loop. This link does not subscribe to or change the existing heart-rate stream.
RSSI is Mac-to-WHOOP signal strength, not person-to-person distance.
"""

import asyncio
import math
import time
from dataclasses import dataclass

from bleak import BleakClient, BleakScanner

from whoop_haptics_protocol import (
    CLIENT_HELLO, COMMAND_UUID, NOTIFY_UUIDS, SERVICE_UUID,
    Reassembler, one_buzz_frame, one_second_frame, stop_frame,
)

class HapticStopped(RuntimeError):
    """A local stop superseded a pulse's completion wait, without resending it."""


@dataclass
class Pending:
    command: int
    sequence: int
    future: asyncio.Future


class WhoopHapticLink:
    def __init__(self, source=None, serial=None, *, log=None,
                 finder=None, client_factory=None, command_timeout=8.0,
                 write_timeout=8.0, stop_timeout=3.0, rssi_timeout=3.0,
                 sequence_reuse_delay=60.0):
        if (not isinstance(source, str) or not source.strip()
                or not isinstance(serial, str) or not serial.strip()):
            raise ValueError("An exact source and expected serial are required")
        times = (command_timeout, write_timeout, stop_timeout, rssi_timeout,
                 sequence_reuse_delay)
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) or x <= 0 for x in times):
            raise ValueError("Timeouts and sequence reuse delay must be finite and positive")
        self.source, self.serial = source, serial
        self.log = log or (lambda _message: None)
        self._finder = finder or BleakScanner.find_device_by_address
        self._client_factory = client_factory or BleakClient
        self.command_timeout, self.write_timeout = command_timeout, write_timeout
        self.stop_timeout, self.rssi_timeout = stop_timeout, rssi_timeout
        self.sequence_reuse_delay = sequence_reuse_delay
        self._client = None
        self._verified = self._ready = self._connecting = self._closing = False
        self._generation = 0
        self._pending = None
        self._busy = False
        self._operation = None
        self._stop_requested = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._next_sequence = 2
        self._sequence_used = {}
        self._rssi_busy = False
        self.last_result = None
        self.last_stop = None
        self.last_duration = None
        self.last_rssi = None
        self._rssi_at = None
        self.firmware = None
        self.model = None

    @property
    def connected(self):
        return self._client is not None and self._client.is_connected

    @property
    def ready(self):
        return self.connected and self._ready and not self._closing

    @property
    def busy(self):
        return self._busy

    def snapshot(self):
        return {"connected": self.connected, "ready": self.ready,
                "connecting": self._connecting, "busy": self._busy,
                "serial": self.serial, "model": self.model, "firmware": self.firmware,
                "last_result": self.last_result, "last_duration": self.last_duration,
                "last_stop": self.last_stop, "rssi": self.last_rssi,
                "rssi_age": None if self._rssi_at is None else time.monotonic() - self._rssi_at}

    def _lost_connection(self, client, generation):
        if generation != self._generation or client is not self._client:
            return
        self._ready = False
        self.last_rssi = self._rssi_at = None
        self.last_result = "disconnected"
        if self._pending is not None and not self._pending.future.done():
            self._pending.future.set_exception(ConnectionError("WHOOP disconnected"))

    async def connect(self):
        if self.ready:
            return self.snapshot()
        if self._connecting or self._closing or self._busy:
            raise RuntimeError("WHOOP link is busy; no connection was queued")
        if self.connected:
            raise RuntimeError("WHOOP link is not ready; disconnect before reconnecting")
        self._connecting = True
        self._generation += 1
        generation = self._generation
        self._verified = self._ready = False
        self.last_result = "connecting"
        client = None
        try:
            device = await self._finder(self.source, timeout=12)
            if device is None or str(device.address).lower() != self.source.lower():
                raise ConnectionError("The exact configured WHOOP was not found")
            client = self._client_factory(device, timeout=20,
                disconnected_callback=lambda item: self._lost_connection(item, generation))
            self._client = client
            await client.connect()

            async def read(short):
                data = await asyncio.wait_for(client.read_gatt_char(
                    f"0000{short}-0000-1000-8000-00805f9b34fb"), timeout=5)
                return bytes(data).decode("utf-8", errors="strict").rstrip("\x00")

            serial, model, firmware = await read("2a25"), await read("2a24"), await read("2a26")
            if serial != self.serial:
                raise RuntimeError("WHOOP serial mismatch; no control writes performed")
            if model not in ("5.0", "MG") or client.services.get_service(SERVICE_UUID) is None:
                raise RuntimeError("Expected a WHOOP 5/MG control service")
            self.model, self.firmware = model, firmware
            self._verified = True
            # Same ordering as the physically verified one-shot probe.
            await asyncio.wait_for(client.write_gatt_char(COMMAND_UUID, CLIENT_HELLO,
                                                         response=True), timeout=15)
            subscribed = 0
            for uuid in NOTIFY_UUIDS:
                if client.services.get_characteristic(uuid) is None:
                    continue
                decoder = Reassembler()

                def receive(_characteristic, data, *, decoder=decoder):
                    if generation != self._generation or client is not self._client:
                        return
                    for packet in decoder.feed(data):
                        pending = self._pending
                        if (pending is not None and not pending.future.done()
                                and packet.packet_type in (36, 38)
                                and packet.command == pending.command
                                and packet.response_sequence == pending.sequence
                                and packet.result != 2):
                            pending.future.set_result(packet)

                await asyncio.wait_for(client.start_notify(uuid, receive), timeout=5)
                subscribed += 1
            if not subscribed or not client.is_connected:
                raise ConnectionError("WHOOP control notifications unavailable")
            self._ready = True
            self.last_result = "connected"
            self.log(f"WHOOP {self.serial} verified; haptics ready (no pulse sent).")
            return self.snapshot()
        except BaseException:
            self._ready = self._verified = False
            try:
                if client is not None:
                    await client.disconnect()
            finally:
                self._client = None
                self.last_result = "connection_failed"
            raise
        finally:
            self._connecting = False

    def _sequence(self):
        now = time.monotonic()
        # 0/1 are reserved; retain this quarantine across reconnects. The wire
        # protocol only echoes 8 bits, so an arbitrarily late reply is not
        # distinguishable after reuse. 60 s is longer than any command timeout.
        for _ in range(254):
            value = self._next_sequence
            self._next_sequence = 2 if value == 255 else value + 1
            if now - self._sequence_used.get(value, -math.inf) >= self.sequence_reuse_delay:
                self._sequence_used[value] = now
                return value
        raise RuntimeError("WHOOP sequence cooldown exhausted; no command sent")

    async def _command(self, command, builder, response_timeout):
        if not self.connected or not self._verified:
            raise ConnectionError("WHOOP is not connected and verified")
        if self._pending is not None:
            raise RuntimeError("A WHOOP control command is already outstanding")
        seq = self._sequence()
        future = asyncio.get_running_loop().create_future()
        pending = self._pending = Pending(command, seq, future)
        try:
            await asyncio.wait_for(self._client.write_gatt_char(
                COMMAND_UUID, builder(seq), response=True), timeout=self.write_timeout)
            return await asyncio.wait_for(asyncio.shield(future), timeout=response_timeout)
        finally:
            if self._pending is pending:
                self._pending = None
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # Consume a disconnect/stop exception even if the ATT write
                # itself failed before the response future was awaited.
                future.exception()

    async def _cleanup_stop(self):
        if not self.connected or not self._verified:
            self.last_stop = {"result": "disconnected", "stop_confirmed": False}
            return self.last_stop
        try:
            packet = await self._command(122, stop_frame, self.stop_timeout)
            if packet.result != 1 or packet.body[:2] != b"\x01\x00":
                raise RuntimeError("WHOOP did not confirm STOP")
            self.last_stop = {"result": "stopped", "stop_confirmed": True}
        except Exception as error:
            self._ready = False
            self.last_stop = {"result": "stop_unconfirmed", "stop_confirmed": False,
                              "error": type(error).__name__}
        return self.last_stop

    async def buzz(self, pattern="notification"):
        builders = {"notification": one_buzz_frame, "one-second": one_second_frame}
        if pattern not in builders:
            raise ValueError("Unknown WHOOP pulse pattern")
        if not self.ready:
            raise RuntimeError("WHOOP is not ready")
        if self._busy:
            raise RuntimeError("WHOOP is busy; no pulse was queued")
        self._busy = True
        self._operation = "buzz"
        self._stop_requested = False
        self._idle.clear()
        started = time.monotonic()
        self.last_result = "sending"
        try:
            packet = await self._command(19, builders[pattern], self.command_timeout)
            if self._stop_requested:
                raise HapticStopped("Pulse completion wait stopped locally")
            if packet.result != 1 or packet.body[:2] != b"\x01\x05":
                raise RuntimeError("WHOOP did not confirm pulse completion")
            self.last_result = "buzz_completed"
        except HapticStopped:
            self.last_result = "stopped"
        except BaseException:
            self.last_result = "uncertain_not_retried"
            raise
        finally:
            try:
                # A cancelled/failed write may already have reached the device.
                # STOP is separate cleanup, never a retry of the pulse.
                await self._cleanup_stop()
            finally:
                self.last_duration = time.monotonic() - started
                self._busy = False
                self._operation = None
                self._idle.set()
        return {"result": self.last_result, "duration": self.last_duration,
                "stop_confirmed": bool(self.last_stop and self.last_stop["stop_confirmed"])}

    async def stop(self):
        if self._busy:
            self._stop_requested = True
            if (self._operation == "buzz" and self._pending is not None
                    and self._pending.command == 19 and not self._pending.future.done()):
                self._pending.future.set_exception(HapticStopped("Stop requested"))
            # Coalesce with the existing operation's STOP, never queue another.
            await asyncio.wait_for(self._idle.wait(),
                                   timeout=2 * self.write_timeout + self.stop_timeout + 1)
            return self.last_stop
        self._busy = True
        self._operation = "stop"
        self._idle.clear()
        try:
            return await self._cleanup_stop()
        finally:
            self._busy = False
            self._operation = None
            self._idle.set()

    async def read_rssi(self):
        if not self.ready:
            raise RuntimeError("WHOOP is not ready for RSSI")
        if self._rssi_busy:
            raise RuntimeError("An RSSI read is already pending")
        self._rssi_busy = True
        client, generation = self._client, self._generation
        try:
            # Bleak 3.1's installed macOS backend exposes get_rssi(), while the
            # cross-platform public facade does not. Never use old adverts as
            # though they were a current connected measurement.
            reader = getattr(getattr(client, "_backend", None), "get_rssi", None)
            if reader is None:
                raise RuntimeError("Connected RSSI is unavailable on this backend")
            value = await asyncio.wait_for(reader(), timeout=self.rssi_timeout)
            if self._client is not client or generation != self._generation or not self.ready:
                raise ConnectionError("WHOOP disconnected during RSSI measurement")
            if isinstance(value, bool) or not isinstance(value, int) or not -127 <= value <= 20:
                raise ValueError("Invalid connected RSSI")
            self.last_rssi, self._rssi_at = value, time.monotonic()
            return value
        except BaseException:
            self.last_rssi = self._rssi_at = None
            raise
        finally:
            self._rssi_busy = False

    async def disconnect(self):
        if self._connecting:
            raise RuntimeError("Wait for connect to finish before disconnecting")
        self._closing = True
        try:
            if self._verified and self.connected:
                await self.stop()
        finally:
            client = self._client
            self._ready = False
            try:
                if client is not None:
                    await client.disconnect()
            finally:
                self._generation += 1
                self._client = None
                self._verified = self._ready = self._closing = False
                self.last_rssi = self._rssi_at = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_args):
        await self.disconnect()
