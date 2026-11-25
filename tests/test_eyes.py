"""The agent's eyes: a clip's study, its sheets, its moments and its shot lines."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import eyes
from project.media import _find_tool
from project.validate import ValidationError, validate


class _Clips(unittest.TestCase):
    """A temporary folder, and clips made with ffmpeg from lavfi sources played one after another."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.out = self.dir / "eyes" / "clip"

    def clip(self, name: str, sources: list[str], audio: bool = True) -> Path:
        path = self.dir / name
        command = [_find_tool("ffmpeg"), "-v", "error", "-y"]
        for source in sources:
            command += ["-f", "lavfi", "-i", source]
        if audio:       # every input before the options that shape the output
            seconds = sum(float(re.search(r"d=([\d.]+)", s).group(1)) for s in sources)
            command += ["-f", "lavfi", "-t", str(seconds), "-i", "sine=frequency=330"]
        graph = "".join(f"[{n}:v]" for n in range(len(sources))) + f"concat=n={len(sources)}:v=1:a=0[v]"
        command += ["-filter_complex", graph, "-map", "[v]"] + (["-map", f"{len(sources)}:a"] if audio else [])
        subprocess.run([*command, "-pix_fmt", "yuv420p", str(path)], check=True)
        return path


class TestStudy(_Clips):
    def test_a_cut_a_sheet_and_a_valid_study(self):
        clip = self.clip("red-blue.mp4", ["color=red:s=180x320:d=2", "color=blue:s=180x320:d=2"])
        study = eyes.study(clip, self.out)
        validate(study, "study")
        self.assertEqual(len(study["cuts"]), 1)
        self.assertAlmostEqual(study["cuts"][0], 2.0, delta=0.2)
        self.assertEqual(len(study["samples"]), 8)                  # every 0.5 s over 4 s
        self.assertTrue((self.out / "sheet.jpg").stat().st_size > 0)

    def test_soft_and_dark_are_flagged(self):
        soft = self.clip("soft.mp4", ["testsrc2=s=320x240:d=2", "testsrc2=s=320x240:d=2,boxblur=10"])
        study = eyes.study(soft, self.out)
        self.assertIn("soft", eyes.flags(study["samples"], 2.0, 4.0))
        self.assertNotIn("soft", eyes.flags(study["samples"], 0.0, 2.0))
        dark = eyes.study(self.clip("dark.mp4", ["color=black:s=180x320:d=1"]), self.dir / "dark")
        self.assertIn("dark", eyes.flags(dark["samples"], 0.0, 1.0))

    def test_a_matching_stamp_reuses_the_study(self):
        clip = self.clip("red.mp4", ["color=red:s=180x320:d=1"])
        eyes.study(clip, self.out)
        with mock.patch.object(eyes, "frames_at", side_effect=AssertionError("read frames again")):
            eyes.study(clip, self.out)

    def test_a_clip_without_audio_has_no_speech(self):                          # Review Focus 1
        study = eyes.study(self.clip("mute.mp4", ["color=red:s=180x320:d=1"], audio=False), self.out)
        self.assertEqual(study["speech"], [])
        self.assertEqual(study["speech_seconds"], 0)

    def test_a_very_short_clip_gets_one_frame(self):                            # Review Focus 2
        study = eyes.study(self.clip("blink.mp4", ["color=red:s=180x320:d=0.3"]), self.out)
        self.assertEqual(len(study["samples"]), 1)

    def test_a_sideways_phone_clip_is_drawn_upright(self):                      # Review Focus 3
        upright = self.clip("tall.mp4", ["color=red:s=180x320:d=1"])
        rotated = self.dir / "rotated.mp4"
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y", "-display_rotation:v:0", "90", "-i", str(upright),
                        "-c", "copy", str(rotated)], check=True)
        frame = eyes.frames_at(rotated, [0.5])[0]
        self.assertGreater(frame.shape[1], frame.shape[0])      # stored 180x320, shown 320x180 once turned


class TestCloser(_Clips):
    def test_one_second_at_four_a_second_holds_four_frames(self):
        clip = self.clip("red-blue.mp4", ["color=red:s=180x320:d=2", "color=blue:s=180x320:d=2"])
        with mock.patch.object(eyes, "draw_sheet", wraps=eyes.draw_sheet) as drawn:
            eyes.closer(clip, 1.0, 2.0, self.dir / "c.jpg")
        self.assertEqual(drawn.call_args.args[1], ["1.0s", "1.2s", "1.5s", "1.8s"])
        self.assertTrue((self.dir / "c.jpg").stat().st_size > 0)


class TestMoments(unittest.TestCase):
    GOOD = [{"start": 0.0, "end": 1.5, "what": "side-on", "framing": "wide", "subject": "him"},
            {"start": 1.5, "end": 3.0, "what": "turns to camera", "framing": "medium", "subject": "him",
             "notes": "smiles"}]

    def test_moments_are_checked(self):
        self.assertEqual(eyes.moment_problems("a.mp4", self.GOOD, 3.0), [])
        late = [dict(self.GOOD[0], end=9.0)]
        self.assertTrue(any("a.mp4" in p and "1" in p for p in eyes.moment_problems("a.mp4", late, 3.0)))
        overlap = [self.GOOD[0], dict(self.GOOD[1], start=1.0)]
        self.assertTrue(eyes.moment_problems("a.mp4", overlap, 3.0))
        backwards = [dict(self.GOOD[0], start=1.0, end=0.5)]
        self.assertTrue(eyes.moment_problems("a.mp4", backwards, 3.0))
        with self.assertRaises(ValidationError):
            validate({"clips": [{"clip": "a.mp4", "moments": [dict(self.GOOD[0], framing="extreme")]}]}, "moments")
        validate({"clips": [{"clip": "a.mp4", "moments": self.GOOD}]}, "moments")

    def test_shot_lines_carry_moments_or_the_study(self):
        study = {"duration": 3.0, "cuts": [], "speech_seconds": 0.0,
                 "samples": [{"t": t / 2, "sharp": 100.0, "bright": 120.0, "motion": 0.0} for t in range(6)]}
        self.assertEqual(eyes.shot_lines("a.mp4", study, self.GOOD)[1],
                         "- a.mp4 1.5–3.0 s · medium · turns to camera · smiles · sharp")
        self.assertEqual(eyes.shot_lines("a.mp4", study, None),
                         ["- a.mp4, 3.0 s · 0 cut(s) · speech 0.0 s · sharp"])


if __name__ == "__main__":
    unittest.main()
