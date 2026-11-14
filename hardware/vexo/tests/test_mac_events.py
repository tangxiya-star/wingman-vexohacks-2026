import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from band_config import BAND_NUMBER
from mac_events import MacEventReporter


class MacEventReporterTests(unittest.TestCase):
    def test_stdout_and_flushed_file_match_with_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events" / "hand.jsonl"
            output = io.StringIO()
            event = {"type": "hand_raise", "label": "抬手", "sequence": -1}
            before = datetime.now(timezone.utc)
            with redirect_stdout(output), MacEventReporter(path, BAND_NUMBER) as reporter:
                first = reporter.emit(event)
                second = reporter.emit({"type": "hand_lower"})
                # Read before close to verify that each event is already flushed.
                stored = path.read_text(encoding="utf-8")
            after = datetime.now(timezone.utc)

            self.assertEqual(output.getvalue(), stored)
            self.assertEqual([json.loads(line) for line in stored.splitlines()], [first, second])
            self.assertEqual(event, {"type": "hand_raise", "label": "抬手", "sequence": -1})
            self.assertEqual([first["sequence"], second["sequence"]], [1, 2])
            self.assertEqual(first["type"], "hand_raise")
            self.assertIn("抬手", stored)
            for record in (first, second):
                self.assertEqual(record["band_number"], BAND_NUMBER)
                self.assertTrue(record["received_at"].endswith("Z"))
                timestamp = datetime.fromisoformat(record["received_at"])
                self.assertLessEqual(before, timestamp)
                self.assertLessEqual(timestamp, after)

    def test_existing_events_are_preserved_and_close_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            previous = '{"type":"previous_event"}\n'
            path.write_text(previous, encoding="utf-8")
            reporter = MacEventReporter(path, BAND_NUMBER)
            with redirect_stdout(io.StringIO()):
                record = reporter.emit({"type": "hand_raise"})
            reporter.close()
            reporter.close()
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0] + "\n", previous)
            self.assertEqual(json.loads(lines[1]), record)
            with self.assertRaises(ValueError):
                reporter.emit({"type": "hand_raise"})

    def test_stdout_only_and_invalid_json_propagates_without_output(self):
        output = io.StringIO()
        reporter = MacEventReporter(None, BAND_NUMBER)
        with redirect_stdout(output):
            with self.assertRaises(ValueError):
                reporter.emit({"type": "hand_raise", "confidence": float("nan")})
            self.assertEqual(output.getvalue(), "")
            record = reporter.emit({"type": "hand_raise"})
        self.assertEqual(record["sequence"], 1)
        self.assertEqual(json.loads(output.getvalue()), record)
        reporter.close()
        reporter.close()

    def test_constructor_file_error_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(IsADirectoryError):
                MacEventReporter(Path(directory), BAND_NUMBER)


if __name__ == "__main__":
    unittest.main()
