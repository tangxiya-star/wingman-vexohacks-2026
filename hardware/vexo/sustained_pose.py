"""Estimate a held wrist orientation, separately from quick gesture events.

Explicit down/up calibration uses 800 ms of samples, not a motion trajectory.
At least 80% of a window must have 0.8–1.2 g acceleration and directions within
10 degrees of a robust centre; median angular speed must be below 80 deg/s.
These are demo noise guards, not a measured accuracy guarantee. The guards
allow isolated spikes without treating sustained movement as a held pose.

Classification uses a rolling 250 ms window with at least 200 ms of evidence.
Its direction must be within 30 degrees of the nearest calibrated anchor and
at least 15 degrees closer to it than the other anchor. An ambiguous/unstable
window clears the state immediately; reacquisition requires a qualifying
window, never a quick-raise event. There is no indefinite "up" latch.

This measures wrist orientation relative to gravity, not absolute hand height.
It cannot distinguish positions with the same orientation. Calibrate each
wearer's current mounting; this module never imports someone else's gestures.
"""

import math
from collections import deque
from collections.abc import Mapping
from numbers import Integral, Real
from statistics import median


AXES = ("ax", "ay", "az", "gx", "gy", "gz")


def _finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _unit(vector):
    magnitude = math.hypot(*vector)
    if not math.isfinite(magnitude) or magnitude == 0:
        raise ValueError("direction must have nonzero finite magnitude")
    return tuple(value / magnitude for value in vector)


def _angle(one, other):
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(a * b for a, b in zip(one, other))))))


class SustainedPoseEstimator:
    """Feed raw ``t,n,ax,ay,az,gx,gy,gz`` samples; expose down/up/unknown.

    ``t`` is device milliseconds; ``n`` is optional uint32. Calibration failure
    or cancellation preserves the previously accepted profile. A profile may
    contain one anchor while setup is incomplete; ``ready`` requires both.
    Successful down calibration clears the old up anchor. Unstable calibration
    expires after 10 seconds of device time. When samples stop altogether, the
    caller must enforce freshness (the application's state reader uses 2 s).
    """

    def __init__(self, *, calibration_ms=800, calibration_timeout_ms=10000, window_ms=250, stable_ms=200,
                 max_sample_gap_ms=200, gyro_limit_dps=80, dispersion_deg=10,
                 anchor_angle_deg=30, margin_deg=15, min_separation_deg=60):
        settings = (calibration_ms, calibration_timeout_ms, window_ms, stable_ms, max_sample_gap_ms,
                    gyro_limit_dps, dispersion_deg, anchor_angle_deg,
                    margin_deg, min_separation_deg)
        if any(not _finite(value) or value <= 0 for value in settings):
            raise ValueError("pose thresholds must be positive finite numbers")
        if not stable_ms <= window_ms <= calibration_ms:
            raise ValueError("require stable_ms <= window_ms <= calibration_ms")
        if calibration_timeout_ms <= calibration_ms:
            raise ValueError("calibration timeout must exceed its required stable window")
        if any(value >= 180 for value in (dispersion_deg, anchor_angle_deg, margin_deg)):
            raise ValueError("pose angle thresholds must be below 180 degrees")
        if not 60 <= min_separation_deg <= 180:
            raise ValueError("anchors must be separated by at least 60 degrees")
        self.calibration_ms, self.window_ms, self.stable_ms = calibration_ms, window_ms, stable_ms
        self.calibration_timeout_ms = calibration_timeout_ms
        self.max_sample_gap_ms = max_sample_gap_ms
        self.gyro_limit_dps, self.dispersion_deg = gyro_limit_dps, dispersion_deg
        self.anchor_angle_deg, self.margin_deg = anchor_angle_deg, margin_deg
        self.min_separation_deg = min_separation_deg
        self._anchors = {"down": None, "up": None}
        self._window = deque(maxlen=2000)
        self._calibration_window = deque(maxlen=2000)
        self._previous = None
        self._calibrating = None
        self._calibration_started_t = None
        self._state = "unknown"
        self.model_revision = 0
        self.last_observation = {"kind": "uncalibrated"}

    @property
    def ready(self):
        return all(self._anchors[label] is not None for label in ("down", "up"))

    @property
    def raised(self):
        return self._state == "up"

    @property
    def state(self):
        return self._state

    @property
    def calibrating(self):
        return self._calibrating

    def _clear_motion(self):
        self._window.clear()
        self._calibration_window.clear()
        self._previous = None
        self._state = "unknown"

    def begin_calibration(self, pose):
        if pose not in ("down", "up"):
            raise ValueError("calibration pose must be down or up")
        self._clear_motion()
        self._calibrating = pose
        self._calibration_started_t = None
        self.last_observation = {"kind": "calibration_started", "pose": pose}

    def cancel_calibration(self):
        if self._calibrating is None:
            return
        pose, self._calibrating = self._calibrating, None
        self._calibration_started_t = None
        self._clear_motion()
        self.last_observation = {"kind": "calibration_cancelled", "pose": pose}

    def calibration_profile(self):
        return {"version": 1, **{label: list(vector) if vector is not None else None
                                  for label, vector in self._anchors.items()}}

    def restore_calibration(self, profile):
        if (not isinstance(profile, Mapping) or type(profile.get("version")) is not int
                or profile["version"] != 1 or not all(label in profile for label in ("down", "up"))):
            raise ValueError("pose profile must have version 1 and down/up anchors")
        anchors = {}
        for label in ("down", "up"):
            vector = profile[label]
            if vector is None:
                anchors[label] = None
                continue
            if (not isinstance(vector, (tuple, list)) or len(vector) != 3
                    or not all(map(_finite, vector))
                    or not math.isclose(math.hypot(*vector), 1.0, rel_tol=0, abs_tol=1e-6)):
                raise ValueError("pose anchors must be finite unit vectors")
            anchors[label] = _unit(tuple(map(float, vector)))
        if all(anchors.values()) and _angle(anchors["down"], anchors["up"]) + 1e-9 < self.min_separation_deg:
            raise ValueError("down and up anchors must be at least 60 degrees apart")
        self._anchors = anchors
        self._calibrating = None
        self._calibration_started_t = None
        self._clear_motion()
        self.model_revision += 1
        self.last_observation = {"kind": "calibration_restored", "ready": self.ready}

    @staticmethod
    def _append(window, sample, duration):
        window.append(sample)
        # Keep one sample at/before the boundary. Dropping every older sample
        # would make an 800 ms calibration require an exact 800 ms timestamp
        # difference, which jittered real device timestamps need not provide.
        while len(window) > 1 and sample["t"] - window[1]["t"] >= duration:
            window.popleft()

    def _direction(self, window):
        """A robust mean after median-centre angular outlier rejection."""
        if len(window) < 5:
            return None, "insufficient_samples"
        usable = [row for row in window if 0.8 <= row["magnitude"] <= 1.2]
        needed = math.ceil(0.8 * len(window))
        if len(usable) < needed:
            return None, "acceleration"
        if median(row["gyro"] for row in window) >= self.gyro_limit_dps:
            return None, "rotation"
        try:
            centre = _unit(tuple(median(row["direction"][axis] for row in usable) for axis in range(3)))
            inliers = [row["direction"] for row in usable
                       if _angle(centre, row["direction"]) <= self.dispersion_deg]
            if len(inliers) < needed:
                return None, "dispersion"
            return _unit(tuple(sum(row[axis] for row in inliers) / len(inliers) for axis in range(3))), None
        except ValueError:
            return None, "dispersion"

    def _calibrate_window(self):
        pose = self._calibrating
        span = self._calibration_window[-1]["t"] - self._calibration_window[0]["t"]
        direction, reason = self._direction(self._calibration_window)
        if span < self.calibration_ms or direction is None:
            self.last_observation = {"kind": "calibration_wait", "pose": pose,
                                     "duration_ms": span,
                                     "reason": reason or "duration"}
            return
        # A new explicit down anchor starts a new mounting calibration. Clear
        # its old up only after success; a failed/cancelled attempt is atomic.
        other = self._anchors["down"] if pose == "up" else None
        if other is not None and _angle(direction, other) + 1e-9 < self.min_separation_deg:
            self._calibrating = None
            self._calibration_started_t = None
            self._clear_motion()
            self.last_observation = {"kind": "calibration_rejected", "pose": pose,
                                     "reason": "anchors_too_close"}
            return
        self._anchors[pose] = direction
        if pose == "down":
            self._anchors["up"] = None
        self._calibrating = None
        self._calibration_started_t = None
        self._clear_motion()
        self.model_revision += 1
        self.last_observation = {"kind": "calibration_complete", "pose": pose,
                                 "ready": self.ready}

    def feed(self, sample):
        """Return the latest state; malformed/discontinuous input clears it.

        A missing ``n`` is allowed. When present on adjacent samples it must
        advance modulo uint32. Invalid input does not destroy calibration.
        """
        try:
            if not isinstance(sample, Mapping):
                raise ValueError("invalid sample")
            values = [sample[key] for key in ("t", *AXES)]
            if not all(map(_finite, values)) or values[0] < 0:
                raise ValueError("invalid sample")
            number = sample.get("n")
            if number is not None and (isinstance(number, bool) or not isinstance(number, Integral)
                                       or not 0 <= number <= 0xFFFFFFFF):
                raise ValueError("invalid sample number")
            timestamp = float(values[0])
            acceleration = tuple(map(float, values[1:4]))
            magnitude = math.hypot(*acceleration)
            gyro = math.hypot(*values[4:7])
            if not math.isfinite(gyro):
                raise ValueError("invalid angular speed")
            direction = _unit(acceleration)
        except (KeyError, TypeError, ValueError, OverflowError):
            self._clear_motion()
            self.last_observation = {"kind": "stream_reset", "reason": "invalid_sample"}
            return self._state
        if self._calibrating is not None:
            if self._calibration_started_t is None:
                self._calibration_started_t = timestamp
            elif timestamp - self._calibration_started_t >= self.calibration_timeout_ms:
                pose, self._calibrating = self._calibrating, None
                self._calibration_started_t = None
                self._clear_motion()
                self.last_observation = {"kind": "calibration_failed", "pose": pose,
                                         "reason": "unstable_timeout"}
                return self._state
        if self._previous is not None:
            old_t, old_n = self._previous
            if (timestamp <= old_t or timestamp - old_t > self.max_sample_gap_ms
                    or (number is not None and old_n is not None
                        and number != ((old_n + 1) & 0xFFFFFFFF))):
                self._clear_motion()
                self._previous = (timestamp, number)
                self.last_observation = {"kind": "stream_reset", "reason": "sample_discontinuity"}
                if timestamp <= old_t and self._calibrating is not None:
                    pose, self._calibrating = self._calibrating, None
                    self._calibration_started_t = None
                    self.last_observation = {"kind": "calibration_failed", "pose": pose,
                                             "reason": "timestamp_reset"}
                return self._state
        self._previous = (timestamp, number)
        row = {"t": timestamp, "direction": direction, "magnitude": magnitude, "gyro": gyro}
        if self._calibrating is not None:
            self._append(self._calibration_window, row, self.calibration_ms)
            self._calibrate_window()
            return self._state
        if not self.ready:
            self._state = "unknown"
            return self._state
        self._append(self._window, row, self.window_ms)
        span = self._window[-1]["t"] - self._window[0]["t"]
        direction, reason = self._direction(self._window)
        state = "unknown"
        observation = {"kind": "pose", "duration_ms": span}
        if direction is not None and span >= self.stable_ms:
            angles = {label: _angle(direction, anchor) for label, anchor in self._anchors.items()}
            label = min(angles, key=angles.get)
            other = "up" if label == "down" else "down"
            if angles[label] <= self.anchor_angle_deg and angles[other] - angles[label] >= self.margin_deg:
                state = label
            observation.update(angle_down_deg=angles["down"], angle_up_deg=angles["up"])
        else:
            observation["reason"] = reason or "duration"
        self._state = state
        observation["state"] = state
        self.last_observation = observation
        return self._state
