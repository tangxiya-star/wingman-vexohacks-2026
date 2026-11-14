"""Python port of the official Vexo gesture-trainer template recogniser.

Source: https://github.com/VexoAI-Org/vexo-open-kit/blob/1e4291e2fa4896b1f603d3d4f0b009c483425da0/projects/gesture-trainer/recogniser.js
The official trainer requests 50 Hz six-axis motion. Its thresholds are demo
defaults, not validated recognition rates on real wrists. This port additionally
rejects malformed/non-finite samples and breaks segments at sample discontinuities.

MIT License

Copyright (c) 2026 Vexo AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import math
import time
from collections.abc import Mapping, Sequence

START_GYRO = 40
START_ACCEL = 0.08
QUIET_MS = 300
MIN_MS = 200
MAX_MS = 3000
MAX_SAMPLES = 2000
POINTS = 24
GYRO_SCALE = 250
ACCEL_SCALE = 1
NOT_SURE = 0.5
AXES = ("ax", "ay", "az", "gx", "gy", "gz")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valid_sample(sample) -> bool:
    return isinstance(sample, Mapping) and all(_finite(sample.get(key)) for key in ("t", *AXES))


def _moving(sample: Mapping, before: Mapping | None) -> bool:
    if math.hypot(sample["gx"], sample["gy"], sample["gz"]) > START_GYRO:
        return True
    return before is not None and math.hypot(
        *(sample[axis] - before[axis] for axis in AXES[:3])
    ) > START_ACCEL


class Segmenter:
    """Cut movements from rest → motion → rest, using band time in milliseconds."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.samples: list[dict] = []
        self.before: dict | None = None
        self.last_move = 0
        self.began = 0
        self.too_long = False

    def feed(self, sample: Mapping, now: float | None = None) -> list[dict] | None:
        """Return one finished segment or None; ``now`` is host time in ms.

        Invalid samples cancel a segment. A time gap above QUIET_MS or a jump in
        an available sample number starts a fresh segment, never joining the gap.
        """
        if now is None:
            now = time.time() * 1000
        if not _valid_sample(sample) or not _finite(now):
            self.reset()
            return None
        sample = dict(sample)
        number = sample.get("n")
        if number is not None and (not _finite(number) or number < 0 or int(number) != number):
            self.reset()
            return None
        if self.before is not None:
            previous_number = self.before.get("n")
            if sample["t"] <= self.before["t"]:
                self.reset()
                return None
            if sample["t"] - self.before["t"] > QUIET_MS or (
                number is not None and previous_number is not None and number != previous_number + 1
            ):
                self.reset()

        is_moving = _moving(sample, self.before)
        self.before = sample
        if is_moving:
            self.last_move = sample["t"]
        if not self.samples and not is_moving:
            return None

        if not self.samples:
            self.began = now
            self.too_long = False
            self.samples.append(sample)
        elif len(self.samples) >= MAX_SAMPLES or now - self.began > 2 * (MAX_MS + QUIET_MS):
            self.too_long = True
        elif sample["t"] - self.samples[0]["t"] <= MAX_MS + QUIET_MS:
            self.samples.append(sample)
        if sample["t"] - self.last_move < QUIET_MS:
            return None

        gesture = [one for one in self.samples if one["t"] <= self.last_move]
        too_long = self.too_long
        self.samples = []
        self.too_long = False
        if too_long or not gesture:
            return None
        duration = self.last_move - gesture[0]["t"]
        return gesture if MIN_MS <= duration <= MAX_MS else None


def to_shape(gesture: Sequence[Mapping]) -> list[float]:
    """Resample a gesture to 24 evenly spaced times × six scaled axes."""
    if not gesture or any(not _valid_sample(sample) for sample in gesture):
        raise ValueError("A gesture needs finite timestamps and all six motion axes")
    if any(b["t"] <= a["t"] for a, b in zip(gesture, gesture[1:])):
        raise ValueError("Gesture timestamps must increase strictly")
    start = gesture[0]["t"]
    length = gesture[-1]["t"] - start
    shape = []
    index = 0
    for point in range(POINTS):
        timestamp = start + length * point / (POINTS - 1)
        while index < len(gesture) - 2 and gesture[index + 1]["t"] < timestamp:
            index += 1
        a = gesture[index]
        b = gesture[index + 1] if index + 1 < len(gesture) else a
        part = min(1, max(0, (timestamp - a["t"]) / (b["t"] - a["t"]))) if b["t"] > a["t"] else 0
        for axis in AXES:
            value = a[axis] + (b[axis] - a[axis]) * part
            shape.append(value / (GYRO_SCALE if axis.startswith("g") else ACCEL_SCALE))
    if not all(_finite(value) for value in shape):
        raise ValueError("Gesture interpolation produced a non-finite shape")
    return shape


def _validate_shape(shape: Sequence[float]) -> None:
    if len(shape) != POINTS * len(AXES) or any(not _finite(value) for value in shape):
        raise ValueError("A shape must contain 144 finite numbers")


def distance(one: Sequence[float], other: Sequence[float]) -> float:
    """Mean Euclidean distance between matching six-axis points, as upstream."""
    _validate_shape(one)
    _validate_shape(other)
    total = 0.0
    for point in range(0, len(one), len(AXES)):
        square = 0.0
        for axis in range(point, point + len(AXES)):
            square += (one[axis] - other[axis]) ** 2
        total += math.sqrt(square)
    return total / (len(one) / len(AXES))


def match(shape: Sequence[float], examples: Sequence[Mapping], limit: float = NOT_SURE) -> dict:
    """Return nearest ``{label, distance}``; an unknown/no-example label is None.

    With no examples the distance is infinity, matching the official recogniser.
    """
    _validate_shape(shape)
    if not _finite(limit) or limit < 0:
        raise ValueError("The match limit must be finite and non-negative")
    best = {"label": None, "distance": math.inf}
    for example in examples:
        current = distance(shape, example["shape"])
        if current < best["distance"]:
            best = {"label": example["label"], "distance": current}
    return best if best["distance"] <= limit else {"label": None, "distance": best["distance"]}
