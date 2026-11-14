import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from gesture_matcher import (
    MAX_SAMPLES, NOT_SURE, POINTS, QUIET_MS, Segmenter, distance, match, to_shape,
)


REST = {"ax": 0, "ay": 0, "az": 1, "gx": 0, "gy": 0, "gz": 0}
KIT = Path(__file__).resolve().parents[1] / "vexo-open-kit"


def movement(kind="left", seconds=0.7, rate=50, start=5000):
    """A smooth physical-looking stroke, bracketed by stationary samples."""
    result = []
    for index in range(math.ceil((seconds + 1.0) * rate)):
        sample = {**REST, "t": start + index * 1000 / rate, "n": index}
        phase = (index / rate - 0.4) / seconds
        if 0 <= phase < 1:
            pulse = math.sin(math.pi * phase)
            if kind == "twist":
                sample["gz"] = 420 * pulse
            else:
                sign = 1 if kind == "left" else -1
                sample.update(ax=sign * 0.5 * pulse, gy=sign * 180 * pulse)
        result.append(sample)
    return result


def cut(samples, segmenter=None):
    segmenter = segmenter or Segmenter()
    found = []
    for sample in samples:
        gesture = segmenter.feed(sample, now=sample["t"])
        if gesture is not None:
            found.append(gesture)
    return found


class GestureMatcherTests(unittest.TestCase):
    def test_rest_motion_rest_and_resampling_match_at_different_speed_and_rate(self):
        examples = []
        for kind in ("left", "right"):
            gestures = cut(movement(kind))
            self.assertEqual(len(gestures), 1)
            self.assertLess(gestures[0][0]["t"], gestures[0][-1]["t"])
            shape = to_shape(gestures[0])
            self.assertEqual(len(shape), POINTS * 6)
            examples.append({"label": kind, "shape": shape})
        for kind in ("left", "right"):
            for seconds, rate in ((0.55, 50), (0.9, 50), (0.7, 25), (0.7, 100)):
                with self.subTest(kind=kind, seconds=seconds, rate=rate):
                    gestures = cut(movement(kind, seconds, rate))
                    self.assertEqual(len(gestures), 1)
                    result = match(to_shape(gestures[0]), examples)
                    self.assertEqual(result["label"], kind)
                    self.assertLess(result["distance"], NOT_SURE)
        unknown = match(to_shape(cut(movement("twist"))[0]), examples)
        self.assertIsNone(unknown["label"])
        self.assertGreater(unknown["distance"], NOT_SURE)

    def test_short_long_and_reset_do_not_contaminate_next_gesture(self):
        segmenter = Segmenter()
        self.assertEqual(cut(movement(seconds=0.1), segmenter), [])
        self.assertEqual(cut(movement(seconds=4, start=10000), segmenter), [])
        self.assertEqual(len(cut(movement(start=20000), segmenter)), 1)
        for sample in movement(start=30000)[:40]:
            segmenter.feed(sample, now=sample["t"])
        segmenter.reset()
        self.assertEqual(segmenter.samples, [])
        self.assertIsNone(segmenter.before)
        self.assertEqual(len(cut(movement(start=40000), segmenter)), 1)

    def test_rejects_missing_axes_nonfinite_and_broken_sample_order(self):
        for broken in (
            {"t": 5500},
            {**REST, "t": 5500, "ax": math.nan},
            {**REST, "t": 5500, "gz": math.inf},
            {**REST, "t": None},
        ):
            with self.subTest(broken=broken):
                segmenter = Segmenter()
                segmenter.feed({**REST, "t": 5000, "gz": 300}, now=5000)
                self.assertIsNone(segmenter.feed(broken, now=5500))
                self.assertEqual(segmenter.samples, [])
                self.assertEqual(len(cut(movement(start=10000), segmenter)), 1)

        for following in (
            {**REST, "gz": 100, "t": 5000, "n": 2},
            {**REST, "gz": 100, "t": 4990, "n": 2},
            {**REST, "gz": 100, "t": 5020, "n": 4},
            {**REST, "gz": 100, "t": 5000 + QUIET_MS + 1, "n": 2},
        ):
            segmenter = Segmenter()
            segmenter.feed({**REST, "gz": 100, "t": 5000, "n": 1}, now=5000)
            segmenter.feed(following, now=5020)
            self.assertLessEqual(len(segmenter.samples), 1)

    def test_faulty_clock_cannot_grow_memory_or_return_an_overlong_gesture(self):
        segmenter = Segmenter()
        for index in range(MAX_SAMPLES + 100):
            segmenter.feed({**REST, "gz": 300, "t": 5000 + index / 100}, now=0)
        self.assertEqual(len(segmenter.samples), MAX_SAMPLES)
        self.assertIsNone(segmenter.feed({**REST, "t": 5321}, now=0))
        self.assertEqual(segmenter.samples, [])

        for index in range(200):
            segmenter.feed({**REST, "gz": 300, "t": 6000 + index}, now=index * 100)
        self.assertIsNone(segmenter.feed({**REST, "t": 6499}, now=30000))
        self.assertEqual(segmenter.samples, [])

    def test_shape_validation_empty_examples_and_tie_order(self):
        shape = to_shape(cut(movement())[0])
        self.assertEqual(match(shape, []), {"label": None, "distance": math.inf})
        self.assertEqual(match(shape, [
            {"label": "first", "shape": shape}, {"label": "second", "shape": shape}
        ], limit=0), {"label": "first", "distance": 0})
        for invalid in ([], [{"t": 1}], [{**REST, "t": 1}, {**REST, "t": 1}]):
            with self.assertRaises(ValueError):
                to_shape(invalid)
        for invalid in ([0] * 143, [math.nan] * 144):
            with self.assertRaises(ValueError):
                distance(shape, invalid)

    @unittest.skipUnless(shutil.which("node") and (KIT / "projects/gesture-trainer/recogniser.js").exists(),
                         "Optional differential check needs Node and the official Vexo kit")
    def test_differential_against_official_js_circle_shake_and_flick(self):
        # The official motions generate each input ONCE in Node. Python consumes
        # exactly those numeric samples, avoiding separate trig/noise implementations.
        script = r"""
import {pathToFileURL} from 'node:url';
const base = pathToFileURL(process.argv[1] + '/projects/gesture-trainer/');
const {Segmenter, toShape, match} = await import(new URL('recogniser.js', base));
const {MOTIONS} = await import(new URL('motions.js', base));
const rest = {ax:0, ay:0, az:1, gx:0, gy:0, gz:0};
const cases = [];
for (const name of ['circle','shake','flick']) {
  for (const slow of [1, 1.25]) {
    const [motion, seconds] = MOTIONS[name];
    const samples = [];
    for (let i=0; i<(seconds*slow+1.2)*50; i++) {
      const s = (i/50-0.4)/slow;
      samples.push({...rest, ...(s>=0 && s<seconds ? motion(s): {}), t:5000+i*20, n:i});
    }
    const segmenter = new Segmenter();
    const gestures = samples.map(sample => segmenter.feed(sample,sample.t)).filter(Boolean);
    cases.push({name, slow, samples, gestures, shapes:gestures.map(toShape)});
  }
}
const examples = cases.filter(c=>c.slow===1).map(c=>({label:c.name,shape:c.shapes[0]}));
for (const c of cases) c.matches = c.shapes.map(shape=>match(shape,examples));
console.log(JSON.stringify({cases,examples}));
"""
        completed = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script, str(KIT)],
            capture_output=True, text=True, check=True, timeout=20,
        )
        expected = json.loads(completed.stdout)
        for case in expected["cases"]:
            with self.subTest(name=case["name"], slow=case["slow"]):
                actual_gestures = cut(case["samples"])
                self.assertEqual(actual_gestures, case["gestures"])
                self.assertEqual(len(actual_gestures), 1)
                actual_shape = to_shape(actual_gestures[0])
                self.assertEqual(len(actual_shape), 144)
                for actual, reference in zip(actual_shape, case["shapes"][0]):
                    self.assertAlmostEqual(actual, reference, delta=1e-12)
                result = match(actual_shape, expected["examples"])
                self.assertEqual(result["label"], case["matches"][0]["label"])
                self.assertAlmostEqual(result["distance"], case["matches"][0]["distance"], delta=1e-12)


if __name__ == "__main__":
    unittest.main()
