"""Making a video from a prompt: storyboard checks and the project it builds."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import produce
from project.media import _find_tool, level_db, loudness
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

    def test_b_roll_goes_over_footage_and_comes_from_the_assets(self):
        board = self.board(
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 1, "end": 4}, "reason": "r",
             "broll": [{"path": "broll.mp4", "when": "this jacket", "start": 1.0}, {"path": "other.mp4"}]},
            {"visual": {"type": "title", "text": "Hi"}, "duration": 2, "reason": "r",
             "broll": [{"path": "shot.png"}]})
        validate(board, "storyboard")
        problems = produce.check_storyboard(board, self.INPUTS)
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("'other.mp4' is not one of the creator's assets", problems[0])
        self.assertIn("scene 2 (title): B-roll goes over footage", problems[1])

    def test_a_look_is_one_of_the_creator_s_luts_or_openshot_s(self):
        scene = {"visual": {"type": "footage", "source": "talk.mp4", "start": 1, "end": 4}, "reason": "r"}
        with tempfile.TemporaryDirectory() as tmp:
            install = Path(tmp)
            (install / "colors" / "film").mkdir(parents=True)
            (install / "colors" / "film" / "warm_film.cube").write_text("LUT_3D_SIZE 2\n")
            (install / "mine.cube").write_text("LUT_3D_SIZE 2\n")
            inputs = dict(self.INPUTS, looks=[{"path": (install / "mine.cube").as_posix()},
                                              {"path": (install / "gone.cube").as_posix()}])
            with mock.patch.object(produce.openshot_build, "install_dir", lambda: install):
                found = {name: produce.check_storyboard(self.board(scene, look={"path": name}), inputs)
                         for name in ("mine.cube", "warm_film.cube", "teal.cube", "gone.cube")}
        validate(self.board(scene, look={"path": "mine.cube", "intensity": 0.7}), "storyboard")
        self.assertEqual((found["mine.cube"], found["warm_film.cube"]), ([], []))
        self.assertEqual(found["teal.cube"], ["look 'teal.cube' is not one of the creator's LUTs or OpenShot's own"])
        self.assertIn("is not there any more", found["gone.cube"][0])

    def test_only_a_product_card_has_a_price(self):
        def scene(card):
            return self.board({"visual": {"type": "asset", "path": "shot.png"}, "duration": 2, "reason": "r",
                               "cards": [card]})
        validate(scene({"kind": "product", "text": "Nomad", "price": "$129", "when": "Nomad"}), "storyboard")
        validate(scene({"kind": "lower_third", "text": "Satwik", "subtitle": "Founder"}), "storyboard")
        with self.assertRaises(ValidationError):
            validate(scene({"kind": "lower_third", "text": "Satwik", "price": "$129"}), "storyboard")


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
        # The 330 Hz tone reads -21.9 LUFS: raised 7.9 dB to the platforms' -14, its peaks still under -1 dBTP.
        self.assertAlmostEqual(voice["volume_db"], 7.9, delta=0.3)
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

    def _said(self, text, out, voice=None):
        """A narration line whose words come 0.25 s apart, from 0.1 s."""
        out.parent.mkdir(parents=True, exist_ok=True)
        out.with_suffix(".json").write_text(json.dumps(
            [{"start": 0.1 + 0.25 * i, "end": 0.35 + 0.25 * i, "text": w} for i, w in enumerate(text.split())]))
        return _tone(out, 1.0)

    def _image(self):
        image = self.folder / "shot.png"
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=800x600",
                        "-frames:v", "1", str(image)], check=True)
        return {"footage": [], "assets": [{"path": image.as_posix(), "kind": "image"}], "music": []}

    def test_a_product_card_comes_up_when_the_product_is_named(self):
        board = {"script": "s", "scenes": [
            {"visual": {"type": "title", "text": "Hook"}, "duration": 2.0, "reason": "r"},
            {"visual": {"type": "asset", "path": "shot.png"}, "narration": "Meet the Nomad, only $129.",
             "duration": 4.0, "reason": "r",
             "cards": [{"kind": "product", "text": "Nomad jacket", "subtitle": "Packs into its own pocket",
                        "price": "$129", "when": "the nomad"}]}]}
        with mock.patch.object(produce.voiceover, "speak", self._said):
            ir = produce.build_ir(self.folder, board, BRIEF, self._image())
        validate(ir, "ir")
        title, card = ir["tracks"][1]["clips"]
        # "the" is the second word, said 0.35 s into the line, which starts after the 2 s title and the lead.
        self.assertAlmostEqual(card["timeline_start"], 2.0 + produce.VOICE_LEAD_SECONDS + 0.35, delta=1 / 30)
        self.assertEqual(card["timeline_duration"], produce.CARD_SECONDS)
        self.assertEqual((card["text"], card["generator_params"]), (
            "Nomad jacket", {"layout": "product", "subtitle": "Packs into its own pocket", "price": "$129"}))

    def test_over_footage_a_card_comes_up_when_the_recording_says_it(self):
        if not FOOTAGE.exists():
            self.skipTest("media not present")
        (self.folder / "f").mkdir()
        (self.folder / "f" / "timing.json").write_text(json.dumps({"words": [
            {"start": 0.2, "end": 0.5, "text": " Hello"}, {"start": 0.5, "end": 0.8, "text": " there"},
            {"start": 2.0, "end": 2.3, "text": " Hello"}, {"start": 2.3, "end": 2.6, "text": " there."}]}))
        inputs = {"footage": [{"name": FOOTAGE.name, "source": FOOTAGE.as_posix(), "duration": 25.7,
                               "folder": "f"}], "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": FOOTAGE.name, "start": 1.0, "end": 4.0}, "reason": "r",
             "cards": [{"kind": "lower_third", "text": "Satwik Sharma", "when": "Hello, there!"}]}]}
        ir = produce.build_ir(self.folder, board, dict(BRIEF, aspect="16:9"), inputs)
        self.assertEqual(ir["tracks"][1]["clips"][0]["timeline_start"], 1.0)   # said at 2.0 s, inside the span

    def test_b_roll_cuts_away_when_the_recording_says_its_words(self):
        if not FOOTAGE.exists():
            self.skipTest("media not present")
        (self.folder / "f").mkdir()
        (self.folder / "f" / "timing.json").write_text(json.dumps({"words": [
            {"start": 2.0, "end": 2.3, "text": " this"}, {"start": 2.3, "end": 2.6, "text": " jacket"}]}))
        inputs = dict(self._image(), footage=[{"name": FOOTAGE.name, "source": FOOTAGE.as_posix(),
                                               "duration": 25.7, "folder": "f"}])
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": FOOTAGE.name, "start": 1.0, "end": 4.0}, "reason": "r",
             "broll": [{"path": "shot.png", "when": "jacket", "duration": 5.0}]}]}
        with mock.patch.object(produce.broll, "still_to_clip", lambda image, out, *a: _tone(out, 1.0)):
            ir = produce.build_ir(self.folder, board, dict(BRIEF, aspect="16:9"), inputs)
        validate(ir, "ir")
        self.assertEqual([t["id"] for t in ir["tracks"]], ["V1", "B-roll"])
        cutaway = ir["tracks"][1]["clips"][0]
        # "jacket" is said 1.3 s into the span; the cutaway stops with the scene, 1.7 s later.
        self.assertEqual((cutaway["timeline_start"], cutaway["timeline_duration"]), (1.3, 1.7))
        self.assertEqual(ir["tracks"][0]["clips"][0]["source_out"], 4.0)    # the recording plays on beneath

    def test_a_look_grades_the_picture_and_not_the_graphics(self):
        lut = self.folder / "warm.cube"
        lut.write_text("LUT_3D_SIZE 2\n")
        inputs = dict(self._image(), looks=[{"path": lut.as_posix()}])
        board = {"script": "s", "look": {"path": "warm.cube", "intensity": 0.7}, "scenes": [
            {"visual": {"type": "title", "text": "Hook"}, "duration": 2.0, "reason": "r"},
            {"visual": {"type": "asset", "path": "shot.png"}, "duration": 2.0, "reason": "r"}]}
        ir = produce.build_ir(self.folder, board, BRIEF, inputs)
        validate(ir, "ir")
        picture, title = ir["tracks"][0]["clips"][0], ir["tracks"][1]["clips"][0]
        self.assertEqual(picture["effects"], [{"type": "lut", "params": {"path": lut.as_posix(), "intensity": 0.7}}])
        self.assertNotIn("effects", title)
        board.pop("look")           # without a look, nothing is graded
        plain = produce.build_ir(self.folder, board, BRIEF, inputs)
        self.assertFalse(any("effects" in c for t in plain["tracks"] for c in t["clips"]))

    def test_a_card_stops_at_the_end_of_its_scene(self):
        board = {"script": "s", "scenes": [
            {"visual": {"type": "asset", "path": "shot.png"}, "duration": 2.0, "reason": "r",
             "cards": [{"kind": "lower_third", "text": "Satwik Sharma", "duration": 5.0}]}]}
        ir = produce.build_ir(self.folder, board, BRIEF, self._image())
        card = ir["tracks"][1]["clips"][0]
        self.assertEqual((card["timeline_start"], card["timeline_duration"]), (0.0, 2.0))   # from the scene's start
        self.assertEqual(card["generator_params"], {"layout": "lower_third"})

    def test_cards_without_their_moment_or_on_top_of_another_graphic_are_reported(self):
        board = {"script": "s", "scenes": [
            {"visual": {"type": "asset", "path": "shot.png"}, "narration": "Meet the Nomad", "reason": "r",
             "cards": [{"kind": "product", "text": "Nomad", "when": "passport"}]},
            {"visual": {"type": "title", "text": "Hook"}, "duration": 2.0, "reason": "r",
             "cards": [{"kind": "lower_third", "text": "Satwik Sharma"}]}]}
        with mock.patch.object(produce.voiceover, "speak", self._said), \
                self.assertRaises(produce.ProduceError) as cm:
            produce.build_ir(self.folder, board, BRIEF, self._image())
        self.assertIn("'passport' is not said in scene 1", str(cm.exception))
        self.assertIn("scene 2: the 'Satwik Sharma' card would be on screen with another graphic",
                      str(cm.exception))

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
        self.assertEqual(clip["volume_db"], level_db(*loudness(FOOTAGE)))   # levelled for the platform, not muted
        self.assertNotIn("transform", clip)                              # 16:9 footage fits as it is
        self.assertEqual(ir["project"]["fps"], 30)                       # the footage's own rate


class TestCuttingToTheBeat(unittest.TestCase):
    GRID = [round(0.1 + 0.5 * k, 6) for k in range(60)]     # 120 BPM from 0.1 s, every beat on a frame

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        speak = mock.patch.object(produce.voiceover, "speak", lambda text, out, voice=None: _tone(out, 1.0))
        speak.start()
        self.addCleanup(speak.stop)

    def _build(self, scenes: list[dict], grid: list[float], inputs: dict | None = None) -> dict:
        board = {"script": "s", "music": {"path": "song.mp3", "cut_to_beat": True}, "scenes": scenes}
        validate(board, "storyboard")
        inputs = {"footage": [], "assets": [], "music": [{"path": "C:/x/song.mp3", "duration": 60.0}], **(inputs or {})}
        with mock.patch.object(produce.beats, "beats", lambda path: grid):
            return produce.build_ir(self.folder, board, dict(BRIEF, aspect="16:9"), inputs)

    def test_each_cut_moves_to_the_nearest_beat(self):
        ir = self._build([{"visual": {"type": "title", "text": "One"}, "duration": 2.0, "reason": "r"},
                          {"visual": {"type": "title", "text": "Two"}, "duration": 1.3, "reason": "r"}], self.GRID)
        titles = next(t for t in ir["tracks"] if t["id"] == "Graphics")["clips"]
        # 2.0 s ends nearest the beat at 2.1 s; then 2.1 + 1.3 = 3.4 s, nearest the beat at 3.6 s.
        self.assertEqual([(c["timeline_start"], c["timeline_duration"]) for c in titles], [(0.0, 2.1), (2.1, 1.5)])

    def test_a_cut_never_shortens_the_narration(self):
        # One second of voice needs 1.5 s; the nearer beat, at 1.4 s, would cut off its tail.
        grid = [round(0.2 + 0.6 * k, 6) for k in range(60)]
        ir = self._build([{"visual": {"type": "title", "text": "Meet it"}, "narration": "Meet it", "reason": "r"}], grid)
        self.assertEqual(next(t for t in ir["tracks"] if t["id"] == "Graphics")["clips"][0]["timeline_duration"], 2.0)

    def test_a_cut_never_runs_past_the_end_of_a_clip(self):
        clip = {"assets": [{"path": "C:/x/walk.mp4", "kind": "clip", "duration": 2.0, "size": "1920x1080"}]}
        ir = self._build([{"visual": {"type": "asset", "path": "walk.mp4"}, "reason": "r"}], self.GRID, clip)
        # The nearer beat, at 2.1 s, needs more of the 2 s clip than there is.
        self.assertEqual(ir["tracks"][0]["clips"][0]["source_out"], 1.6)

    def test_a_cut_in_footage_that_is_heard_does_not_move_into_a_word(self):
        if not FOOTAGE.exists():
            self.skipTest("media not present")
        (self.folder / "f").mkdir()
        (self.folder / "f" / "timing.json").write_text(json.dumps({"words": [
            {"start": 1.0, "end": 1.5, "text": " Hello"}, {"start": 1.5, "end": 2.0, "text": " there."},
            {"start": 2.2, "end": 2.6, "text": " Again"}]}))
        footage = {"footage": [{"name": FOOTAGE.name, "source": FOOTAGE.as_posix(), "duration": 25.7, "folder": "f"}]}

        def cut(grid):
            ir = self._build([{"visual": {"type": "footage", "source": FOOTAGE.name, "start": 1.0, "end": 2.1},
                               "reason": "r"}], grid, footage)
            return ir["tracks"][0]["clips"][0]["source_out"]

        # The pause after "there." runs 2.0-2.2 s: the cut moves to a beat inside it...
        self.assertEqual(cut([round(0.5 * k, 6) for k in range(60)]), 2.0)
        # ...but not to the nearest beats when they are over "Again" or "there."
        self.assertEqual(cut([round(0.25 + 0.5 * k, 6) for k in range(60)]), 2.1)


class TestRequests(unittest.TestCase):
    def test_the_storyboard_request_gives_the_music_s_tempo(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / produce.INPUTS_FILE).write_text(json.dumps(
                {"prompt": "p", "script": None, "footage": [], "assets": [],
                 "music": [{"path": "C:/x/song.mp3", "duration": 60.0}]}), encoding="utf-8")
            (folder / produce.BRIEF_FILE).write_text(json.dumps(BRIEF), encoding="utf-8")
            with mock.patch.object(produce.beats, "beats", lambda path: [0.1 + 0.5 * k for k in range(100)]):
                request = produce.storyboard_request(folder).read_text(encoding="utf-8")
        self.assertIn("`song.mp3` is at 120 BPM, a beat every 0.50 s", request)
        self.assertIn("`cut_to_beat`", request)

    def test_the_storyboard_request_offers_the_creator_s_looks_and_openshot_s(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "colors" / "film_&_vintage").mkdir(parents=True)
            (folder / "colors" / "film_&_vintage" / "warm_film.cube").write_text("LUT_3D_SIZE 2\n")
            (folder / produce.BRIEF_FILE).write_text(json.dumps(BRIEF), encoding="utf-8")
            requests = []
            for looks, install in (([{"path": "C:/x/mine.cube"}], folder), ([], None)):
                (folder / produce.INPUTS_FILE).write_text(json.dumps(
                    {"prompt": "p", "script": None, "footage": [], "assets": [], "music": [], "looks": looks}),
                    encoding="utf-8")
                with mock.patch.object(produce.openshot_build, "install_dir", lambda: install):
                    requests.append(produce.storyboard_request(folder).read_text(encoding="utf-8"))
        offered, plain = requests
        self.assertIn("give it a `look`", offered)
        self.assertIn("one of the creator's own LUTs (`mine.cube`), or one of OpenShot's "
                      "(film & vintage: `warm_film.cube`)", offered)
        self.assertNotIn("give it a `look`", plain)     # no LUT of the creator's, and no OpenShot

    def test_a_look_given_at_prepare_must_be_a_lut(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "notes.cube").write_text("a colour I like")
            (folder / "warm.cube").write_text('TITLE "warm"\nLUT_1D_SIZE 2\n0 0 0\n1 1 1\n')
            with self.assertRaises(produce.ProduceError):
                produce.prepare(folder / "out", "p", None, [], [], [], looks=[folder / "notes.cube"])
            produce.prepare(folder / "out", "p", None, [], [], [], looks=[folder / "warm.cube"])
            inputs = json.loads((folder / "out" / produce.INPUTS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(inputs["looks"], [{"path": (folder / "warm.cube").resolve().as_posix()}])

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

    def test_the_storyboard_request_passes_on_the_brand_kit(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / produce.INPUTS_FILE).write_text('{"prompt": "p", "script": null, "footage": [], '
                                                      '"assets": [], "music": []}', encoding="utf-8")
            (folder / produce.BRIEF_FILE).write_text(json.dumps(BRIEF), encoding="utf-8")
            (folder / "brand.json").write_text('{"accent": "#FF3366"}', encoding="utf-8")
            with mock.patch.object(produce.hyperframes, "BRAND_FILE", folder / "brand.json"):
                request = produce.storyboard_request(folder).read_text(encoding="utf-8")
            (folder / "brand.json").unlink()
            with mock.patch.object(produce.hyperframes, "BRAND_FILE", folder / "brand.json"):
                plain = produce.storyboard_request(folder).read_text(encoding="utf-8")
        self.assertIn("#FF3366", request)
        self.assertNotIn("the creator's brand kit", plain)


if __name__ == "__main__":
    unittest.main()
