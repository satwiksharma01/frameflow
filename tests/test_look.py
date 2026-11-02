"""Looking at the result: black frames, captions off screen and graphics over a face."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np

from project import look
from project.media import _find_tool


def _frame(value: int = 0) -> np.ndarray:
    return np.full((90, 160, 3), value, np.uint8)


def _clip(start: float, duration: float, **extra) -> dict:
    return {"id": "", "source": "C:/media/talk.mp4", "source_in": 0.0, "source_out": duration,
            "timeline_start": start, "timeline_duration": duration, **extra}


def _ir(*tracks: tuple[str, str, list[dict]]) -> dict:
    return {"schema_version": "0.2.0",
            "project": {"name": "t", "width": 1920, "height": 1080, "fps": 30, "source_frame_rate_mode": "cfr"},
            "tracks": [{"id": tid, "type": kind, "clips": clips} for tid, kind, clips in tracks]}


class TestWhatIsWrongInAFrame(unittest.TestCase):
    def test_a_frame_black_but_for_a_speck_is_black(self):
        frame = _frame()
        frame[0, 0] = 255
        self.assertTrue(look.is_black(frame))

    def test_a_title_on_black_is_not(self):
        frame = _frame()
        frame[40:50, 40:120] = 255
        self.assertFalse(look.is_black(frame))

    def test_a_caption_reaching_the_edge_is_off_screen(self):
        frame = _frame()
        frame[70:80, 100:160] = 255
        self.assertEqual(look.edges(frame), ["right"])

    def test_a_caption_inside_the_frame_reaches_no_edge(self):
        frame = _frame()
        frame[70:80, 40:120] = 255
        self.assertEqual(look.edges(frame), [])

    def test_how_much_of_a_face_a_graphic_covers(self):
        frame = _frame()
        frame[20:60, 20:60] = 255
        self.assertAlmostEqual(look.covered(frame, (30, 30, 40, 40)), 0.5625)


class TestWhereToLook(unittest.TestCase):
    def test_after_each_cut_in_each_clip_and_gap_and_at_each_caption_and_graphic(self):
        ir = _ir(("V1", "video", [_clip(0.0, 4.0), _clip(6.0, 2.0)]),
                 ("Graphics", "graphics", [_clip(1.0, 2.0, text="Nomad jacket")]),
                 ("Captions", "captions", [_clip(6.0, 1.0, text="hello there")]))
        looks = [(round(lk.at, 3), lk.kind) for lk in look.where(ir)]
        # A caption in its last frame, when all its words are up.
        self.assertEqual(looks, [(0.0 + 2.0, "black"), (6.0, "black"), (7.0, "black"), (5.0, "black"),
                                 (2.0, "graphic"), (6.967, "caption")])

    def test_a_video_of_titles_alone_is_looked_at_where_the_main_track_is_empty(self):
        ir = _ir(("V1", "video", []), ("Graphics", "graphics", [_clip(0.0, 3.0, text="Frameflow")]))
        self.assertEqual([(lk.at, lk.kind) for lk in look.where(ir)], [(1.5, "black"), (1.5, "graphic")])


class TestInOpenShotsEngine(unittest.TestCase):
    """A caption drawn where it belongs, then moved off the right edge, through OpenShot's own engine."""

    def setUp(self):
        from project import openshot_build
        from project.openshot_template import profile_dirs
        if not profile_dirs() or openshot_build.install_dir() is None:
            self.skipTest("OpenShot is not installed")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        ffmpeg = _find_tool("ffmpeg")
        self.picture = self.root / "picture.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=1920x1080:r=30:d=3",
                        "-pix_fmt", "yuv420p", str(self.picture)], check=True)
        # A white line of "text" where Frameflow puts a caption, on a transparent frame.
        self.caption = self.root / "caption.mov"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                        "color=c=black@0.0:s=1920x1080:r=30:d=3,format=rgba,"
                        "drawbox=x=760:y=880:w=400:h=60:color=white@1.0:t=fill:replace=1",
                        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(self.caption)],
                       check=True)

    def problems(self, main: list[dict], caption: dict) -> list[str]:
        from project.compile_osp import compile_file
        ir = _ir(("V1", "video", [dict(c, source=self.picture.as_posix()) for c in main]),
                 ("Captions", "captions", [dict(caption, source=self.caption.as_posix())]))
        for track in ir["tracks"]:
            for n, clip in enumerate(track["clips"], start=1):
                clip["id"] = f"clip{n}"
        (self.root / "p.ir.json").write_text(json.dumps(ir), encoding="utf-8")
        return look.check(compile_file(self.root / "p.ir.json", self.root / "p.osp"), ir)[0]

    def test_a_caption_in_its_place_is_fine(self):
        self.assertEqual(self.problems([_clip(0.0, 3.0)], _clip(1.0, 1.0, text="hello there")), [])

    def test_a_caption_moved_off_the_right_edge_is_reported(self):
        moved = _clip(1.0, 1.0, text="hello there", transform={"position": {"x": 0.4}})
        self.assertEqual(self.problems([_clip(0.0, 3.0)], moved),
                         ['0:01.97: the caption "hello there" runs off the right edge'])

    def test_a_gap_in_the_main_track_is_black_even_under_a_caption(self):
        self.assertEqual(self.problems([_clip(0.0, 1.0), _clip(2.0, 1.0)], _clip(1.0, 1.0, text="hello there")),
                         ["0:01.50: black, where the main track has nothing"])


if __name__ == "__main__":
    unittest.main()
