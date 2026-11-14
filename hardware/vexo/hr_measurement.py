"""Decode Bluetooth Heart Rate Measurement (0x2A37) notifications.

The payload has no measurement timestamp. Receipt time therefore cannot prove
that a bridge has obtained a fresh reading from its heart rate sensor.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HeartRateMeasurement:
    bpm: int
    contact: bool | None
    rr_seconds: tuple[float, ...]


def parse_heart_rate(data: bytes) -> HeartRateMeasurement:
    """Parse one complete standard notification, rejecting malformed payloads.

    ``contact=None`` means the sensor does not support contact detection.
    Energy Expended, if present, is validated and skipped. RR intervals are
    returned oldest first, in seconds rather than the wire unit of 1/1024 s.
    """
    if not data:
        raise ValueError("Heart Rate Measurement is empty")

    flags = data[0]
    if flags & 0xE0:
        raise ValueError("Heart Rate Measurement has reserved flag bits set")

    bpm_size = 2 if flags & 0x01 else 1
    offset = 1 + bpm_size
    if len(data) < offset:
        raise ValueError("Heart Rate Measurement has a truncated BPM value")
    bpm = int.from_bytes(data[1:offset], "little")
    contact = bool(flags & 0x02) if flags & 0x04 else None

    if flags & 0x08:
        if len(data) < offset + 2:
            raise ValueError("Heart Rate Measurement has truncated energy data")
        offset += 2

    remaining = len(data) - offset
    if flags & 0x10:
        if remaining == 0 or remaining % 2:
            raise ValueError("Heart Rate Measurement has missing or truncated RR data")
        rr_seconds = tuple(
            int.from_bytes(data[index:index + 2], "little") / 1024
            for index in range(offset, len(data), 2)
        )
    else:
        if remaining:
            raise ValueError("Heart Rate Measurement has unexpected trailing data")
        rr_seconds = ()

    return HeartRateMeasurement(bpm, contact, rr_seconds)


def _validate_bpm(bpm: int) -> None:
    if isinstance(bpm, bool) or not isinstance(bpm, int) or not 6 <= bpm <= 600:
        raise ValueError("BPM must be an integer from 6 to 600 for the Vexo LED")


def bpm_period_ms(bpm: int) -> int:
    """Return the flash period for a BPM the Vexo LED can represent.

    Firmware accepts periods from 100 to 10000 ms: 6 through 600 BPM.
    These bounds describe LED timing capability, not a medical validity range.
    """
    _validate_bpm(bpm)
    return round(60000 / bpm)


def display_period_ms(bpm: int) -> int:
    """Return an exaggerated display rhythm, not the actual heartbeat period.

    Valid BPM inputs retain ``bpm_period_ms``'s 6..600 capability bounds.
    Up to 70 BPM displays at 1000 ms; each following 5 BPM band shortens
    the period by 100 ms (71..75: 900 ms, 106..110: 200 ms). Above 110
    BPM the display remains at 100 ms. These are presentation choices.
    """
    _validate_bpm(bpm)
    if bpm <= 70:
        return 1000
    steps = (bpm - 71) // 5 + 1
    return max(100, 1000 - 100 * steps)
