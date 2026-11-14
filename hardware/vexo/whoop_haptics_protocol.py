"""Pure WHOOP 5/MG frame codec for a deliberately bounded haptic experiment.

No Bluetooth, device discovery, or command execution lives in this module.
Protocol sources, pinned to NOOP commit 2a1de7609843b095505274ad6fc811757210be80:
Packages/WhoopProtocol/Sources/WhoopProtocol/{Framing,DeviceFamily,Interpreter,
HapticPayloads}.swift and docs/PROTOCOL_ALARMS.md.
Use one Reassembler per notification characteristic, never merge channels.
"""

from dataclasses import dataclass
import struct
import zlib

SERVICE_UUID = "fd4b0001-cce1-4033-93ce-002d5875f58a"
COMMAND_UUID = "fd4b0002-cce1-4033-93ce-002d5875f58a"
NOTIFY_UUIDS = tuple(f"fd4b000{x}-cce1-4033-93ce-002d5875f58a" for x in (3, 4, 5, 7))
MAX_FRAME_BYTES = 8192
ONE_BUZZ_PAYLOAD = bytes.fromhex("01 2f 98 00 00 00 00 00 00 00 00 00")
# TI DRV2625 waveform library, effect 16: "1000 ms Alert 100%".
# https://www.ti.com/lit/ds/symlink/drv2625.pdf section 9.1.1.
# WHOOP's mapping to this waveform remains subject to physical verification.
ONE_SECOND_PAYLOAD = bytes.fromhex("01 10 00 00 00 00 00 00 00 00 00 00")
STOP_PAYLOAD = b"\x01"
CLIENT_HELLO = bytes.fromhex("aa0108000001e67123019101363e5c8d")
RESULT_NAMES = {0: "failure", 1: "success", 2: "pending", 3: "unsupported"}


def crc16_modbus(data):
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def frame(command, seq, payload):
    """Encode a WHOOP 5 command; pure bytes only, with no transport side effects."""
    if type(command) is not int or not 0 <= command <= 255:
        raise ValueError("command must be a byte")
    if type(seq) is not int or not 0 <= seq <= 255:
        raise ValueError("sequence must be a byte")
    inner = bytes((35, seq, command)) + bytes(payload)
    inner += b"\x00" * (-len(inner) % 4)
    if len(inner) + 12 > MAX_FRAME_BYTES:
        raise ValueError("frame exceeds bounded size")
    header = b"\xaa\x01" + struct.pack("<H", len(inner) + 4) + b"\x00\x01"
    return (header + struct.pack("<H", crc16_modbus(header)) + inner
            + struct.pack("<I", zlib.crc32(inner)))


def one_buzz_frame(seq):
    """One notification pulse, zero repeats; no alarm scheduling or persistent write."""
    return frame(19, seq, ONE_BUZZ_PAYLOAD)


def one_second_frame(seq):
    """One nominal 1000 ms ROM effect, terminated by zero, with zero repeats."""
    return frame(19, seq, ONE_SECOND_PAYLOAD)


def stop_frame(seq):
    return frame(122, seq, STOP_PAYLOAD)


@dataclass(frozen=True)
class ParsedFrame:
    packet_type: int
    sequence: int | None
    command: int | None
    payload: bytes
    response_sequence: int | None = None
    result: int | None = None
    body: bytes = b""

    @property
    def result_name(self):
        return RESULT_NAMES.get(self.result, "unknown")


def parse_frame(data):
    """Validate both checksums before exposing response fields.

    response_sequence echoes the HOST's sent sequence; sequence is the strap's
    independent counter. body retains alignment padding, whose semantic length
    is specific to each command. A success response alone is not a felt buzz.
    """
    data = bytes(data)
    if not 13 <= len(data) <= MAX_FRAME_BYTES:
        raise ValueError("invalid frame size")
    if data[:2] != b"\xaa\x01":
        raise ValueError("invalid WHOOP 5 frame prefix")
    if struct.unpack_from("<H", data, 2)[0] + 8 != len(data):
        raise ValueError("frame length mismatch")
    if crc16_modbus(data[:6]) != struct.unpack_from("<H", data, 6)[0]:
        raise ValueError("header CRC mismatch")
    inner = data[8:-4]
    if zlib.crc32(inner) != struct.unpack_from("<I", data, len(data) - 4)[0]:
        raise ValueError("payload CRC mismatch")
    packet_type = inner[0]
    sequence = inner[1] if len(inner) > 1 else None
    command = inner[2] if len(inner) > 2 else None
    payload = inner[3:]
    if packet_type in (36, 38):
        if len(inner) < 5:
            raise ValueError("truncated command response")
        return ParsedFrame(packet_type, sequence, command, payload,
                           payload[0], payload[1], payload[2:])
    return ParsedFrame(packet_type, sequence, command, payload)


class Reassembler:
    """Bounded, CRC-validating notification fragment collector."""

    def __init__(self):
        self.buffer = bytearray()
        self.rejected = 0

    def feed(self, chunk):
        # Consume bytewise to keep retained data bounded even for a huge chunk.
        frames = []
        for byte in chunk:
            self.buffer.append(byte)
            while self.buffer:
                if self.buffer[0] != 0xAA:
                    del self.buffer[0]
                    continue
                if len(self.buffer) < 8:
                    break
                total = struct.unpack_from("<H", self.buffer, 2)[0] + 8
                header_valid = (self.buffer[1] == 1
                                and crc16_modbus(self.buffer[:6])
                                == struct.unpack_from("<H", self.buffer, 6)[0])
                if not header_valid or not 13 <= total <= MAX_FRAME_BYTES:
                    self.rejected += 1
                    del self.buffer[0]
                    continue
                if len(self.buffer) < total:
                    break
                candidate = bytes(self.buffer[:total])
                try:
                    parsed = parse_frame(candidate)
                except ValueError:
                    self.rejected += 1
                    del self.buffer[0]
                else:
                    del self.buffer[:total]
                    frames.append(parsed)
        return frames
