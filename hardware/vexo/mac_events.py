"""Write derived band events to the Mac as JSON lines.

Callers provide event-level data such as ``type: hand_raise``. Do not pass heart
rate or raw motion samples; this module neither collects nor retains them.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


class MacEventReporter:
    def __init__(self, path: Path | None, band_number: int):
        self.band_number = band_number
        self._sequence = 0
        self._closed = False
        self._file: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", encoding="utf-8", newline="\n")

    def emit(self, event: dict) -> dict:
        if self._closed:
            raise ValueError("MacEventReporter is closed")
        record = {
            **event,
            "band_number": self.band_number,
            "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sequence": self._sequence + 1,
        }
        # Serialize before either output so malformed data produces no partial event.
        line = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        self._sequence += 1
        if self._file is not None:
            self._file.write(line + "\n")
            self._file.flush()
        print(line, flush=True)
        return record

    def close(self) -> None:
        if self._closed:
            return
        if self._file is not None:
            self._file.close()
        self._closed = True

    def __enter__(self) -> "MacEventReporter":
        if self._closed:
            raise ValueError("MacEventReporter is closed")
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
