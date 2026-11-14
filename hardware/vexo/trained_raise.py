"""User-trained down/overhead gestures using the official Vexo template matcher.

Pose angles label demonstrations and rearm the detector; they do not measure
hand height. Recognition uses recorded six-axis motion templates, not the old
130-degree/1800-ms trigger. Training fit is not independent validation.
"""

import math
from numbers import Integral, Real

from gesture_matcher import NOT_SURE, START_ACCEL, START_GYRO, Segmenter, distance, match, to_shape
from raise_hand import RaiseHandDetector


def _finite(value):
    try:
        return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _unit(vector):
    length = math.hypot(*vector)
    return tuple(value / length for value in vector)


def _angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))


class _QuietPose:
    def __init__(self):
        self.reset()

    def reset(self):
        self.since = self.anchor = self.mean = None
        self.count = 0

    def feed(self, t, direction, quiet):
        if not quiet:
            self.reset()
            return 0
        if self.since is None or _angle(self.anchor, direction) > 8:
            self.since, self.anchor, self.mean, self.count = t, direction, direction, 1
        else:
            self.count = min(1024, self.count + 1)
            self.mean = tuple(old + (new - old) / self.count for old, new in zip(self.mean, direction))
        return t - self.since


class TrainedRaiseDetector:
    """Collect three raises and three lowers, then classify complete segments.

    ``calibrate`` clears the model and learns an explicitly requested down pose.
    ``begin_training`` starts a fresh template collection; it may be called while
    down-pose calibration is still running. Imported models always await a real
    stable down pose. All motion timing uses the device's ``t`` in milliseconds.
    """

    def __init__(self, *, peak_gyro_dps=120, max_duration_ms=2200,
                 down_angle_deg=35, away_angle_deg=60, rearm_ms=300,
                 match_limit=NOT_SURE, max_sample_gap_ms=200,
                 release_angle_deg=30, release_hold_ms=150):
        settings = (peak_gyro_dps, max_duration_ms, down_angle_deg, away_angle_deg,
                    rearm_ms, match_limit, max_sample_gap_ms, release_angle_deg, release_hold_ms)
        if any(not _finite(value) or value <= 0 for value in settings):
            raise ValueError("detector thresholds must be positive finite numbers")
        if not down_angle_deg < away_angle_deg < 180:
            raise ValueError("pose thresholds must satisfy down < away < 180 degrees")
        self.peak_gyro_dps, self.max_duration_ms = peak_gyro_dps, max_duration_ms
        self.down_angle_deg, self.away_angle_deg = down_angle_deg, away_angle_deg
        self.rearm_ms, self.max_sample_gap_ms = rearm_ms, max_sample_gap_ms
        if release_angle_deg >= 180:
            raise ValueError("release angle must be below 180 degrees")
        self.release_angle_deg, self.release_hold_ms = release_angle_deg, release_hold_ms
        self._default_limit = match_limit
        self.limit = match_limit
        self._calibrator = RaiseHandDetector()
        self._segmenter = Segmenter()
        self._quiet, self._down, self._released_pose = _QuietPose(), _QuietPose(), _QuietPose()
        self._templates = []
        self._training = False
        self.model_revision = 0
        self.last_observation = {}
        self.sample_count = 0
        self._clear_stream()

    @property
    def baseline(self):
        return self._calibrator.baseline

    @property
    def phase(self):
        return self._phase

    @property
    def training(self):
        return self._training

    @property
    def training_counts(self):
        return {label: sum(item["label"] == label for item in self._templates)
                for label in ("raise", "lower")}

    @property
    def ready(self):
        return all(count == 3 for count in self.training_counts.values())

    @property
    def raised(self):
        """A recognized raise still held near its confirmed orientation.

        A quiet pose at least 30 degrees away for 150 ms clears this flag,
        including a shoulder-level pose. This is an orientation proxy: large
        wrist rotations can clear it, and translation without rotation cannot
        be measured as hand height. Stream freshness is enforced by the reader.
        """
        return self._raised

    def _clear_stream(self):
        self._segmenter.reset()
        self._quiet.reset()
        self._down.reset()
        self._released_pose.reset()
        self._raised = False
        self._raised_direction = None
        self._previous = None
        self._last_quiet_direction = None
        self._last_quiet_at = None
        self._start_direction = None
        self._started_armed = False
        self._armed = False
        self._phase = "calibrating" if self.baseline is None else "wait_down"
        if self.baseline is None:
            self._calibrator.calibrate()

    def calibrate(self):
        self._calibrator.calibrate()
        self._templates = []
        self._training = False
        self.limit = self._default_limit
        self.sample_count = 0
        self.model_revision += 1
        self._clear_stream()
        self.last_observation = {"kind": "calibration_started"}

    def begin_training(self):
        if self._templates:
            self.model_revision += 1
        self._templates = []
        self.limit = self._default_limit
        self._training = True
        self._clear_stream()
        self.last_observation = {"kind": "training_started", "counts": self.training_counts}

    def calibration_profile(self):
        if self.baseline is None:
            return None
        return {"version": 2, "baseline": list(self.baseline), "limit": self.limit,
                "templates": [{"label": item["label"], "shape": list(item["shape"])}
                              for item in self._templates]}

    def restore_calibration(self, profile):
        if not isinstance(profile, dict):
            raise ValueError("model profile must be an object")
        version = profile.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, Integral) or version not in (1, 2):
            raise ValueError("unsupported model profile version")
        calibrator = RaiseHandDetector()
        calibrator.restore_calibration({"baseline": profile.get("baseline")})
        templates, limit = [], self._default_limit
        if version == 2:
            rows, limit = profile.get("templates"), profile.get("limit")
            if not isinstance(rows, list) or len(rows) > 6 or not _finite(limit) or limit <= 0:
                raise ValueError("model needs at most six templates and a finite positive limit")
            counts = {"raise": 0, "lower": 0}
            for item in rows:
                if (not isinstance(item, dict) or not isinstance(item.get("label"), str)
                        or item["label"] not in counts):
                    raise ValueError("template label must be raise or lower")
                shape = item.get("shape")
                if not isinstance(shape, (list, tuple)) or len(shape) != 144 or not all(map(_finite, shape)):
                    raise ValueError("template shape must contain 144 finite numbers")
                counts[item["label"]] += 1
                if counts[item["label"]] > 3:
                    raise ValueError("at most three templates per label")
                templates.append({"label": item["label"], "shape": [float(value) for value in shape]})
            try:
                if any(not math.isfinite(distance(a["shape"], b["shape"]))
                       for i, a in enumerate(templates) for b in templates[i + 1:]):
                    raise ValueError("template distances must be finite")
            except OverflowError as error:
                raise ValueError("template values overflow distance calculation") from error
        self._calibrator, self._templates, self.limit = calibrator, templates, float(limit)
        self._training = False
        self.model_revision += 1
        self._clear_stream()
        self.last_observation = {"kind": "model_restored", "ready": self.ready,
                                 "counts": self.training_counts}

    def _observe_segment(self, gesture, current, direction, endpoint_quiet):
        start_angle = _angle(self.baseline, self._start_direction) if self._start_direction else None
        end_angle = _angle(self.baseline, direction)
        duration = gesture[-1]["t"] - gesture[0]["t"]
        peak = max(math.hypot(*(row[key] for key in ("gx", "gy", "gz"))) for row in gesture)
        shape = to_shape(gesture)
        observation = dict(kind="gesture", device_time_ms=current["t"], duration_ms=duration,
                           start_angle_deg=start_angle, angle_deg=end_angle, peak_gyro_dps=peak,
                           started_armed=self._started_armed, endpoint_quiet=endpoint_quiet)
        if self.training:
            label = None
            if start_angle is not None and endpoint_quiet:
                if start_angle <= self.down_angle_deg and end_angle > self.away_angle_deg:
                    label = "raise"
                elif start_angle > self.away_angle_deg and end_angle <= self.down_angle_deg:
                    label = "lower"
            if label and self.training_counts[label] < 3:
                self._templates.append({"label": label, "shape": shape})
                self.model_revision += 1
                observation.update(kind="training_recorded", label=label)
                if self.ready:
                    positives = [item["shape"] for item in self._templates if item["label"] == "raise"]
                    nearest = [min(distance(one, other) for j, other in enumerate(positives) if i != j)
                               for i, one in enumerate(positives)]
                    self.limit = max(self._default_limit, 1.25 * max(nearest) + 0.05)
                    self._training = False
            else:
                observation.update(kind="training_skipped", label=label,
                                   reason="class_full" if label else "endpoints_do_not_label_a_raise_or_lower")
            observation.update(counts=self.training_counts, ready=self.ready, limit=self.limit)
            self.last_observation = observation
            return None

        matched = match(shape, self._templates, self.limit) if self.ready else {"label": None, "distance": None}
        observation.update(label=matched["label"], match_distance=matched["distance"], ready=self.ready)
        accepted = (self.ready and matched["label"] == "raise" and self._started_armed
                    and start_angle is not None and start_angle <= self.down_angle_deg
                    and peak >= self.peak_gyro_dps and duration <= self.max_duration_ms)
        observation["accepted"] = accepted
        self.last_observation = observation
        if not accepted:
            return None
        self._armed = False
        self._down.reset()
        self._phase = "wait_down"
        self._raised = True
        self._raised_direction = direction
        self._released_pose.reset()
        return dict(type="hand_raise", gesture="quick_overhead", device_time_ms=current["t"],
                    duration_ms=duration, angle_deg=end_angle, peak_gyro_dps=peak,
                    match_distance=matched["distance"])

    def feed(self, sample):
        try:
            values = [sample[key] for key in ("t", "ax", "ay", "az", "gx", "gy", "gz")]
            n = sample.get("n")
            if not all(map(_finite, values)) or values[0] < 0:
                raise ValueError("invalid motion fields")
            if n is not None and (isinstance(n, bool) or not isinstance(n, Integral) or not 0 <= n <= 0xFFFFFFFF):
                raise ValueError("invalid sample number")
            clean = dict(zip(("t", "ax", "ay", "az", "gx", "gy", "gz"), map(float, values)))
            clean["n"] = n
            acceleration = tuple(clean[key] for key in ("ax", "ay", "az"))
            magnitude = math.hypot(*acceleration)
            gyro = math.hypot(*(clean[key] for key in ("gx", "gy", "gz")))
            if magnitude == 0 or not math.isfinite(magnitude) or not math.isfinite(gyro):
                raise ValueError("invalid motion magnitude")
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
            self._clear_stream()
            self.last_observation = {"kind": "stream_reset", "reason": "invalid_sample"}
            return None
        self.sample_count += 1
        previous = self._previous
        broken = previous is not None and (clean["t"] <= previous["t"]
                 or clean["t"] - previous["t"] > self.max_sample_gap_ms
                 or (n is not None and previous["n"] is not None
                     and n != (previous["n"] + 1) & 0xFFFFFFFF))
        if broken:
            self._clear_stream()
            self._previous = clean
            self.last_observation = {"kind": "stream_reset", "reason": "sample_discontinuity",
                                     "device_time_ms": clean["t"]}
            return None
        self._previous = clean
        direction = _unit(acceleration)
        if self.baseline is None:
            self._calibrator.feed(clean)
            if self.baseline is not None:
                self._clear_stream()
                self._armed, self._phase = True, "armed"
                self._last_quiet_direction = self.baseline
                self._last_quiet_at = clean["t"]
                self.last_observation = {"kind": "calibration_complete"}
            return None

        moving = gyro > START_GYRO or (previous is not None and math.hypot(
            *(clean[key] - previous[key] for key in ("ax", "ay", "az"))) > START_ACCEL)
        quiet = not moving and gyro < 35 and 0.85 <= magnitude <= 1.15
        if self._raised:
            departed = quiet and _angle(self._raised_direction, direction) >= self.release_angle_deg
            if self._released_pose.feed(clean["t"], direction, departed) >= self.release_hold_ms:
                self._raised = False
                self._raised_direction = None
                self._released_pose.reset()
        had_segment = bool(self._segmenter.samples)
        # This wrapper handles uint32 sequence rollover and stricter gaps itself.
        gesture = self._segmenter.feed({**clean, "n": None})
        if not had_segment and self._segmenter.samples:
            self._start_direction = (self._last_quiet_direction if self._last_quiet_at is not None
                                     and clean["t"] - self._last_quiet_at <= 400 else None)
            self._started_armed = self._armed
            self._armed = False
            self._down.reset()
            self._phase = "raising" if self._started_armed else "wait_down"
        if self._quiet.feed(clean["t"], direction, quiet) >= 150:
            self._last_quiet_direction = _unit(self._quiet.mean)
            self._last_quiet_at = clean["t"]
        down_ms = self._down.feed(clean["t"], direction,
                                  quiet and _angle(self.baseline, direction) <= self.down_angle_deg)
        if down_ms >= self.rearm_ms and not self._segmenter.samples:
            self._armed, self._phase = True, "armed"
        event = self._observe_segment(gesture, clean, direction, quiet) if gesture is not None else None
        if had_segment and not self._segmenter.samples:
            if gesture is None:
                self.last_observation = {"kind": "segment_skipped", "reason": "official_segment_limits"}
            self._start_direction = None
            self._started_armed = False
            self._phase = "armed" if self._armed else "wait_down"
        return event
