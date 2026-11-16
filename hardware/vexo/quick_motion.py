"""Acceleration-only quick-motion trigger with an explicit manual-reset latch.

The signal is abs(norm(ax, ay, az) - 1 g), independent of sensor orientation.
Defaults require at least five consecutive samples spanning 120 ms at >=0.80 g
deviation. One-sample shocks and short pulses do not trigger. Initial arming
requires 300 ms near 1 g (within 0.12 g); manual reset also requires a 400 ms
cooldown starting with the next valid sample. Gyroscope fields are never read.

These are hackathon demo thresholds, not an overhead/height/gesture classifier.
A drop, shake, or other sufficiently strong motion can also trigger. The higher
default was selected after ordinary wrist/typing motion triggered the previous
0.50 g / 80 ms setting. It requires firmer motion and can miss lighter intended
actions; amplitude alone cannot reliably separate intent. Retrospective checks
are not an independent recognition-rate or tap-rejection guarantee. At 50 Hz,
120 ms requires seven consecutive samples (six timestamp intervals).

Invalid/backwards input clears readiness and candidates, not the latch. Small
forward packet loss (at most 100 ms) cancels the candidate and quiet window but
preserves established readiness. A ready, already latched result also survives
larger forward gaps: its event already happened and is not inferred again.
The caller must expire live state when no samples arrive (e.g. a 2 s TTL).
There are no hardware, clock, filesystem, or gesture-template dependencies.
"""

import math
from collections.abc import Mapping
from numbers import Integral, Real


def _finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


class QuickMotionDetector:
    """Feed device milliseconds, optional uint32 n, and acceleration in g.

    ``feed`` returns one derived ``type: quick_motion`` event per manual-reset
    cycle. ``ready`` means a valid quiet window was observed since construction,
    reset or a stream reset. Forward loss never joins two pulse fragments or
    helps finish an initial quiet window. ``latched`` changes only on a trigger,
    ``reset`` or explicit ``restore_latch``; all methods are synchronous.
    """

    def __init__(self, *, threshold_g=0.80, sustain_ms=120, min_pulse_samples=5,
                 quiet_deviation_g=0.12, settle_ms=300, cooldown_ms=400,
                 max_sample_gap_ms=100):
        settings = (threshold_g, sustain_ms, quiet_deviation_g, settle_ms,
                    cooldown_ms, max_sample_gap_ms)
        if any(not _finite(value) or value <= 0 for value in settings):
            raise ValueError("quick-motion thresholds must be positive finite numbers")
        if quiet_deviation_g >= threshold_g:
            raise ValueError("quiet deviation must be below the trigger threshold")
        if isinstance(min_pulse_samples, bool) or not isinstance(min_pulse_samples, Integral) or min_pulse_samples < 3:
            raise ValueError("a pulse must require at least three samples")
        self.threshold_g, self.sustain_ms = threshold_g, sustain_ms
        self.min_pulse_samples = min_pulse_samples
        self.quiet_deviation_g, self.settle_ms = quiet_deviation_g, settle_ms
        self.cooldown_ms, self.max_sample_gap_ms = cooldown_ms, max_sample_gap_ms
        self._latched = False
        self._cooldown_pending = False
        self._clear_stream()
        self.last_observation = {"kind": "settling"}

    @property
    def ready(self):
        return self._ready

    @property
    def latched(self):
        return self._latched

    @property
    def phase(self):
        if not self._ready:
            return "cooldown" if self._cooldown_pending else "settling"
        if self._latched:
            return "latched"
        return "candidate" if self._pulse_start is not None else "armed"

    def _clear_pulse(self):
        self._pulse_start = None
        self._pulse_count = 0
        self._peak_acceleration = self._peak_deviation = 0.0

    def _clear_stream(self):
        self._ready = False
        self._previous = None
        self._quiet_since = None
        self._quiet_count = 0
        self._cooldown_started = None
        self._clear_pulse()

    def reset(self):
        """Manually release the latch; require cooldown and fresh quiet samples."""
        self._latched = False
        self._cooldown_pending = True
        self._clear_stream()
        self.last_observation = {"kind": "manual_reset"}

    def restore_latch(self):
        """Restore only a previously verified latch; never restore live readiness."""
        self._latched = True
        self._cooldown_pending = False
        self._clear_stream()
        self.last_observation = {"kind": "latch_restored"}

    def feed(self, sample):
        """Return a quick-motion event, or None; never consume gyroscope data.

        ``peak_acceleration_g`` is the largest acceleration magnitude in the
        confirmation pulse. ``peak_deviation_g`` is its largest departure from
        1 g; the two differ for low-acceleration pulses. ``duration_ms`` covers
        the observed pulse through confirmation, not a complete gesture.
        """
        try:
            if not isinstance(sample, Mapping):
                raise ValueError("invalid sample")
            values = [sample[key] for key in ("t", "ax", "ay", "az")]
            if not all(map(_finite, values)) or values[0] < 0:
                raise ValueError("invalid acceleration or timestamp")
            timestamp = float(values[0])
            number = sample.get("n")
            if number is not None and (isinstance(number, bool) or not isinstance(number, Integral)
                                       or not 0 <= number <= 0xFFFFFFFF):
                raise ValueError("invalid sample number")
            magnitude = math.hypot(*values[1:])
            if not math.isfinite(magnitude):
                raise ValueError("invalid acceleration magnitude")
        except (KeyError, ValueError, TypeError, OverflowError):
            self._clear_stream()
            self.last_observation = {"kind": "stream_reset", "reason": "invalid_sample"}
            return None
        if self._previous is not None:
            old_t, old_n = self._previous
            elapsed = timestamp - old_t
            delta = ((number - old_n) & 0xFFFFFFFF) if number is not None and old_n is not None else None
            if elapsed <= 0 or (delta is not None and not 0 < delta < 0x80000000):
                self._clear_stream()
                self._previous = (timestamp, number)
                self.last_observation = {"kind": "stream_reset", "reason": "sample_discontinuity"}
                return None
            if elapsed > self.max_sample_gap_ms or (delta is not None and delta > 1):
                keep_ready = self._ready and (self._latched or elapsed <= self.max_sample_gap_ms)
                if keep_ready:
                    self._clear_pulse()
                    self._quiet_since = None
                    self._quiet_count = 0
                else:
                    self._clear_stream()
                self._previous = (timestamp, number)
                self.last_observation = {"kind": "sample_gap", "ready_preserved": keep_ready,
                                         "gap_ms": elapsed}
                # The arrival after a gap never completes a pre-gap pulse or
                # quiet window. Start new evidence with the next sample.
                return None
        self._previous = (timestamp, number)
        deviation = abs(magnitude - 1.0)
        if not self._ready:
            if self._cooldown_pending and self._cooldown_started is None:
                self._cooldown_started = timestamp
            if deviation <= self.quiet_deviation_g:
                if self._quiet_since is None:
                    self._quiet_since = timestamp
                self._quiet_count += 1
            else:
                self._quiet_since = None
                self._quiet_count = 0
            quiet_ms = timestamp - self._quiet_since if self._quiet_since is not None else 0
            cooled = not self._cooldown_pending or timestamp - self._cooldown_started >= self.cooldown_ms
            if self._quiet_count >= 5 and quiet_ms >= self.settle_ms and cooled:
                self._ready = True
                self._cooldown_pending = False
            self.last_observation = {"kind": self.phase, "quiet_ms": quiet_ms}
            return None
        if self._latched:
            return None
        if deviation < self.threshold_g:
            self._clear_pulse()
            self.last_observation = {"kind": "armed"}
            return None
        if self._pulse_start is None:
            self._pulse_start = timestamp
        self._pulse_count += 1
        self._peak_acceleration = max(self._peak_acceleration, magnitude)
        self._peak_deviation = max(self._peak_deviation, deviation)
        duration = timestamp - self._pulse_start
        self.last_observation = {"kind": "candidate", "duration_ms": duration,
                                 "sample_count": self._pulse_count}
        if duration < self.sustain_ms or self._pulse_count < self.min_pulse_samples:
            return None
        event = {"type": "quick_motion", "device_time_ms": timestamp,
                 "peak_acceleration_g": self._peak_acceleration,
                 "peak_deviation_g": self._peak_deviation, "duration_ms": duration}
        self._latched = True
        self._clear_pulse()
        self.last_observation = {"kind": "triggered", **event}
        return event
