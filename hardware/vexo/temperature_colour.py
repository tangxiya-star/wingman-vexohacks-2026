"""Map Vexo chip temperature changes to colour; this is not skin temperature.

The first valid sample is a fixed baseline for this instance. Colours reflect
received measurements directly, without smoothing or inventing temperature
samples between the chip sensor's 0.25 °C steps.
"""

import math
import time


class TemperatureColour:
    """Cold blue at baseline, warm red at ``baseline + warm_delta`` degrees C."""

    _COLOURS = (
        (0x00, 0x66, 0xFF),
        (0x00, 0xD4, 0xFF),
        (0xFF, 0xD2, 0x3F),
        (0xFF, 0x7A, 0x00),
        (0xFF, 0x24, 0x00),
    )

    def __init__(self, warm_delta=1.0, stale_after=5.0):
        if not math.isfinite(warm_delta) or warm_delta <= 0:
            raise ValueError("warm_delta must be finite and greater than zero")
        if not math.isfinite(stale_after) or stale_after <= 0:
            raise ValueError("stale_after must be finite and greater than zero")
        self.warm_delta = warm_delta
        self.stale_after = stale_after
        self._baseline = None
        self._celsius = None
        self._received_at = None

    @property
    def baseline(self):
        return self._baseline

    @property
    def celsius(self):
        """Latest accepted sample, or None after an invalid sample."""
        return self._celsius

    @property
    def delta(self):
        if self._celsius is None or self._baseline is None:
            return None
        return self._celsius - self._baseline

    def receive(self, celsius, now=None):
        """Accept a chip sample; invalid input clears output but keeps baseline."""
        try:
            value = float(celsius)
            valid = not isinstance(celsius, bool) and math.isfinite(value) and -40 <= value <= 85
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            self._celsius = None
            self._received_at = None
            return False
        if self._baseline is None:
            self._baseline = value
        self._celsius = value
        self._received_at = time.monotonic() if now is None else now
        return True

    def colour(self, now=None):
        """Return a colour only while the latest valid chip sample is fresh."""
        now = time.monotonic() if now is None else now
        if self._received_at is None or now - self._received_at >= self.stale_after:
            return None
        position = min(1.0, max(0.0, self.delta / self.warm_delta)) * 4
        segment = min(int(position), 3)
        fraction = position - segment
        lower, upper = self._COLOURS[segment:segment + 2]
        rgb = (round(start + (end - start) * fraction) for start, end in zip(lower, upper))
        return "#" + "".join(f"{component:02x}" for component in rgb)
