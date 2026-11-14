import struct
import unittest
import zlib

from whoop_haptics_protocol import (
    CLIENT_HELLO, MAX_FRAME_BYTES, Reassembler, crc16_modbus, frame,
    one_buzz_frame, parse_frame, stop_frame,
)


def synthetic_response(host_seq=2, result=1, body=b"\x01\x05"):
    # Independent synthetic incoming fixture: strap seq 147 differs from host 2.
    inner = bytes((38, 147, 19, host_seq, result)) + body
    inner += b"\x00" * (-len(inner) % 4)
    header = b"\xaa\x01" + struct.pack("<H", len(inner) + 4) + b"\x00\x01"
    return header + struct.pack("<H", crc16_modbus(header)) + inner + struct.pack("<I", zlib.crc32(inner))


class HapticsProtocolTests(unittest.TestCase):
    def test_known_hardware_derived_one_buzz_golden_and_hello(self):
        # NOOP DeviceFamilyFramingTests golden, quoted in issue #926.
        self.assertEqual(one_buzz_frame(1).hex(),
                         "aa0114000001e1e1230113012f980000000000000000000098cb83a5")
        self.assertEqual(frame(145, 1, b"\x01"), CLIENT_HELLO)
        self.assertEqual(crc16_modbus(b"123456789"), 0x4B37)
        parsed = parse_frame(one_buzz_frame(1))
        self.assertEqual((parsed.command, parsed.sequence), (19, 1))
        self.assertEqual(parsed.payload[:12], bytes.fromhex("012f98000000000000000000"))
        self.assertEqual(parse_frame(stop_frame(3)).payload, b"\x01")

    def test_response_uses_host_echo_and_preserves_pending_and_detail(self):
        for result, name in ((0, "failure"), (1, "success"), (2, "pending"), (3, "unsupported")):
            parsed = parse_frame(synthetic_response(result=result))
            self.assertEqual((parsed.sequence, parsed.response_sequence, parsed.command), (147, 2, 19))
            self.assertEqual(parsed.result_name, name)
            self.assertEqual(parsed.body[:2], b"\x01\x05")

    def test_bad_checksums_lengths_and_truncation_are_rejected(self):
        good = synthetic_response()
        bad_header = bytearray(good)
        bad_header[5] ^= 1
        bad_payload = bytearray(good)
        bad_payload[13] ^= 1
        for data in (good[:-1], good + b"\x00", bytes(bad_header), bytes(bad_payload), b"\xaa"):
            with self.subTest(data=data.hex()), self.assertRaises(ValueError):
                parse_frame(data)

    def test_reassembly_fragmentation_noise_multiple_frames_and_size_bound(self):
        good = synthetic_response()
        reader = Reassembler()
        self.assertEqual(reader.feed(b"noise" + good[:7]), [])
        self.assertEqual(len(reader.feed(good[7:] + good)), 2)
        self.assertEqual(reader.buffer, b"")
        bad = b"\xaa\x01\xff\xff\x00\x01"
        bad += struct.pack("<H", crc16_modbus(bad))
        self.assertEqual(len(reader.feed(bad + b"\x00" * 20000 + good)), 1)
        self.assertLess(len(reader.buffer), MAX_FRAME_BYTES)
        self.assertGreater(reader.rejected, 0)


if __name__ == "__main__":
    unittest.main()
