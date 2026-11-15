"""Local, short-lived motion status shared by independent band processes.

Only the latest derived state is written. No raw IMU or heart-rate history.
Readers require fresh samples from both bands before reporting a match.
"""

import json
import math
import secrets
import time
from pathlib import Path


RUNTIME = Path(__file__).resolve().parent / "runtime"
STATE_MAX_AGE = 2.0
INVALID_RESET_GENERATION = "unavailable"


def read_reset_generation(directory=None):
    directory = RUNTIME if directory is None else Path(directory)
    try:
        record = json.loads((directory / "motion_reset.json").read_text(encoding="utf-8"))
        generation = record.get("generation") if isinstance(record, dict) else None
        if (record.get("version") != 1 or not isinstance(generation, str)
                or not 1 <= len(generation) <= 128 or generation == INVALID_RESET_GENERATION):
            return INVALID_RESET_GENERATION
        return generation
    except FileNotFoundError:
        return "initial"
    except (OSError, ValueError, AttributeError):
        return INVALID_RESET_GENERATION


def request_motion_reset(directory=None):
    directory = RUNTIME if directory is None else Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    generation = secrets.token_hex(16)
    temporary = directory / f".motion_reset_{generation}.tmp"
    try:
        temporary.write_text(json.dumps(dict(version=1, generation=generation)), encoding="utf-8")
        temporary.replace(directory / "motion_reset.json")
    finally:
        temporary.unlink(missing_ok=True)
    return generation


class MotionStatePublisher:
    def __init__(self, path, band_number, interval=0.2):
        self.path = Path(path) if path is not None else None
        self.band_number = band_number
        self.interval = interval
        self._last_write = None
        self._last_state = None

    def publish(self, *, connected, ready, raised, phase, force=False,
                mode="pose", triggered=False, reset_generation="initial"):
        if self.path is None:
            return
        if mode not in ("pose", "accel-latch"):
            raise ValueError("unknown motion mode")
        raised = bool(mode == "pose" and connected and ready and raised)
        triggered = bool(mode == "accel-latch" and triggered)
        active = bool(connected and ready and (triggered if mode == "accel-latch" else raised))
        state = (bool(connected), bool(ready), raised, phase, mode, triggered, reset_generation)
        now = time.monotonic()
        if (not force and state == self._last_state and self._last_write is not None
                and now - self._last_write < self.interval):
            return
        record = dict(version=1, band_number=self.band_number, connected=bool(connected),
                      ready=bool(ready), raised=raised, phase=phase, updated_at=time.time(),
                      mode=mode, triggered=triggered, active=active, reset_generation=reset_generation)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
        temporary.replace(self.path)
        self._last_write, self._last_state = now, state


def read_motion_states(directory=None, *, now=None, max_age=STATE_MAX_AGE):
    directory = RUNTIME if directory is None else Path(directory)
    now = time.time() if now is None else now
    reset_generation = read_reset_generation(directory)
    bands = []
    for number in (62, 77):
        band = dict(band_number=number, status="disconnected", raised=False,
                    ready=False, connected=False, updated_at=None, mode="pose",
                    triggered=False, active=False, reset_generation="initial")
        try:
            record = json.loads((directory / f"motion_state_{number}.json").read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("version") != 1 or record.get("band_number") != number:
                raise ValueError("wrong state identity")
            stamp = record.get("updated_at")
            if (isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                    or not math.isfinite(stamp)):
                raise ValueError("invalid state timestamp")
            if any(not isinstance(record.get(key), bool) for key in ("connected", "ready", "raised")):
                raise ValueError("invalid state flags")
            mode = record.get("mode", "pose")
            if mode not in ("pose", "accel-latch"):
                raise ValueError("unknown motion mode")
            generation = record.get("reset_generation", "initial")
            if not isinstance(generation, str) or not 1 <= len(generation) <= 128:
                raise ValueError("invalid reset generation")
            if mode == "accel-latch" and not isinstance(record.get("triggered"), bool):
                raise ValueError("invalid trigger flag")
            band["mode"] = mode
            band["reset_generation"] = generation
            band["updated_at"] = stamp
            age = now - stamp
            if not record["connected"]:
                pass
            elif age < -1 or age > max_age:
                band["status"] = "stale"
            else:
                band["connected"] = True
                band["ready"] = record["ready"]
                if mode == "accel-latch":
                    acknowledged = (reset_generation != INVALID_RESET_GENERATION
                                    and generation == reset_generation)
                    band["ready"] = record["ready"] and acknowledged
                    band["triggered"] = band["ready"] and record["triggered"]
                    band["active"] = band["triggered"]
                    band["status"] = ("arming" if not band["ready"] else
                                      "triggered" if band["triggered"] else "waiting_motion")
                else:
                    band["raised"] = record["ready"] and record["raised"]
                    band["active"] = band["raised"]
                    band["status"] = ("untrained" if not record["ready"] else
                                      "raised" if band["raised"] else
                                      "unknown" if record.get("phase") == "pose_unknown" else "lowered")
        except (OSError, ValueError, TypeError, OverflowError):
            pass
        bands.append(band)
    modes = {band["mode"] for band in bands}
    return dict(match=len(modes) == 1 and all(band["active"] for band in bands),
                mode=next(iter(modes)) if len(modes) == 1 else "mixed",
                reset_generation=reset_generation, bands=bands, server_time=now)
