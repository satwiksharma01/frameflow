"""Making a video from a prompt: storyboard checks and the project it builds."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import produce
from project.media import _find_tool
from project.validate import ValidationError, validate

REPO_ROOT = Path(__file__).resolve().parent.parent
FOOTAGE = REPO_ROOT / "media" / "meet-recording-cfr30.mp4"

BRIEF = {"title": "Nomad reel", "format": "product reel", "aspect": "9:16", "target_seconds": 15,
         "audience": "travellers", "tone": "upbeat", "summary": "A launch reel."}


def _tone(path: Path, seconds: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=330:duration={seconds}", str(path)], check=True)
    return path


class TestStoryboardChecks(unittest.TestCase):
    INPUTS = {"footage": [{"name": "talk.mp4", "source": "C:/x/talk.mp4", "duration": 20.0, "folder": "f"}],
              "assets": [{"path": "C:/x/shot.png", "kind": "image"},
                         {"path": "C:/x/broll.mp4", "kind": "clip", "duration": 5.0, "size": "1920x1080"}],
              "music": [{"path": "C:/x/song.mp3", "duration": 60.0}]}

    def board(self, *scenes, **extra):
        return {"script": "s", "scenes": list(scenes), **extra}

    def test_a_good_storyboard_passes(self):
        board = self.board(
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 1, "end": 4}, "reason": "r"},
            {"visual": {"type": "asset", "path": "shot.png"}, "duration": 2, "reason": "r"},
            {"visual": {"type": "title", "text": "Hi"}, "narration": "Hello", "reason": "r"},
            music={"path": "song.mp3"})
        validate(board, "storyboard")
        self.assertEqual(produce.check_storyboard(board, self.INPUTS), [])

    def test_unknown_inputs_and_spans_past_the_end_are_named(self):
        board = self.board(
            {"visual": {"type": "footage", "source": "other.mp4", "start": 0, "end": 1}, "reason": "r"},
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 18, "end": 25}, "reason": "r"},
            {"visual": {"type": "asset", "path": "nope.png"}, "duration": 1, "reason": "r"},
            {"visual": {"type": "asset", "path": "broll.mp4", "start": 6}, "reason": "r"},
            music={"path": "other.mp3"})
        problems = produce.check_storyboard(board, self.INPUTS)
        self.assertEqual(len(problems), 5, problems)

    def test_a_title_needs_a_duration_or_narration(self):
        board = self.board({"visual": {"type": "title", "text": "Hi"}, "reason": "r"})
        self.assertIn("duration", produce.check_storyboard(board, self.INPUTS)[0])

    def test_the_schema_rejects_an_unknown_visual(self):
        with self.assertRaises(ValidationError):
            validate(self.board({"visual": {"type": "stock", "query": "rain"}, "reason": "r"}), "storyboard")


class TestBuildingTheProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        # Every narration line is read as one second of tone.
        speak = mock.patch.object(produce.voiceover, "speak", lambda text, out, voice=None: _tone(out, 1.0))
        speak.start()
        self.addCleanup(speak.stop)

    def test_scenes_become_tracks_in_playing_order(self):
        image = self.folder / "shot.png"
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=800x600",
                        "-frames:v", "1", str(image)], check=True)
        music = _tone(self.folder / "song.wav", 30.0)
        inputs = {"footage": [], "assets": [{"path": image.as_posix(), "kind": "image"}],
                  "music": [{"path": music.as_posix(), "duration": 30.0}]}
        board = {"script": "s", "music": {"path": "song.wav"}, "scenes": [
            {"visual": {"type": "title", "text": "Hook"}, "duration": 2.0, "reason": "r"},
            {"visual": {"type": "asset", "path": "shot.png"}, "narration": "Meet it", "caption": "Meet it",
             "reason": "r"},
        ]}
        ir = produce.build_ir(self.folder, board, BRIEF, inputs)
        validate(ir, "ir")
        tracks = {t["id"]: t for t in ir["tracks"]}
        self.assertEqual([t["id"] for t in ir["tracks"]], ["V1", "Graphics", "Captions", "Voice", "Music"])
        self.assertEqual((ir["project"]["width"], ir["project"]["height"]), (1080, 1920))

        still = tracks["V1"]["clips"][0]
        self.assertEqual(still["timeline_start"], 2.0)                 # after the 2s title
        self.assertAlmostEqual(still["timeline_duration"], 1.5, places=1)  # 1s voice + lead and tail
        self.assertEqual(still["volume_db"], produce.UNDER_NARRATION_DB)
        self.assertEqual(still["transform"], {"fill": True})                # a 9:16 reel is filled
        self.assertTrue(Path(still["source"]).exists())

        title = tracks["Graphics"]["clips"][0]
        self.assertEqual((title["text"], title["generator_params"]), ("Hook", {"layout": "title"}))
        self.assertEqual(tracks["Captions"]["clips"][0]["timeline_start"], 2.0)
        voice = tracks["Voice"]["clips"][0]
        self.assertAlmostEqual(voice["timeline_start"], 2.0 + produce.VOICE_LEAD_SECONDS)
        song = tracks["Music"]["clips"][0]
        self.assertAlmostEqual(song["timeline_duration"], 3.5, places=1)   # cut to the video's length
        self.assertEqual(song["volume_db"], -18.0)                          # under a voice

    def test_spoken_captions_follow_the_narration(self):
        def speak(text, out, voice=None):
            out.with_suffix(".json").parent.mkdir(parents=True, exist_ok=True)
            out.with_suffix(".json").write_text(json.dumps(
                [{"start": 0.1, "end": 0.5, "text": text.split()[0]}, {"start": 0.5, "end": 1.0, "text": text.split()[1]}]))
            return _tone(out, 1.0)

        board = {"script": "s", "spoken_captions": True, "scenes": [
            {"visual": {"type": "title", "text": "Hook"}, "narration": "Meet Nomad", "reason": "r"},
            {"visual": {"type": "title", "text": "Price"}, "narration": "Only today", "caption": "Sale",
             "reason": "r"}]}
        with mock.patch.object(produce.voiceover, "speak", speak), \
                mock.patch.object(produce.hyperframes, "render", lambda c, out, fps: out):
            ir = produce.build_ir(self.folder, board, BRIEF, {"footage": [], "assets": [], "music": []})
        validate(ir, "ir")
        self.assertEqual([t["id"] for t in ir["tracks"]], ["V1", "Graphics", "Captions", "Voice"])
        spoken, fixed = ir["tracks"][2]["clips"]
        self.assertEqual(spoken["text"], "Meet Nomad")                  # the second scene shows its own caption
        self.assertAlmostEqual(spoken["timeline_start"], produce.VOICE_LEAD_SECONDS + 0.1, places=1)
        self.assertEqual((fixed["text"], "source" in fixed), ("Sale", False))

    def test_narration_longer_than_its_footage_is_reported(self):
        if not FOOTAGE.exists():
            self.skipTest("media not present")
        inputs = {"footage": [{"name": FOOTAGE.name, "source": FOOTAGE.as_posix(), "duration": 25.7,
                               "folder": "f"}], "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": FOOTAGE.name, "start": 2.0, "end": 2.5},
             "narration": "This is far too long to say in half a second", "reason": "r"}]}
        with self.assertRaises(produce.ProduceError) as cm:
            produce.build_ir(self.folder, board, dict(BRIEF, aspect="16:9"), inputs)
        self.assertIn("lengthen the span", str(cm.exception))

    def test_footage_in_a_reel_keeps_the_face_in_frame(self):
        """A 1920x1080 recording in a 9:16 reel, the speaker standing right of centre at x=1500."""
        if not FOOTAGE.exists():
            self.skipTest("media not present")
        (self.folder / "f").mkdir()
        inputs = {"footage": [{"name": FOOTAGE.name, "source": FOOTAGE.as_posix(), "duration": 25.7,
                               "folder": "f"}], "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": FOOTAGE.name, "start": 1.0, "end": 4.0}, "reason": "r"}]}
        with mock.patch.object(produce.reframe, "face_centres", lambda video: [(t / 4, 1500.0) for t in range(40)]), \
                mock.patch.object(produce.reframe, "picture_area", lambda video: (0, 1920)):
            ir = produce.build_ir(self.folder, board, BRIEF, inputs)
        # The window (607.5 source px wide) centres on 1500: the picture moves left by 540 px of 1080.
        self.assertEqual(ir["tracks"][0]["clips"][0]["transform"], {"fill": True, "position": {"x": -0.888889}})
        self.assertTrue((self.folder / "f" / "framing-1080x1920.json").exists())

    def test_footage_keeps_its_own_sound_without_narration(self):
        if not FOOTAGE.exists():
            self.skipTest("media not present")
        inputs = {"footage": [{"name": FOOTAGE.name, "source": FOOTAGE.as_posix(), "duration": 25.7,
                               "folder": "f"}], "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": FOOTAGE.name, "start": 1.0, "end": 4.0}, "reason": "r"}]}
        ir = produce.build_ir(self.folder, board, dict(BRIEF, aspect="16:9"), inputs)
        clip = ir["tracks"][0]["clips"][0]
        self.assertEqual((clip["source_in"], clip["source_out"]), (1.0, 4.0))
        self.assertNotIn("volume_db", clip)
        self.assertNotIn("transform", clip)                              # 16:9 footage fits as it is
        self.assertEqual(ir["project"]["fps"], 30)                       # the footage's own rate


class TestRequests(unittest.TestCase):
    def test_open_questions_stop_the_storyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / produce.INPUTS_FILE).write_text('{"prompt": "p", "script": null, "footage": [], '
                                                      '"assets": [], "music": []}', encoding="utf-8")
            (folder / produce.BRIEF_FILE).write_text(json.dumps(dict(BRIEF, open_questions=["Price?"])),
                                                     encoding="utf-8")
            with self.assertRaises(produce.ProduceError) as cm:
                produce.storyboard_request(folder)
        self.assertIn("Price?", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
