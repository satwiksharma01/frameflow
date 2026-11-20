"""What the engine tells an app: the videos there are, one video's storyboard, a scene's thumbnail."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import app_api, app_think, editors, produce, storyboard_edit

REPO = Path(__file__).resolve().parent.parent
BRIEF = {"title": "Nomad reel", "format": "product reel", "aspect": "9:16", "target_seconds": 15,
         "audience": "a", "tone": "t", "summary": "s"}


class _Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def video(self, name: str, board: dict | None = None, inputs: dict | None = None, brief: dict | None = BRIEF,
              report: dict | None = None) -> Path:
        folder = self.root / name
        folder.mkdir()
        documents = {"inputs.json": inputs or {"footage": [], "assets": [], "music": []}, "brief.json": brief,
                     "storyboard.json": board, "build_report.json": report}
        for file, document in documents.items():
            if document is not None:
                (folder / file).write_text(json.dumps(document), encoding="utf-8")
        return folder


TITLE = {"visual": {"type": "title", "text": "Hook"}, "duration": 2.0, "reason": "r"}


class TestVideos(_Folder):
    def test_folders_with_inputs_are_listed_newest_first(self):
        old = self.video("old", {"script": "s", "scenes": [TITLE]})
        self.video("new", brief=None)
        (self.root / "not-a-video").mkdir()
        os.utime(old / "storyboard.json", (1_000_000_000, 1_000_000_000))
        os.utime(old / "inputs.json", (1_000_000_000, 1_000_000_000))
        cover = app_api.describe(old)["scenes"][0]["key"]
        self.assertEqual(app_api.videos(self.root), [
            {"folder": str(self.root / "new"), "title": "new", "has_storyboard": False, "built": False,
             "cover": None},
            {"folder": str(old), "title": "Nomad reel", "has_storyboard": True, "built": False, "cover": cover}])

    def test_a_broken_brief_does_not_hide_the_other_videos(self):
        self.video("good", {"script": "s", "scenes": [TITLE]})
        bad = self.video("bad")
        (bad / "brief.json").write_text("{half written")
        self.assertEqual(sorted(v["title"] for v in app_api.videos(self.root)), ["Nomad reel", "bad"])

    def test_a_root_that_is_not_there_has_no_videos(self):
        self.assertEqual(app_api.videos(self.root / "nowhere"), [])

    def test_videos_lists_a_folder_with_only_a_plan(self):
        folder = self.root / "plan-only"
        folder.mkdir()
        (folder / "plan_draft.json").write_text(json.dumps(BRIEF), encoding="utf-8")
        self.assertEqual(app_api.videos(self.root), [      # named by the draft's title, not the folder's
            {"folder": str(folder), "title": "Nomad reel", "has_storyboard": False, "built": False, "cover": None}])


class TestDescribe(_Folder):
    def test_a_footage_scene_says_the_words_inside_its_span(self):
        inputs = {"footage": [{"name": "talk.mp4", "source": "C:/x/talk.mp4", "duration": 20.0, "folder": "f"}],
                  "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 0.8, "end": 2.0}, "reason": "r",
             "caption": "Hi", "cards": [{"kind": "product", "text": "Nomad", "when": "Nomad"}],
             "broll": [{"path": "C:/x/walk.mp4", "when": "there"}]},
            {"visual": {"type": "title", "text": "Hook"}, "narration": "Meet it.", "reason": "r"},
            TITLE]}
        folder = self.video("v", board, inputs)
        (folder / "f").mkdir()
        (folder / "f" / "timing.json").write_text(json.dumps({"pauses": [], "words": [
            {"start": 1.0, "end": 1.3, "text": " Hello"}, {"start": 1.5, "end": 1.9, "text": " there."},
            {"start": 9.0, "end": 9.4, "text": " later"}]}))
        described = app_api.describe(folder)
        self.assertEqual({k: described[k] for k in ("title", "aspect", "target_seconds", "built", "sections", "report")},
                         {"title": "Nomad reel", "aspect": "9:16", "target_seconds": 15, "built": False,
                          "sections": [], "report": None})
        self.assertEqual([{k: v for k, v in s.items() if k != "key"} for s in described["scenes"]], [
            {"number": 1, "kind": "footage", "says": "Hello there.", "seconds": 1.2, "start": None,
             "source": "Your recording 0:00–0:02", "over": ["Caption: Hi", "Card: Nomad", "B-roll: walk.mp4"],
             "text": None, "narration": None, "caption": "Hi",
             "cards": [{"kind": "product", "text": "Nomad", "when": "Nomad"}],
             "broll": [{"path": "C:/x/walk.mp4", "when": "there"}]},
            {"number": 2, "kind": "title", "says": "Meet it.", "seconds": None, "start": None, "source": "Title",
             "over": [], "text": "Hook", "narration": "Meet it.", "caption": None, "cards": [], "broll": []},
            {"number": 3, "kind": "title", "says": "Hook", "seconds": 2.0, "start": None, "source": "Title",
             "over": [], "text": "Hook", "narration": None, "caption": None, "cards": [], "broll": []}])

    def test_an_unbuilt_scene_is_estimated_without_its_long_pauses(self):
        inputs = {"footage": [{"name": "talk.mp4", "source": "C:/x/talk.mp4", "duration": 20.0, "folder": "f"}],
                  "assets": [], "music": []}
        folder = self.video("v", {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 1.0, "end": 7.0}, "reason": "r"}]}, inputs)
        (folder / "f").mkdir()
        (folder / "f" / "timing.json").write_text(json.dumps({"words": [], "pauses": [{"start": 3.0, "end": 5.0}]}))
        # The build cuts the 2 s pause to a quarter second either side: 6 s of span plays as about 4.5.
        self.assertAlmostEqual(app_api.describe(folder)["scenes"][0]["seconds"], 4.5, delta=2 / 30)

    def test_two_unbuilt_scenes_meeting_in_a_long_pause_are_estimated_with_it_cut(self):
        inputs = {"footage": [{"name": "talk.mp4", "source": "C:/x/talk.mp4", "duration": 20.0, "folder": "f"}],
                  "assets": [], "music": []}
        folder = self.video("v", {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 1.0, "end": 5.0}, "reason": "r"},
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 5.0, "end": 9.0}, "reason": "r"}]}, inputs)
        (folder / "f").mkdir()
        (folder / "f" / "timing.json").write_text(json.dumps({"words": [], "pauses": [{"start": 4.0, "end": 6.0}]}))
        # As the build cuts it: the first ends a quarter second into the pause, the second starts a quarter before its end.
        first, second = (s["seconds"] for s in app_api.describe(folder)["scenes"])
        self.assertAlmostEqual(first, 3.25, delta=1 / 30)
        self.assertAlmostEqual(second, 3.25, delta=1 / 30)

    def test_describe_gives_a_version_its_history_and_the_whole_video_settings(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE], "spoken_captions": True,
                                  "sections": [{"title": "All", "from": 1}]})
        described = app_api.describe(folder)
        self.assertEqual(described["version"], storyboard_edit.version(folder))
        self.assertEqual((described["can_undo"], described["can_redo"]), (False, False))
        self.assertEqual(described["video"], {"spoken_captions": True, "has_music": False, "cut_to_beat": False,
                                              "look": None})
        self.assertEqual(described["sections"], [{"title": "All", "from": 1, "confirmed": False}])
        storyboard_edit.edit(folder, {"op": "rename_chapter", "number": 1, "title": "Everything"},
                             described["version"])
        again = app_api.describe(folder)
        self.assertEqual((again["can_undo"], again["sections"][0]["confirmed"]), (True, True))

    def test_two_scenes_with_the_same_picture_get_different_keys(self):
        keys = [s["key"] for s in app_api.describe(self.video("v", {"script": "s", "scenes": [TITLE, TITLE]}))["scenes"]]
        self.assertRegex(keys[0], r"^[0-9a-f]{12}-0$")
        self.assertEqual(keys[1], keys[0][:-1] + "1")

    def test_the_report_is_used_only_while_it_is_of_this_storyboard_and_brief(self):
        board = {"script": "s", "scenes": [TITLE], "sections": [{"title": "All", "from": 1}]}
        folder = self.video("v", board)
        report = {"of": produce.source_digest(folder), "seconds": 2.5, "target_seconds": 15,
                  "scenes": [{"start": 0.0, "end": 2.5}], "joins": None,
                  "picture": {"skipped": "OpenShot is not installed"}}
        (folder / "build_report.json").write_text(json.dumps(report))
        # An older storyboard file than its report says nothing: only what the build read counts.
        os.utime(folder / "build_report.json", (900_000_000, 900_000_000))
        built = app_api.describe(folder)
        self.assertEqual((built["built"], built["report"], built["sections"]),
                         (True, report, [{"title": "All", "from": 1, "confirmed": False}]))
        self.assertEqual((built["scenes"][0]["start"], built["scenes"][0]["seconds"]), (0.0, 2.5))

        (folder / "storyboard.json").write_text(json.dumps(dict(board, script="changed")))
        stale = app_api.describe(folder)
        self.assertEqual((stale["built"], stale["report"]), (False, None))
        self.assertEqual((stale["scenes"][0]["start"], stale["scenes"][0]["seconds"]), (None, 2.0))

        (folder / "storyboard.json").write_text(json.dumps(board))
        self.assertTrue(app_api.describe(folder)["built"])
        (folder / "brief.json").write_text(json.dumps(dict(BRIEF, aspect="16:9")))      # the brief changed
        self.assertFalse(app_api.describe(folder)["built"])

    def test_a_report_without_what_it_was_built_from_is_not_trusted(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE]},
                            report={"seconds": 2.5, "target_seconds": 15, "scenes": [], "joins": None,
                                    "picture": {"skipped": "x"}})
        self.assertFalse(app_api.describe(folder)["built"])
        (folder / "build_report.json").write_text("{half written")
        self.assertFalse(app_api.describe(folder)["built"])

    def test_describe_names_the_preview_only_while_its_report_is_current(self):
        board = {"script": "s", "scenes": [TITLE]}
        folder = self.video("v", board)
        (folder / "build_report.json").write_text(json.dumps({
            "of": produce.source_digest(folder), "seconds": 2.0, "target_seconds": 15,
            "scenes": [{"start": 0.0, "end": 2.0}], "joins": None, "picture": {"skipped": "x"},
            "preview": "Nomad-reel-preview.mp4"}))
        video = folder / "Nomad-reel-preview.mp4"
        video.write_bytes(b"mp4")
        self.assertEqual(app_api.describe(folder)["preview"], str(video.resolve()))
        (folder / "storyboard.json").write_text(json.dumps(dict(board, script="changed")))
        self.assertIsNone(app_api.describe(folder)["preview"])
        (folder / "storyboard.json").write_text(json.dumps(board))
        video.unlink()
        described = app_api.describe(folder)
        self.assertEqual((described["built"], described["preview"]), (True, None))

    def test_describe_says_whether_the_video_was_ever_built(self):
        board = {"script": "s", "scenes": [TITLE]}
        folder = self.video("v", board)
        self.assertFalse(app_api.describe(folder)["ever_built"])
        produce.project_path(folder, BRIEF).write_text("{}")       # a build's OpenShot project
        (folder / "storyboard.json").write_text(json.dumps(dict(board, script="changed")))
        described = app_api.describe(folder)
        self.assertEqual((described["built"], described["ever_built"]), (False, True))
        self.assertFalse(app_api.describe(self.video("untitled", board, brief=None))["ever_built"])

    def test_a_storyboard_of_the_wrong_shape_names_what_is_wrong(self):
        folder = self.video("v", {"script": "s"})              # valid JSON, but no scenes
        with self.assertRaises(ValueError) as raised:
            app_api.describe(folder)
        self.assertIn("storyboard.json", str(raised.exception))
        self.assertIn("scenes", str(raised.exception))
        (folder / "storyboard.json").write_text("[1, 2]")
        with self.assertRaises(ValueError) as raised:
            app_api.describe(folder)
        self.assertIn("storyboard.json", str(raised.exception))

    def test_a_video_without_a_storyboard_says_so(self):
        self.assertEqual(app_api.describe(self.video("v")),
                         {"title": "Nomad reel", "scenes": [], "no_storyboard": True, "plan": BRIEF,
                          "plan_is_draft": False, "plan_unopened": [], "prompt": None,
                          "material": {"footage": [], "assets": [], "music": [], "looks": [], "script": False}})

    def test_describe_gives_the_prompt_and_the_material_by_file_name(self):
        inputs = {"prompt": "A launch reel", "script": "Meet Nomad.",
                  "footage": [{"name": "talk.mp4", "source": "C:/x/talk.mp4", "duration": 20.0, "folder": "f"}],
                  "assets": [{"path": "C:/x/shot.png", "kind": "image"},
                             {"path": "C:/x/walk.mp4", "kind": "clip", "duration": 3.0, "size": "320x568"}],
                  "music": [{"path": "C:/x/song.mp3", "duration": 60.0}], "looks": [{"path": "C:/x/warm.cube"}]}
        given = {"prompt": "A launch reel", "material": {"footage": ["talk.mp4"], "assets": ["shot.png", "walk.mp4"],
                                                         "music": ["song.mp3"], "looks": ["warm.cube"], "script": True}}
        for name, board in (("planned", None), ("boarded", {"script": "s", "scenes": [TITLE]})):
            with self.subTest(name):
                described = app_api.describe(self.video(name, board, inputs))
                self.assertEqual({key: described[key] for key in given}, given)
        bare = self.video("bare")
        (bare / "inputs.json").unlink()
        described = app_api.describe(bare)
        self.assertEqual((described["prompt"], described["material"]),
                         (None, {"footage": [], "assets": [], "music": [], "looks": [], "script": False}))

    def plan(self, folder: Path) -> tuple:
        described = app_api.describe(folder)
        return described["plan"], described["plan_is_draft"]

    def test_describe_shows_the_plan_draft(self):
        drafting = self.video("drafting", brief=None)
        self.assertEqual(self.plan(drafting), (None, False))
        (drafting / "plan_draft.json").write_text(json.dumps(BRIEF), encoding="utf-8")
        self.assertEqual(self.plan(drafting), (BRIEF, True))
        changing = self.video("changing", {"script": "s", "scenes": [TITLE]})     # a plan changed after approval
        (changing / "plan_draft.json").write_text(json.dumps(dict(BRIEF, tone="calm")), encoding="utf-8")
        self.assertEqual(self.plan(changing), (dict(BRIEF, tone="calm"), True))

    def test_after_approve_the_plan_is_the_brief_and_a_change_to_it_is_a_draft(self):
        for name, board in (("only-a-brief", None), ("with-a-storyboard", {"script": "s", "scenes": [TITLE]})):
            with self.subTest(name):
                folder = self.video(name, board)
                self.assertEqual(self.plan(folder), (BRIEF, False))
                approved = (folder / "brief.json").read_bytes()
                app_think.edit_plan(folder, {"tone": "calm"})
                self.assertEqual((folder / "brief.json").read_bytes(), approved)
                self.assertEqual(self.plan(folder), (dict(BRIEF, tone="calm"), True))

    def test_a_broken_storyboard_is_an_error_not_a_traceback(self):
        folder = self.video("my video")                    # a space in the path, as in "E:\\my projects"
        (folder / "storyboard.json").write_text("{not json")
        result = subprocess.run([sys.executable, "-m", "project.app_api", "describe", str(folder)],
                                cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("storyboard.json", json.loads(result.stdout)["error"])
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_the_command_line_prints_one_json_value(self):
        self.video("v", {"script": "s", "scenes": [TITLE]})
        result = subprocess.run([sys.executable, "-m", "project.app_api", "videos", str(self.root)],
                                cwd=REPO, capture_output=True, text=True)
        self.assertEqual((result.returncode, json.loads(result.stdout)[0]["title"]), (0, "Nomad reel"))


class TestThumbnail(_Folder):
    def test_a_recording_that_has_moved_gives_none(self):
        inputs = {"footage": [{"name": "talk.mp4", "source": str(self.root / "gone.mp4"), "duration": 20.0,
                               "folder": "f"}], "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 1.0, "end": 2.0}, "reason": "r"}, TITLE]}
        folder = self.video("v", board, inputs)
        first, title = (s["key"] for s in app_api.describe(folder)["scenes"])
        self.assertIsNone(app_api.thumbnail(folder, first))
        self.assertIsNone(app_api.thumbnail(folder, title))       # a title has no picture of its own
        self.assertIsNone(app_api.thumbnail(folder, "000000000000-0"))      # no scene has that key

    def test_a_clip_gives_a_small_jpeg_kept_for_next_time(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg not found")
        clip = self.root / "talk.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30", "-t", "2",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        inputs = {"footage": [{"name": "talk.mp4", "source": str(clip), "duration": 2.0, "folder": "f"}],
                  "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 0.5, "end": 1.5}, "reason": "r"}]}
        board["scenes"].insert(0, TITLE)
        folder = self.video("v", board, inputs)
        key = app_api.describe(folder)["scenes"][1]["key"]
        picture = app_api.thumbnail(folder, key)
        self.assertEqual(picture.read_bytes()[:2], b"\xff\xd8")                  # a JPEG
        self.assertEqual(picture.parent, folder / "app_cache" / "thumbs")
        made = picture.stat().st_mtime_ns
        storyboard_edit.apply(folder, {"op": "move", "from": 2, "to": 1})        # the scene moves; its key does not
        self.assertEqual(app_api.describe(folder)["scenes"][0]["key"], key)
        self.assertEqual(app_api.thumbnail(folder, key), picture)
        self.assertEqual(picture.stat().st_mtime_ns, made)                       # not made again


class TestCoveredScene(_Folder):
    def test_a_recording_covered_with_a_picture_shows_the_picture(self):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg not found")
        clip, cover = self.root / "talk.mp4", self.root / "cover.png"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30", "-t", "2",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=320x568", "-frames:v", "1",
                        str(cover)], check=True)
        inputs = {"footage": [{"name": "talk.mp4", "source": str(clip), "duration": 2.0, "folder": "f"}],
                  "assets": [], "music": []}
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 0.5, "end": 1.5}, "reason": "r"}]}
        folder = self.video("v", board, inputs)
        bare = app_api.describe(folder)["scenes"][0]["key"]
        storyboard_edit.apply(folder, {"op": "picture", "number": 1, "path": str(cover)}, chosen=[str(cover)])
        scene = app_api.describe(folder)["scenes"][0]
        self.assertEqual(scene["source"], "cover.png over your recording 0:00–0:01")
        self.assertNotEqual(scene["key"], bare)                       # so the app fetches the new picture
        pixel = subprocess.run([ffmpeg, "-v", "error", "-i", str(app_api.thumbnail(folder, scene["key"])),
                                "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               capture_output=True, check=True).stdout
        self.assertGreater(pixel[0], 200)                              # the cover's red, not the recording
        self.assertLess(pixel[1], 80)

    def test_b_roll_that_pops_up_on_words_does_not_cover_the_scene(self):
        board = {"script": "s", "scenes": [
            {"visual": {"type": "footage", "source": "talk.mp4", "start": 0.5, "end": 1.5}, "reason": "r",
             "broll": [{"path": "cover.png", "when": "hello", "duration": 1.0}]}]}
        folder = self.video("v", board)
        self.assertEqual(app_api.describe(folder)["scenes"][0]["source"], "Your recording 0:00–0:01")


class TestOpen(_Folder):
    def opened(self, folder: Path, shown: bool) -> tuple[mock.Mock, str]:
        """Open the video with the editor's `open` faked to answer `shown`: the fake, and what was printed."""
        printed = io.StringIO()
        with mock.patch.object(editors.Editor, "open", autospec=True, return_value=shown) as open_, \
                contextlib.redirect_stdout(printed):
            app_api.open_project(folder)
        return open_, printed.getvalue()

    def test_open_asks_the_editor_to_open_the_built_project(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE]})
        project = produce.project_path(folder, BRIEF)
        project.write_text("{}")
        open_, printed = self.opened(folder, True)
        open_.assert_called_once_with(editors.EDITORS[editors.DEFAULT], project)
        self.assertEqual(printed, "==> Opening it in OpenShot\n")

    def test_open_before_any_build_says_to_build_first(self):
        folder = self.video("my video", {"script": "s", "scenes": [TITLE]})
        with self.assertRaises(SystemExit) as raised:
            self.opened(folder, True)
        self.assertEqual(raised.exception.code, "Build the video first: there is no OpenShot project yet.")
        # The app runs the command line, and shows what it says on stderr.
        result = subprocess.run([sys.executable, "-m", "project.app_api", "open", str(folder)],
                                cwd=REPO, capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr.strip()),
                         (1, "==> Opening it in OpenShot\n", raised.exception.code))

    def test_open_when_openshot_is_missing_says_so(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE]})
        project = produce.project_path(folder, BRIEF)
        project.write_text("{}")
        with self.assertRaises(SystemExit) as raised:
            self.opened(folder, False)
        self.assertEqual(raised.exception.code, f"OpenShot was not found. Open {project} yourself.")


class TestServe(_Folder):
    """The engine kept running for the app: one JSON line in, one JSON line out."""

    def setUp(self):
        super().setUp()
        self.server = subprocess.Popen([sys.executable, "-m", "project.app_api", "serve"], cwd=REPO,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8")
        self.addCleanup(self.stop)

    def stop(self):
        if self.server.poll() is None:
            self.server.kill()
        self.server.wait(10)
        for stream in (self.server.stdin, self.server.stdout, self.server.stderr):
            stream.close()

    def ask(self, *requests: dict) -> dict:
        for request in requests:
            self.server.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")      # raw UTF-8, as the app sends
        self.server.stdin.flush()
        answers = [json.loads(self.server.stdout.readline()) for _ in requests]
        return {a["id"]: a for a in answers}

    def test_each_request_is_answered_by_its_id(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE]})
        answers = self.ask({"id": 1, "method": "describe", "params": {"folder": str(folder)}},
                           {"id": 2, "method": "videos", "params": {"root": str(self.root)}},
                           {"id": 3, "method": "shuffle", "params": {}})
        self.assertEqual(answers[1]["result"]["title"], "Nomad reel")
        self.assertEqual(answers[2]["result"][0]["folder"], str(folder))
        self.assertIn("shuffle", answers[3]["error"])
        self.assertIsNone(self.server.poll())                       # still running

    def test_an_edit_answers_with_the_new_storyboard(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE, dict(TITLE, visual={"type": "title", "text": "Two"})]})
        version = storyboard_edit.version(folder)
        answer = self.ask({"id": 7, "method": "edit", "params": {"folder": str(folder), "version": version,
                                                                "op": {"op": "move", "from": 2, "to": 1},
                                                                "chosen": []}})[7]["result"]
        self.assertEqual([s["text"] for s in answer["described"]["scenes"]], ["Two", "Hook"])
        self.assertEqual(answer["notes"], [])
        self.assertTrue(answer["described"]["can_undo"])
        undone = self.ask({"id": 8, "method": "undo",
                           "params": {"folder": str(folder), "version": answer["described"]["version"]}})[8]
        self.assertEqual([s["text"] for s in undone["result"]["described"]["scenes"]], ["Hook", "Two"])

    def test_a_refused_edit_says_why_and_the_server_carries_on(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE]})
        answers = self.ask({"id": 1, "method": "edit", "params": {"folder": str(folder), "chosen": [],
                                                                 "version": storyboard_edit.version(folder),
                                                                 "op": {"op": "delete", "number": 1}}},
                           {"id": 2, "method": "edit", "params": {"folder": str(folder), "chosen": [],
                                                                 "version": "0000000000000000",
                                                                 "op": {"op": "delete", "number": 1}}})
        self.assertEqual(answers[1]["result"], {"refused": "A video needs at least one scene.", "changed": False})
        self.assertTrue(answers[2]["result"]["changed"])

    def test_a_failing_request_does_not_stop_the_server(self):
        broken = self.video("broken")
        (broken / "storyboard.json").write_text("{not json")
        answers = self.ask({"id": 1, "method": "describe", "params": {"folder": str(broken)}},
                           {"id": 2, "method": "videos", "params": {"root": str(self.root)}})
        self.assertIn("storyboard.json", answers[1]["error"])
        self.assertEqual(len(answers[2]["result"]), 1)

    def test_words_beyond_english_letters_arrive_as_they_were_typed(self):
        folder = self.video("v", {"script": "s", "scenes": [TITLE], "sections": [{"title": "A", "from": 1}]})
        answer = self.ask({"id": 1, "method": "edit", "params": {
            "folder": str(folder), "version": storyboard_edit.version(folder), "chosen": [],
            "op": {"op": "rename_chapter", "number": 1, "title": "Tür · नमस्ते"}}})[1]["result"]
        self.assertEqual(answer["described"]["sections"][0]["title"], "Tür · नमस्ते")

    def test_serve_answers_thinkers_and_edit_plan(self):
        # Answered here, not by the running server: finding the agents would run the ones on this PC.
        folder, out = self.video("v"), io.StringIO()
        agents = [{"id": "claude", "name": "Claude Code", "found": True, "version": "2.0"}]
        requests = [{"id": 1, "method": "thinkers"},
                    {"id": 2, "method": "edit_plan", "params": {"folder": str(folder), "fields": {"tone": "calm"}}},
                    {"id": 3, "method": "edit_plan", "params": {"folder": str(folder), "fields": {"aspect": "2:1"}}},
                    {"id": 4, "method": "new_video", "params": {"root": str(self.root), "prompt": "A launch reel"}}]
        with mock.patch.object(app_api.thinkers, "found_agents", return_value=agents), \
                contextlib.redirect_stderr(io.StringIO()):
            app_api.serve([json.dumps(r) for r in requests], out)
        answers = {a["id"]: a for a in map(json.loads, out.getvalue().splitlines())}
        self.assertEqual(answers[1]["result"], agents)
        self.assertEqual(answers[2]["result"]["plan"], dict(BRIEF, tone="calm"))
        self.assertTrue(answers[2]["result"]["plan_is_draft"])
        self.assertTrue(answers[3]["error"].startswith("That change was not made: "))
        self.assertEqual(answers[4]["result"], str(self.root / "a-launch-reel"))
        self.assertTrue((self.root / "a-launch-reel").is_dir())

    def test_the_server_ends_with_its_input(self):
        self.server.stdin.close()
        self.assertEqual(self.server.wait(5), 0)


if __name__ == "__main__":
    unittest.main()
