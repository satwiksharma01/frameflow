"""A small preview of every build, rendered by OpenShot's own engine for the app to play."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import openshot_build, preview
from project.media import MediaError, _find_tool


class TestPreview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_preview_is_540_on_its_shorter_side(self):
        self.assertEqual(preview.size(1080, 1920), (540, 960))
        self.assertEqual(preview.size(1920, 1080), (960, 540))
        self.assertEqual(preview.size(1080, 1080), (540, 540))

    def test_a_failed_render_leaves_nothing(self):
        out = self.root / "v-preview.mp4"

        def fails(script, *args, cwd=None, timeout=3600):
            Path(args[1]).write_bytes(b"half")       # the part file OpenShot had begun
            return subprocess.CompletedProcess(args, 1, "", "boom")
        with mock.patch.object(openshot_build, "install_dir", lambda: self.root), \
                mock.patch.object(openshot_build, "run_script", fails), \
                self.assertRaises(preview.PreviewError) as raised:
            preview.render(self.root / "v.osp", out, 540, 960)
        self.assertIn("boom", str(raised.exception))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_render_that_times_out_is_a_skipped_preview(self):
        out = self.root / "v-preview.mp4"

        def times_out(script, *args, cwd=None, timeout=3600):
            Path(args[1]).write_bytes(b"half")
            raise subprocess.TimeoutExpired(["openshot-qt-cli.exe"], timeout)
        with mock.patch.object(openshot_build, "install_dir", lambda: self.root), \
                mock.patch.object(openshot_build, "run_script", times_out), \
                self.assertRaises(preview.PreviewError) as raised:
            preview.render(self.root / "v.osp", out, 540, 960)
        self.assertIn("OpenShot could not render the preview: ", str(raised.exception))
        self.assertIn("timed out after 3600 seconds", str(raised.exception))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_first_build_of_frameflows_openshot_that_fails_is_a_skipped_preview(self):
        for error in (subprocess.CalledProcessError(1, ["cmd", "/c", "mklink", "/J"]),
                      openshot_build.BuildError("this OpenShot's classes/app.py is not the one Frameflow's patch "
                                                "was written for")):
            def build():
                raise error
            with self.subTest(type(error).__name__), \
                    mock.patch.object(openshot_build, "install_dir", lambda: self.root), \
                    mock.patch.object(openshot_build, "is_built", lambda: False), \
                    mock.patch.object(openshot_build, "build", build), \
                    self.assertRaises(preview.PreviewError) as raised:
                preview.render(self.root / "v.osp", self.root / "v-preview.mp4", 540, 960)
            self.assertEqual(str(raised.exception), f"OpenShot could not render the preview: {error}")
            self.assertEqual(list(self.root.iterdir()), [])

    def test_without_openshot_there_is_no_preview(self):
        with mock.patch.object(openshot_build, "install_dir", lambda: None), \
                self.assertRaises(preview.PreviewError) as raised:
            preview.render(self.root / "v.osp", self.root / "v-preview.mp4", 540, 960)
        self.assertEqual(str(raised.exception), "OpenShot is not installed")

    def test_a_real_project_previews_with_its_length_picture_and_sound(self):
        try:
            ffprobe = _find_tool("ffprobe")
        except MediaError:
            self.skipTest("ffprobe is not installed")
        if not openshot_build.is_built():
            self.skipTest("Frameflow's OpenShot is not built")
        from project.compile_osp import compile_file
        clip = self.root / "clip.mp4"
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:d=2",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-pix_fmt", "yuv420p", "-shortest",
                        str(clip)], check=True)
        ir = {"schema_version": "0.2.0",
              "project": {"name": "p", "width": 1080, "height": 1920, "fps": 30, "source_frame_rate_mode": "cfr"},
              "tracks": [{"id": "V1", "type": "video", "clips": [
                  {"id": "clip1", "source": clip.as_posix(), "source_in": 0.0, "source_out": 2.0,
                   "timeline_start": 0.0, "timeline_duration": 2.0}]}]}
        (self.root / "p.ir.json").write_text(json.dumps(ir), encoding="utf-8")
        project = compile_file(self.root / "p.ir.json", self.root / "p.osp")

        out = preview.render(project, self.root / "p-preview.mp4", *preview.size(1080, 1920))
        found = json.loads(subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out)],
            capture_output=True, text=True, check=True).stdout)
        streams = {s["codec_type"]: s for s in found["streams"]}
        self.assertEqual((streams["video"]["codec_name"], streams["video"]["width"], streams["video"]["height"]),
                         ("h264", 540, 960))
        self.assertEqual(streams["audio"]["codec_name"], "aac")
        self.assertAlmostEqual(float(found["format"]["duration"]), 2.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
