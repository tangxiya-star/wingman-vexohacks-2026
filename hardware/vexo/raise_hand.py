"""Detect a quick overhead gesture from Vexo motion samples, without device I/O.

The wearer must keep their arm naturally down during the initial calibration.
The thresholds below are demo assumptions awaiting wrist testing. A gravity
direction more than 130 degrees from that pose is a gesture proxy, not a
measurement of hand height or proof that the hand is above the head.

Like the SDK gesture trainer, this uses device sample time and separates motion
from stillness. It keeps constant-sized state, rather than recording gestures.
"""

import math
from numbers import Integral, Real


CALIBRATION_MS = 800
MAX_SAMPLE_GAP_MS = 200
STILL_GYRO_DPS = 35
STILL_MAGNITUDE_G = (0.85, 1.15)
STILL_DIRECTION_DEG = 8
START_GYRO_DPS = 40
DOWN_ANGLE_DEG = 25
OVERHEAD_ANGLE_DEG = 130
QUICK_PEAK_GYRO_DPS = 120
MAX_GESTURE_MS = 1800  # Includes the stable confirmation at the target.
TARGET_HOLD_MS = 150
REARM_HOLD_MS = 300


def _angle(a, b):
    cosine = max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))
    return math.degrees(math.acos(cosine))


def _unit(vector):
    length = math.hypot(*vector)
    return tuple(value / length for value in vector)


class _StillWindow:
    """Continuous stillness, compared with a fixed anchor to reject drift."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.since = None
        self.anchor = None
        self.mean = None
        self.count = 0

    def feed(self, t, direction, qualifies):
        if not qualifies:
            self.reset()
            return 0
        if self.since is None or _angle(self.anchor, direction) > STILL_DIRECTION_DEG:
            self.since, self.anchor, self.mean, self.count = t, direction, direction, 1
        else:
            # A bounded running average; no sample array grows during a stream.
            self.count = min(1024, self.count + 1)
            self.mean = tuple(old + (new - old) / self.count
                              for old, new in zip(self.mean, direction))
        return t - self.since

    @property
    def direction(self):
        return _unit(self.mean)


class RaiseHandDetector:
    """Feed mapping/SDK Message samples containing t, ax..az, gx..gz and optional n.

    ``t`` is device milliseconds; acceleration is in g and gyro in degrees/s.
    Expected input is 50 Hz, but all windows use elapsed time, not sample count.
    The 1800 ms candidate deadline includes movement, settling and the final
    150 ms stable confirmation; it is not an extra timeout after arrival.
    ``sample_count`` counts structurally valid samples since ``calibrate()``.
    A bad/discontinuous stream keeps the baseline but requires a fresh, stable
    down pose. Only explicit ``calibrate()`` discards the known baseline.
    """

    def __init__(self):
        self._calibration = _StillWindow()
        self._target = _StillWindow()
        self._down = _StillWindow()
        self.calibrate()

    @property
    def phase(self):
        return self._phase

    @property
    def baseline(self):
        return self._baseline

    @property
    def sample_count(self):
        return self._sample_count

    def calibrate(self):
        """Forget the down pose and wait for a new continuous still calibration."""
        self._baseline = None
        self._sample_count = 0
        self._interrupt()

    def calibration_profile(self):
        """Return an independent JSON-compatible down-pose profile, or None."""
        if self._baseline is None:
            return None
        return {"version": 1, "baseline": list(self._baseline)}

    def restore_calibration(self, profile):
        """Restore a down pose, requiring actual stable down samples to rearm.

        Accept version 1 (or an omitted version). Reject invalid input without
        changing the current baseline, candidate or stream continuity state.
        """
        if not isinstance(profile, dict):
            raise ValueError("calibration profile must be an object")
        version = profile.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, Integral) or version != 1:
            raise ValueError("unsupported calibration profile version")
        baseline = profile.get("baseline")
        if not isinstance(baseline, (list, tuple)) or len(baseline) != 3:
            raise ValueError("calibration baseline must contain three finite numbers")
        try:
            if any(isinstance(value, bool) or not isinstance(value, Real)
                   or not math.isfinite(value) for value in baseline):
                raise ValueError("calibration baseline must contain three finite numbers")
            vector = tuple(float(value) for value in baseline)
        except (OverflowError, TypeError) as error:
            raise ValueError("calibration baseline must contain three finite numbers") from error
        scale = max(abs(value) for value in vector)
        if scale == 0:
            raise ValueError("calibration baseline must be nonzero")
        # Scale before normalizing so finite extreme values cannot overflow or
        # underflow the norm. Commit only after the complete profile validates.
        normalized = _unit(tuple(value / scale for value in vector))
        self._baseline = normalized
        self._interrupt()

    def _reset_motion(self):
        self._calibration.reset()
        self._target.reset()
        self._down.reset()
        self._started_at = None
        self._peak_gyro = 0

    def _interrupt(self):
        self._reset_motion()
        self._phase = "calibrating" if self._baseline is None else "wait_down"
        self._last_t = None
        self._last_n = None

    @staticmethod
    def _parse(sample):
        values = tuple(sample[key] for key in ("t", "ax", "ay", "az", "gx", "gy", "gz"))
        if any(isinstance(value, bool) or not isinstance(value, Real)
               or not math.isfinite(value) for value in values):
            raise ValueError("motion fields must be finite numbers")
        t, *axes = map(float, values)
        n = sample.get("n")
        if t < 0 or (n is not None and (isinstance(n, bool) or not isinstance(n, Integral)
                                       or not 0 <= n <= 0xFFFFFFFF)):
            raise ValueError("invalid device time or sequence number")
        acceleration, gyro = tuple(axes[:3]), math.hypot(*axes[3:])
        magnitude = math.hypot(*acceleration)
        if magnitude == 0 or not math.isfinite(magnitude) or not math.isfinite(gyro):
            raise ValueError("invalid motion vector")
        return t, n, tuple(value / magnitude for value in acceleration), magnitude, gyro

    def feed(self, sample):
        """Return one hand_raise event on confirmation, otherwise None."""
        try:
            t, n, direction, magnitude, gyro = self._parse(sample)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            self._interrupt()
            return None
        self._sample_count += 1
        broken = (self._last_t is not None
                  and (t <= self._last_t or t - self._last_t > MAX_SAMPLE_GAP_MS))
        broken |= (n is not None and self._last_n is not None
                   and n != (self._last_n + 1) & 0xFFFFFFFF)
        if broken:
            self._interrupt()
        self._last_t, self._last_n = t, n
        if broken:
            return None  # This frame establishes time, never completes old motion.

        quiet = (STILL_MAGNITUDE_G[0] <= magnitude <= STILL_MAGNITUDE_G[1]
                 and gyro < STILL_GYRO_DPS)
        if self._phase == "calibrating":
            if self._calibration.feed(t, direction, quiet) >= CALIBRATION_MS:
                self._baseline = self._calibration.direction
                self._reset_motion()
                self._phase = "armed"
            return None

        angle = _angle(self._baseline, direction)
        down = quiet and angle < DOWN_ANGLE_DEG
        if self._phase == "wait_down":
            if self._down.feed(t, direction, down) >= REARM_HOLD_MS:
                self._reset_motion()
                self._phase = "armed"
            return None

        if self._phase == "armed":
            if gyro < START_GYRO_DPS and angle < DOWN_ANGLE_DEG:
                return None
            self._phase = "raising"
            self._started_at = t

        self._peak_gyro = max(self._peak_gyro, gyro)
        elapsed = t - self._started_at
        if elapsed > MAX_GESTURE_MS:
            self._reset_motion()
            self._phase = "wait_down"
            return None
        target_ms = self._target.feed(t, direction, quiet and angle >= OVERHEAD_ANGLE_DEG)
        if target_ms >= TARGET_HOLD_MS and self._peak_gyro >= QUICK_PEAK_GYRO_DPS:
            event = dict(type="hand_raise", gesture="quick_overhead", device_time_ms=t,
                         duration_ms=elapsed, angle_deg=_angle(self._baseline, self._target.direction),
                         peak_gyro_dps=self._peak_gyro)
            self._reset_motion()
            self._phase = "wait_down"
            return event
        if self._down.feed(t, direction, down) >= REARM_HOLD_MS:
            self._reset_motion()
            self._phase = "armed"
        return None
