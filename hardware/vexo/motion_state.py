"""Local, short-lived pose status shared by independent band processes.

Only the latest derived state is written. No raw IMU or heart-rate history.
Readers require fresh samples from both bands before reporting a match.
"""

import json
import math
import time
from pathlib import Path


RUNTIME = Path(__file__).resolve().parent / "runtime"
STATE_MAX_AGE = 2.0


class MotionStatePublisher:
    def __init__(self, path, band_number, interval=0.2):
        self.path = Path(path) if path is not None else None
        self.band_number = band_number
        self.interval = interval
        self._last_write = None
        self._last_state = None

    def publish(self, *, connected, ready, raised, phase, force=False):
        if self.path is None:
            return
        raised = bool(connected and ready and raised)
        state = (bool(connected), bool(ready), raised, phase)
        now = time.monotonic()
        if (not force and state == self._last_state and self._last_write is not None
                and now - self._last_write < self.interval):
            return
        record = dict(version=1, band_number=self.band_number, connected=bool(connected),
                      ready=bool(ready), raised=raised, phase=phase, updated_at=time.time())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, allow_nan=False), encoding="utf-8")
        temporary.replace(self.path)
        self._last_write, self._last_state = now, state


def read_motion_states(directory=None, *, now=None, max_age=STATE_MAX_AGE):
    directory = RUNTIME if directory is None else Path(directory)
    now = time.time() if now is None else now
    bands = []
    for number in (62, 77):
        band = dict(band_number=number, status="disconnected", raised=False,
                    ready=False, connected=False, updated_at=None)
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
            band["updated_at"] = stamp
            age = now - stamp
            if not record["connected"]:
                pass
            elif age < -1 or age > max_age:
                band["status"] = "stale"
            else:
                band["connected"] = True
                band["ready"] = record["ready"]
                band["raised"] = record["ready"] and record["raised"]
                band["status"] = ("untrained" if not record["ready"] else
                                  "raised" if band["raised"] else
                                  "unknown" if record.get("phase") == "pose_unknown" else "lowered")
        except (OSError, ValueError, TypeError, OverflowError):
            pass
        bands.append(band)
    return dict(match=all(band["raised"] for band in bands), bands=bands, server_time=now)
