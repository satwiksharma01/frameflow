"""B-roll: the creator's own images and clips over the main track."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import broll
from project.media import _find_tool
from project.validate import validate


def _ir():
    """A 10 s vertical cut of one recording, with a Captions track above it."""
    return {"schema_version": "0.2.0",
            "project": {"name": "t", "width": 1080, "height": 1920, "fps": 30, "source_frame_rate_mode": "cfr"},
            "tracks": [{"id": "V1", "type": "video", "clips": [
                           {"id": "clip1", "source": "C:/media/talk.mp4", "source_in": 0.0, "source_out": 10.0,
                            "timeline_start": 0.0, "timeline_duration": 10.0}]},
                       {"id": "Captions", "type": "captions", "clips": []}]}


class TestPlacing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        cls.image, cls.clip = folder / "jacket.png", folder / "street.mp4"
        ffmpeg = _find_tool("ffmpeg")
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360",
                        "-frames:v", "1", str(cls.image)], check=True)
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
                        "-f", "lavfi", "-i", "sine=duration=2", "-shortest", str(cls.clip)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def item(self, path, at, duration=2.0, **extra):
        return {"label": "B-roll 1", "path": str(path), "at": at, "duration": duration, **extra}

    def test_a_clip_covers_the_picture_with_its_sound_turned_down(self):
        ir = _ir()
        self.assertEqual(broll.place(ir, [self.item(self.clip, 3.0, 1.5, start=0.5)], 0), [])
        self.assertEqual([t["id"] for t in ir["tracks"]], ["V1", "B-roll", "Captions"])   # just above the cut
        self.assertEqual(ir["tracks"][1]["clips"], [{
            "id": "clip1", "source": self.clip.resolve().as_posix(), "source_in": 0.5, "source_out": 2.0,
            "timeline_start": 3.0, "timeline_duration": 1.5, "volume_db": broll.MUTED_DB,
            "transform": {"fill": True}}])
        validate(ir, "ir")

    def test_an_image_becomes_a_clip_with_a_slow_push_in(self):
        ir = _ir()
        self.assertEqual(broll.place(ir, [self.item(self.image, 1.0)], 0), [])
        made = []

        def still(image, out, width, height, fps, seconds):
            made.append((Path(image).name, width, height, seconds))
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"mp4")
            return Path(out)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(broll, "still_to_clip", still):
            broll.make_stills(ir, Path(tmp))
            clip = ir["tracks"][1]["clips"][0]
            self.assertEqual(Path(clip["source"]).parent, Path(tmp).resolve() / "stills")
        self.assertEqual(made, [("jacket.png", 1080, 1920, 2.0)])
        self.assertEqual((clip["source_in"], clip["source_out"]), (0.0, 2.0))
        self.assertNotIn("volume_db", clip)             # a still has no sound to turn down
        validate(ir, "ir")

    def test_b_roll_stops_at_the_end_of_the_video(self):
        ir = _ir()
        self.assertEqual(broll.place(ir, [self.item(self.image, 9.0, 3.0)], 0), [])
        self.assertEqual(ir["tracks"][1]["clips"][0]["timeline_duration"], 1.0)

    def test_what_cannot_be_placed_is_named(self):
        ir = _ir()
        problems = broll.place(ir, [self.item(self.clip, 0.0, 1.0),
                                    self.item(self.clip, 0.5, 1.0),               # on top of the first
                                    self.item(self.clip, 3.0, 2.0, start=1.0),    # 1 s of the clip is left
                                    self.item(Path("C:/nowhere/missing.mp4"), 6.0)], 0)
        self.assertEqual(len(problems), 3, problems)
        self.assertIn("overlap", problems[0])
        self.assertIn("1.0s from 1.0s", problems[1])
        self.assertIn("missing.mp4", problems[2])
        self.assertEqual(len(ir["tracks"][1]["clips"]), 1)


if __name__ == "__main__":
    unittest.main()
