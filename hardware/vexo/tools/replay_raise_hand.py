#!/usr/bin/env python3
"""Replay a local motion JSONL through the trained hand-raise detector.

Usage: .venv/bin/python tools/replay_raise_hand.py trace.jsonl --expect-count 3
Use --mode legacy for historical fixed-angle detector evidence. Each sample is
{t, ax, ay, az, gx, gy, gz, n?}. Control markers: disabled, calibrate,
restore_calibration (profile version 1 or 2), and begin_training. Training
examples are diagnostics, never detected events. Output is JSONL containing
training progress, segment diagnostics, events, phase transitions and a summary.
Record before starting training so the begin_training marker is included;
a saved profile alone does not indicate an in-progress training session.
Diagnostics do not tune thresholds or prove that the hand was overhead.
"""

import argparse
import json
import math
from numbers import Integral, Real
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raise_hand import (
    DOWN_ANGLE_DEG, MAX_GESTURE_MS, MAX_SAMPLE_GAP_MS, OVERHEAD_ANGLE_DEG,
    QUICK_PEAK_GYRO_DPS, START_GYRO_DPS, STILL_DIRECTION_DEG,
    STILL_GYRO_DPS, STILL_MAGNITUDE_G, TARGET_HOLD_MS, RaiseHandDetector,
)
from trained_raise import TrainedRaiseDetector


def emit(record):
    print(json.dumps(record, ensure_ascii=False, allow_nan=False))


def angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))))


def inspect_sample(sample):
    """Observe the documented input units without calling detector internals."""
    if not isinstance(sample, dict):
        return None, "sample_is_not_an_object"
    values = []
    for key in ("t", "ax", "ay", "az", "gx", "gy", "gz"):
        value = sample.get(key)
        try:
            valid = (not isinstance(value, bool) and isinstance(value, Real)
                     and math.isfinite(value))
        except OverflowError:
            valid = False
        if not valid:
            return None, f"invalid_{key}"
        values.append(float(value))
    t, *axes = values
    n = sample.get("n")
    if t < 0:
        return None, "negative_device_time"
    if n is not None and (isinstance(n, bool) or not isinstance(n, Integral)
                          or not 0 <= n <= 0xFFFFFFFF):
        return None, "invalid_sequence_number"
    magnitude, gyro = math.hypot(*axes[:3]), math.hypot(*axes[3:])
    if magnitude == 0 or not math.isfinite(magnitude) or not math.isfinite(gyro):
        return None, "invalid_vector_magnitude"
    return dict(t=t, n=n, direction=tuple(value / magnitude for value in axes[:3]),
                magnitude_g=magnitude, gyro_dps=gyro), None


def continuity_fault(current, previous):
    if previous is None:
        return None
    dt = current["t"] - previous["t"]
    if dt <= 0:
        return dict(reason="non_increasing_device_time", delta_ms=dt)
    if dt > MAX_SAMPLE_GAP_MS:
        return dict(reason="sample_gap", delta_ms=dt)
    if current["n"] is not None and previous["n"] is not None:
        expected = (previous["n"] + 1) & 0xFFFFFFFF
        if current["n"] != expected:
            return dict(reason="sequence_discontinuity", expected_n=expected, received_n=current["n"])
    return None


class CandidateObservation:
    """Track per-candidate evidence, including stillness before its deadline."""

    def __init__(self, sample, relative_angle):
        self.started_at = sample["t"]
        self.start_angle = relative_angle
        self.start_gyro = sample["gyro_dps"]
        self.elapsed = 0
        self.peak_gyro = 0
        self.maximum_angle = 0
        self.first_target_ms = None
        self.hold_started = None
        self.hold_anchor = None
        self.longest_hold = 0
        self.rejections = {}

    def observe(self, sample, relative_angle):
        self.elapsed = sample["t"] - self.started_at
        # A late sample cannot establish evidence the detector needed earlier.
        if self.elapsed > MAX_GESTURE_MS:
            return
        self.peak_gyro = max(self.peak_gyro, sample["gyro_dps"])
        self.maximum_angle = max(self.maximum_angle, relative_angle)
        rejected = []
        if relative_angle < OVERHEAD_ANGLE_DEG:
            rejected.append("angle_below_target")
        elif self.first_target_ms is None:
            self.first_target_ms = self.elapsed
        if sample["gyro_dps"] >= STILL_GYRO_DPS:
            rejected.append("gyro_not_still")
        if not STILL_MAGNITUDE_G[0] <= sample["magnitude_g"] <= STILL_MAGNITUDE_G[1]:
            rejected.append("acceleration_not_near_gravity")
        if rejected:
            self.hold_started = self.hold_anchor = None
        else:
            if (self.hold_anchor is not None
                    and angle(self.hold_anchor, sample["direction"]) > STILL_DIRECTION_DEG):
                rejected.append("target_direction_drift")
                self.hold_started = self.hold_anchor = None
            if self.hold_started is None:
                self.hold_started = sample["t"]
                self.hold_anchor = sample["direction"]
            self.longest_hold = max(self.longest_hold, sample["t"] - self.hold_started)
        for reason in rejected:
            self.rejections[reason] = self.rejections.get(reason, 0) + 1

    def summary(self):
        unmet = []
        if self.peak_gyro < QUICK_PEAK_GYRO_DPS:
            unmet.append("required_fast_rotation_not_observed")
        if self.first_target_ms is None:
            unmet.append("target_angle_not_reached")
        elif self.longest_hold < TARGET_HOLD_MS:
            unmet.append("continuous_stable_target_hold_incomplete")
        return dict(started_device_time_ms=self.started_at, elapsed_ms=self.elapsed,
                    start_angle_deg=round(self.start_angle, 3),
                    start_gyro_dps=round(self.start_gyro, 3),
                    start_conditions=dict(gyro_threshold=self.start_gyro >= START_GYRO_DPS,
                                          departure_angle=self.start_angle >= DOWN_ANGLE_DEG),
                    maximum_angle_deg_before_deadline=round(self.maximum_angle, 3),
                    peak_gyro_dps_before_deadline=round(self.peak_gyro, 3),
                    first_target_angle_elapsed_ms=self.first_target_ms,
                    longest_stable_target_ms_before_deadline=self.longest_hold,
                    target_rejected_sample_counts=self.rejections,
                    unmet_conditions_before_deadline=unmet)


def replay_legacy(path, expect_count=None):
    detector = RaiseHandDetector()
    previous_sample = None
    candidate = None
    enabled = True  # Preserve replay of older traces without a control header.
    counts = dict(samples=0, invalid_samples=0, continuity_faults=0,
                  calibrations=0, restored_calibrations=0, disabled_markers=0,
                  skipped_disabled_samples=0, phase_transitions=0, events=0)
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"line {line_number}: invalid JSON: {error.msg}") from error
            before = detector.phase
            kind = record.get("kind") if isinstance(record, dict) else None
            if kind == "disabled":
                counts["disabled_markers"] += 1
                enabled = False
                previous_sample = candidate = None
                emit(dict(kind="disabled", line=line_number, phase=detector.phase))
                continue
            if kind == "restore_calibration":
                try:
                    detector.restore_calibration(record.get("profile"))
                except ValueError as error:
                    raise ValueError(f"line {line_number}: invalid calibration profile: {error}") from error
                counts["restored_calibrations"] += 1
                enabled = True
                previous_sample = candidate = None
                emit(dict(kind="restore_calibration", line=line_number, previous_phase=before,
                          phase=detector.phase, profile=detector.calibration_profile()))
                continue
            if kind == "calibrate":
                counts["calibrations"] += 1
                detector.calibrate()
                enabled = True
                previous_sample = candidate = None
                emit(dict(kind="calibrate", line=line_number, previous_phase=before,
                          phase=detector.phase))
                continue

            counts["samples"] += 1
            if not enabled:
                counts["skipped_disabled_samples"] += 1
                continue
            observed, invalid = inspect_sample(record)
            fault = (dict(reason="invalid_sample", detail=invalid) if invalid else
                     continuity_fault(observed, previous_sample))
            if invalid:
                counts["invalid_samples"] += 1
            elif fault:
                counts["continuity_faults"] += 1
            event = detector.feed(record)
            after = detector.phase
            relative_angle = (angle(detector.baseline, observed["direction"])
                              if detector.baseline is not None and observed is not None else None)
            if before != "raising" and after == "raising":
                candidate = CandidateObservation(observed, relative_angle)
            if candidate is not None and observed is not None and fault is None:
                candidate.observe(observed, relative_angle)
            if event is not None:
                counts["events"] += 1
                emit(dict(kind="detected_event", line=line_number, **event))

            if before != after or fault is not None:
                if before != after:
                    counts["phase_transitions"] += 1
                diagnostic = dict(kind="phase_transition" if before != after else "stream_fault",
                                  line=line_number, previous_phase=before, phase=after)
                if observed is not None:
                    diagnostic.update(device_time_ms=observed["t"],
                                      angle_deg=round(relative_angle, 3) if relative_angle is not None else None,
                                      gyro_dps=round(observed["gyro_dps"], 3),
                                      magnitude_g=round(observed["magnitude_g"], 4))
                if fault is not None:
                    diagnostic.update(fault)
                elif event is not None:
                    diagnostic["reason"] = "gesture_confirmed"
                elif before == "raising" and after == "wait_down":
                    diagnostic["reason"] = "candidate_deadline_exceeded"
                elif before == "raising" and after == "armed":
                    diagnostic["reason"] = "returned_down_before_confirmation"
                elif before == "calibrating" and after == "armed":
                    diagnostic.update(reason="calibration_complete", baseline=detector.baseline)
                elif after == "raising":
                    diagnostic["reason"] = "movement_candidate_started"
                else:
                    diagnostic["reason"] = "stable_down_rearmed"
                if candidate is not None:
                    diagnostic["candidate"] = candidate.summary()
                emit(diagnostic)
            if after != "raising" or fault is not None:
                candidate = None
            previous_sample = observed  # Invalid input resets the sequence/time anchor.

    summary = dict(kind="replay_summary", mode="legacy", path=str(path), **counts,
                   final_phase=detector.phase, motion_enabled=enabled,
                   detector_sample_count=detector.sample_count)
    if candidate is not None:
        summary["unfinished_candidate"] = candidate.summary()
    if expect_count is not None:
        summary.update(expected_event_count=expect_count, count_matches=counts["events"] == expect_count)
    emit(summary)
    if expect_count is not None and counts["events"] != expect_count:
        print(f"Expected {expect_count} hand_raise event(s), observed {counts['events']}.", file=sys.stderr)
        return 1
    return 0


def replay_trained(path, expect_count=None):
    detector = TrainedRaiseDetector()
    previous_sample = None
    enabled = True  # Bare historical samples can calibrate, but cannot train implicitly.
    counts = dict(samples=0, invalid_samples=0, continuity_faults=0,
                  calibrations=0, restored_calibrations=0, disabled_markers=0,
                  skipped_disabled_samples=0, training_requests=0, trainings_started=0,
                  training_examples=0, segments=0, phase_transitions=0, events=0)
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"line {line_number}: invalid JSON: {error.msg}") from error
            before = detector.phase
            kind = record.get("kind") if isinstance(record, dict) else None
            if kind == "disabled":
                counts["disabled_markers"] += 1
                enabled = False
                previous_sample = None
                emit(dict(kind="disabled", line=line_number, phase=detector.phase))
                continue
            if kind == "calibrate":
                counts["calibrations"] += 1
                detector.calibrate()
                enabled = True
                previous_sample = None
                emit(dict(kind="calibrate", line=line_number, previous_phase=before,
                          phase=detector.phase, training_counts=detector.training_counts))
                continue
            if kind == "restore_calibration":
                try:
                    detector.restore_calibration(record.get("profile"))
                except ValueError as error:
                    raise ValueError(f"line {line_number}: invalid calibration profile: {error}") from error
                counts["restored_calibrations"] += 1
                enabled = True
                previous_sample = None
                emit(dict(kind="restore_calibration", line=line_number, previous_phase=before,
                          phase=detector.phase, baseline=detector.baseline,
                          source_profile_version=record["profile"].get("version", 1),
                          training_counts=detector.training_counts, ready=detector.ready))
                continue
            if kind == "begin_training":
                counts["training_requests"] += 1
                # Mirror the runtime: t before an explicit down calibration is ignored.
                accepted = enabled and detector.baseline is not None
                if accepted:
                    detector.begin_training()
                    counts["trainings_started"] += 1
                    previous_sample = None
                emit(dict(kind="begin_training", line=line_number, accepted=accepted,
                          reason="training_started" if accepted else "explicit_down_calibration_required",
                          phase=detector.phase, training_counts=detector.training_counts))
                continue
            if kind is not None:
                raise ValueError(f"line {line_number}: unknown control marker {kind!r}")

            counts["samples"] += 1
            if not enabled:
                counts["skipped_disabled_samples"] += 1
                continue
            observed, invalid = inspect_sample(record)
            fault = (dict(reason="invalid_sample", detail=invalid) if invalid else
                     continuity_fault(observed, previous_sample))
            if invalid:
                counts["invalid_samples"] += 1
            elif fault:
                counts["continuity_faults"] += 1
            previous_observation = detector.last_observation
            previous_revision = detector.model_revision
            event = detector.feed(record)
            after = detector.phase
            observation = detector.last_observation
            if observation is not previous_observation and observation.get("kind") in (
                    "gesture", "training_recorded", "training_skipped", "segment_skipped"):
                counts["segments"] += 1
                if observation["kind"] == "training_recorded":
                    counts["training_examples"] += 1
                emit(dict(kind="segment_diagnostic", line=line_number, observation=observation))
            if detector.model_revision != previous_revision:
                emit(dict(kind="training_progress", line=line_number,
                          training_counts=detector.training_counts, ready=detector.ready,
                          training=detector.training, match_limit=detector.limit))
            if event is not None:
                counts["events"] += 1
                emit(dict(kind="detected_event", line=line_number, **event))

            if before != after or fault is not None:
                if before != after:
                    counts["phase_transitions"] += 1
                diagnostic = dict(kind="phase_transition" if before != after else "stream_fault",
                                  line=line_number, previous_phase=before, phase=after)
                if observed is not None:
                    relative_angle = (angle(detector.baseline, observed["direction"])
                                      if detector.baseline is not None else None)
                    diagnostic.update(device_time_ms=observed["t"],
                                      angle_deg=round(relative_angle, 3) if relative_angle is not None else None,
                                      gyro_dps=round(observed["gyro_dps"], 3),
                                      magnitude_g=round(observed["magnitude_g"], 4))
                if fault is not None:
                    diagnostic.update(fault)
                elif event is not None:
                    diagnostic["reason"] = "trained_gesture_confirmed"
                elif before == "calibrating" and after == "armed":
                    diagnostic.update(reason="calibration_complete", baseline=detector.baseline)
                elif after == "raising":
                    diagnostic["reason"] = "motion_segment_started_from_down"
                elif after == "armed":
                    diagnostic["reason"] = "stable_down_rearmed"
                else:
                    diagnostic["reason"] = "awaiting_stable_down"
                emit(diagnostic)
            previous_sample = observed

    summary = dict(kind="replay_summary", mode="trained", path=str(path), **counts,
                   final_phase=detector.phase, motion_enabled=enabled,
                   detector_sample_count=detector.sample_count,
                   training_counts=detector.training_counts, ready=detector.ready,
                   training=detector.training, match_limit=detector.limit,
                   last_observation=detector.last_observation)
    if expect_count is not None:
        summary.update(expected_event_count=expect_count, count_matches=counts["events"] == expect_count)
    emit(summary)
    if expect_count is not None and counts["events"] != expect_count:
        print(f"Expected {expect_count} hand_raise event(s), observed {counts['events']}.", file=sys.stderr)
        return 1
    return 0


def replay(path, expect_count=None, mode="trained"):
    if mode == "legacy":
        return replay_legacy(path, expect_count)
    if mode == "trained":
        return replay_trained(path, expect_count)
    raise ValueError(f"Unknown replay mode: {mode!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Local motion JSONL trace")
    parser.add_argument("--mode", choices=("trained", "legacy"), default="trained",
                        help="Default: trained templates. legacy replays the historical fixed-angle detector")
    parser.add_argument("--expect-count", type=int, help="Exit 1 unless exactly this many events are emitted")
    args = parser.parse_args()
    if args.expect_count is not None and args.expect_count < 0:
        parser.error("--expect-count must be nonnegative")
    try:
        return replay(args.path, args.expect_count, args.mode)
    except (OSError, ValueError) as error:
        print(f"Cannot replay {args.path}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
