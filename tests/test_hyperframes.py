"""Graphics rendered by HyperFrames."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import hyperframes
from project.media import _find_tool


def _project(width=1920, height=1080):
    return {"name": "p", "width": width, "height": height, "fps": 30.0, "source_frame_rate_mode": "cfr"}


class TestCard(unittest.TestCase):
    def test_text_is_escaped(self):
        page = hyperframes.card_html("<b>Tom & Jerry</b>", 1920, 1080, 30, 2)
        self.assertIn("&lt;b&gt;Tom &amp; Jerry&lt;/b&gt;", page)
        self.assertNotIn("<b>Tom", page)

    def test_the_card_takes_the_projects_size(self):
        page = hyperframes.card_html("Hi", 1080, 1920, 30, 2)
        self.assertIn('data-width="1080" data-height="1920"', page)

    def test_frame_rates_are_written_as_hyperframes_accepts_them(self):
        self.assertEqual(hyperframes._rate(30.0), "30")
        self.assertEqual(hyperframes._rate(29.97), "30000/1001")
        self.assertIn('data-fps="30"', hyperframes.card_html("Hi", 1920, 1080, 30.0, 2))

    def test_a_render_is_reused(self):
        clip = {"id": "clip1", "timeline_start": 0, "timeline_duration": 2.0,
                "generator": "hyperframes", "text": "Hello"}
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake_render(composition, out, fps):
                calls.append(composition)
                out.write_bytes(b"mov")
                return out

            with mock.patch.object(hyperframes, "render", fake_render):
                first = hyperframes.render_clip(clip, _project(), Path(tmp))
                second = hyperframes.render_clip(clip, _project(), Path(tmp))
                hyperframes.render_clip(dict(clip, text="Other"), _project(), Path(tmp))
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)

    def test_render_generated_gives_the_clip_its_file(self):
        ir = {"project": _project(), "tracks": [{"id": "Graphics", "type": "graphics", "clips": [
            {"id": "clip1", "timeline_start": 3.0, "timeline_duration": 2.0,
             "generator": "hyperframes", "text": "Hello"}]}]}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(hyperframes, "render", lambda c, out, fps: out):
            hyperframes.render_generated(ir, Path(tmp))
        clip = ir["tracks"][0]["clips"][0]
        self.assertTrue(clip["source"].endswith(".mov"))
        self.assertEqual((clip["source_in"], clip["source_out"]), (0.0, 2.0))


class TestRealRender(unittest.TestCase):
    def test_a_card_renders_with_a_transparent_background(self):
        if shutil.which("npx") is None:
            self.skipTest("Node.js is not installed")
        clip = {"id": "clip1", "timeline_start": 0, "timeline_duration": 1.0, "text": "Hello"}
        with tempfile.TemporaryDirectory() as tmp:
            mov = hyperframes.render_clip(clip, _project(640, 360), Path(tmp))
            probe = subprocess.run([_find_tool("ffprobe"), "-v", "error", "-show_entries",
                                    "stream=pix_fmt,width,height", "-of", "csv=p=0", str(mov)],
                                   capture_output=True, text=True)
            corner = subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-ss", "0.5", "-i", str(mov),
                                     "-frames:v", "1", "-vf", "alphaextract,crop=40:40:0:0",
                                     "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
        self.assertEqual(probe.stdout.strip(), "640,360,yuva444p12le")
        self.assertEqual(max(corner.stdout), 0)          # nothing drawn in the corner


if __name__ == "__main__":
    unittest.main()
