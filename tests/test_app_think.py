"""The plan: written by a thinker from the prompt and the material, changed, answered, and kept as a draft."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import app_api, app_think, produce, research, storyboard_edit
from project.media import _find_tool
from project.thinkers import StandInThinker, ThinkError

PROMPT = "A launch reel for the Nomad pack, 30 seconds"
DRAFT = {"title": "Nomad reel", "format": "product reel", "aspect": "9:16", "target_seconds": 30,
         "audience": "travellers", "tone": "upbeat", "summary": "A launch reel.",
         "facts": [{"claim": "It weighs 900 g", "source": "Nomad", "url": "https://example.com/pack",
                    "quote": "the pack weighs 900 grams"}],
         "open_questions": ["What does it cost?", "Where is it sold?"]}
# The pack's page as a stub reader gives it: long enough to be read without a browser.
PAGE = "Our pack is light and strong. " * 30 + "In short, the pack weighs 900 grams with everything in it."
SOLD = {"claim": "Sold in 40 shops", "source": "Nomad", "url": "https://example.org/sold",
        "quote": "sold in forty shops worldwide"}
# A folder's material as prepare left it, from files the app picked before a restart.
PREPARED = {"prompt": "An older idea", "script": "Meet Nomad.",
            "footage": [{"name": "talk.mp4", "source": "C:/x/talk.mp4", "duration": 20.0, "folder": "footage/talk"}],
            "assets": [{"path": "C:/x/shot.png", "kind": "image"}],
            "music": [{"path": "C:/x/song.mp3", "duration": 60.0}], "looks": [{"path": "C:/x/warm.cube"}]}


def _generated(folder: Path) -> tuple[Path, Path]:
    """A picture and a piece of music, made here: no recordings, so nothing is transcribed."""
    picture, music = folder / "shot.png", folder / "song.wav"
    ffmpeg = _find_tool("ffmpeg")
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:size=32x32", "-frames:v", "1",
                    str(picture)], check=True)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
                    str(music)], check=True)
    return picture, music


def _studied(clip: Path, out_dir: Path) -> dict:
    """eyes.study stood in for: a two-second clip with nothing flagged, written where prepare looks for it."""
    study = {"source": Path(clip).as_posix(), "stamp": {"path": Path(clip).as_posix(), "bytes": 0, "mtime_ns": 0},
             "duration": 2.0, "width": 1080, "height": 1920, "fps": 30.0, "cuts": [], "step": 0.5,
             "samples": [{"t": 0.0, "sharp": 100.0, "bright": 120.0, "motion": 0.0}], "speech": [],
             "speech_seconds": 0.0, "sheet": "sheet.jpg"}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "study.json").write_text(json.dumps(study), encoding="utf-8")
    return study


def _tone(path: Path, seconds: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=330:duration={seconds}", str(path)], check=True)
    return path


class _Plan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.folder = self.root / "video"
        # No test opens a page: each one cannot be read, unless a test says what is on it.
        read = mock.patch.object(research, "read", side_effect=research.ReadError("a test opens no page"))
        self.read = read.start()
        self.addCleanup(read.stop)

    def started(self, *answers, folder: Path | None = None, can_search: bool = True, **material) -> StandInThinker:
        thinker = StandInThinker(list(answers), can_search=can_search)
        app_think.start(folder or self.folder, PROMPT, thinker, **material)
        return thinker

    def draft(self) -> dict:
        return json.loads((self.folder / app_think.PLAN_DRAFT).read_text(encoding="utf-8"))


KEY = "sk-test-0123456789abcdef"


def _main(root: Path, *argv, answers=(), **env) -> tuple[int, str, str]:
    """The command line run here with the stand-in thinker: its exit code, and what it printed and said."""
    scripted = root / "answers.json"
    scripted.write_text(json.dumps(list(answers)), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = app_think.main([str(a) for a in argv], {"FRAMEFLOW_THINKER": f"standin:{scripted}", **env})
    return code, out.getvalue(), err.getvalue()


class TestTheCommandLine(_Plan):
    def test_start_prints_its_steps(self):
        code, out, err = _main(self.root, "start", self.folder, "--prompt", PROMPT, "--shape", "9:16",
                               answers=[DRAFT])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), ["==> Preparing the material",
                                            "==> Writing the plan with Stand-in thinker",
                                            "==> Checking the facts on their pages",
                                            "    Nomad reel, with 2 open questions"])
        self.assertEqual(self.draft(), DRAFT)

    def test_a_change_and_an_answer_write_the_plan_again(self):
        self.started(DRAFT)
        calmer, answered = dict(DRAFT, tone="calm"), dict(DRAFT, tone="calm", open_questions=["Where is it sold?"])
        code, out, _ = _main(self.root, "plan-change", self.folder, "--words", "Make it calmer", answers=[calmer])
        self.assertEqual((code, out.splitlines()), (0, ["==> Writing the plan with Stand-in thinker",
                                                        "==> Checking the facts on their pages",
                                                        "    Nomad reel, with 2 open questions"]))
        self.assertEqual(self.draft(), calmer)
        code, out, _ = _main(self.root, "answer", self.folder, "--question", "1", "--words", "$120",
                             answers=[answered])
        self.assertEqual((code, out.splitlines()), (0, ["==> Writing the plan with Stand-in thinker",
                                                        "==> Checking the facts on their pages",
                                                        "    Nomad reel, with 1 open question"]))
        self.assertEqual(self.draft(), answered)

    def test_each_check_of_the_facts_is_a_step_and_a_plan_without_facts_has_none(self):
        self.read.side_effect = lambda url: PAGE
        misquoted = dict(DRAFT, facts=[dict(DRAFT["facts"][0], quote="the pack weighs 800 grams")])
        code, out, _ = _main(self.root, "start", self.folder, "--prompt", PROMPT, answers=[misquoted, DRAFT])
        self.assertEqual((code, out.splitlines()), (0, [      # a fix round is written and checked again
            "==> Preparing the material", "==> Writing the plan with Stand-in thinker",
            "==> Checking the facts on their pages", "==> Writing the plan with Stand-in thinker",
            "==> Checking the facts on their pages", "    Nomad reel, with 2 open questions"]))
        code, out, _ = _main(self.root, "plan-change", self.folder, "--words", "No facts",
                             answers=[dict(DRAFT, facts=[])])
        self.assertEqual((code, out.splitlines()), (0, ["==> Writing the plan with Stand-in thinker",
                                                        "    Nomad reel, with 2 open questions"]))

    def test_a_plan_change_or_answer_refused_over_a_missing_file_shows_no_thinking_step(self):
        # The files are checked first, so a refused job does not look as if the thinker ran.
        picture, _ = _generated(self.root)
        self.started(DRAFT, assets=[picture])
        picture.unlink()
        for argv in (("plan-change", self.folder, "--words", "Make it calmer"),
                     ("answer", self.folder, "--question", "1", "--words", "$120")):
            with self.subTest(argv[0]):
                self.assertEqual(_main(self.root, *argv, answers=[DRAFT]),
                                 (1, "", app_think.MISSING.format(name=picture.name) + "\n"))

    def test_test_makes_one_small_answer(self):
        self.assertEqual(_main(self.root, "test", answers=[{"ready": True}]), (0, "Ready: Stand-in thinker\n", ""))

    def test_a_failure_is_one_redacted_line_on_stderr(self):
        # The folder's name stands for a key that an error echoes.
        code, out, err = _main(self.root, "plan-change", self.root / KEY, "--words", "Make it calmer",
                               FRAMEFLOW_KEY=KEY)
        self.assertEqual((code, out), (1, ""))      # refused before any thinking
        self.assertEqual(err, f"no brief.json in {self.root / '…'}; write it first\n")
        # Whatever is raised, an SDK's own error too, is one line and no traceback.
        with mock.patch.object(app_think, "start", side_effect=RuntimeError(f"401 for {KEY}\n  at sdk")):
            code, out, err = _main(self.root, "start", self.folder, "--prompt", PROMPT, FRAMEFLOW_KEY=KEY)
        self.assertEqual((code, err), (1, "401 for … at sdk\n"))
        code, _, err = _main(self.root, "test")
        self.assertEqual((code, err), (1, "The stand-in thinker has no answers left.\n"))


    def test_a_failure_with_half_a_character_in_it_is_still_one_redacted_line(self):
        # As the app runs it. A Windows file name can hold a lone surrogate, which strict UTF-8 cannot print.
        answers = self.root / "answers.json"
        answers.write_text("[]", encoding="utf-8")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "FRAMEFLOW_THINKER": f"standin:{answers}",
               "FRAMEFLOW_KEY": KEY}
        done = subprocess.run([sys.executable, "-m", "project.app_think", "plan-change",
                               str(self.root / f"half\udc80{KEY}"), "--words=Make it calmer"],
                              cwd=Path(__file__).resolve().parent.parent, env=env, capture_output=True)
        err = done.stderr.decode("utf-8")
        self.assertEqual(done.returncode, 1, err)
        self.assertEqual(len(err.splitlines()), 1, err)
        self.assertIn("no brief.json in ", err)
        self.assertNotIn("Traceback", err)
        self.assertNotIn(KEY, err)


class TestNewFolder(_Plan):
    def test_a_new_folder_is_named_from_the_prompt_and_never_reused(self):
        first = app_think.new_folder(self.root, PROMPT)
        second = app_think.new_folder(self.root, PROMPT)
        self.assertEqual((first.name, second.name), ("a-launch-reel-for-the", "a-launch-reel-for-the-2"))
        self.assertTrue(first.is_dir() and second.is_dir())
        self.assertEqual(app_think.new_folder(self.root, "नमस्ते दुनिया").name, "नमस्ते-दुनिया")
        self.assertEqual(app_think.new_folder(self.root, "?!").name, "video")

    def test_a_windows_device_name_gets_a_folder_that_is_really_made(self):
        # Windows makes no folder called "nul" (mkdir succeeds into the null device), and "con" or "com1"
        # are hard to open or delete there.
        for prompt, name in [("nul", "nul-video"), ("CON", "con-video"), ("com1", "com1-video"),
                             ("lpt9", "lpt9-video"), ("aux", "aux-video"), ("console", "console")]:
            folder = app_think.new_folder(self.root, prompt)
            self.assertEqual(folder.name, name)
            self.assertTrue(folder.is_dir())

    def test_a_file_as_the_root_is_refused_at_once(self):
        root = self.root / "videos"
        root.write_text("not a folder", encoding="utf-8")
        with self.assertRaises(OSError):
            app_think.new_folder(root, PROMPT)
        self.assertEqual([p.name for p in self.root.iterdir()], ["videos"])     # no folder made


class TestWritingThePlan(_Plan):
    def test_start_prepares_the_material_and_writes_a_draft(self):
        picture, music = _generated(self.root)
        thinker = StandInThinker([DRAFT])
        self.assertEqual(app_think.start(self.folder, PROMPT, thinker, assets=[picture], music=[music]), DRAFT)
        self.assertEqual(self.draft(), DRAFT)
        self.assertFalse((self.folder / produce.BRIEF_FILE).exists())
        inputs = json.loads((self.folder / produce.INPUTS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(inputs["prompt"], PROMPT)
        self.assertEqual([a["path"] for a in inputs["assets"]], [picture.resolve().as_posix()])
        self.assertEqual([m["path"] for m in inputs["music"]], [music.resolve().as_posix()])

    def inputs(self, folder: Path | None = None) -> dict:
        return json.loads(((folder or self.folder) / produce.INPUTS_FILE).read_text(encoding="utf-8"))

    def test_a_start_with_no_files_keeps_the_material_prepared_before(self):
        # After a restart the app cannot send the files picked before it: they stay, with the new prompt.
        self.folder.mkdir()
        prepared = json.loads(json.dumps(PREPARED).replace("C:/x", self.root.as_posix()))   # its files still there
        for name in ("talk.mp4", "shot.png", "song.mp3", "warm.cube"):
            (self.root / name).write_bytes(b"")
        (self.folder / produce.INPUTS_FILE).write_text(json.dumps(prepared), encoding="utf-8")
        with mock.patch.object(produce, "prepare") as prepare:
            thinker = self.started(DRAFT)
        prepare.assert_not_called()
        self.assertEqual(self.inputs(), dict(prepared, prompt=PROMPT))
        self.assertIn("recording `talk.mp4`", thinker.asked[0][1])

    def test_a_start_with_files_or_on_no_material_prepares_as_before(self):
        picture, _ = _generated(self.root)
        self.folder.mkdir()
        (self.folder / produce.INPUTS_FILE).write_text(json.dumps(PREPARED), encoding="utf-8")
        self.started(DRAFT, assets=[picture])
        inputs = self.inputs()
        self.assertEqual((inputs["prompt"], inputs["script"], inputs["footage"], inputs["music"], inputs["looks"]),
                         (PROMPT, None, [], [], []))
        self.assertEqual([a["path"] for a in inputs["assets"]], [picture.resolve().as_posix()])
        bare = self.root / "bare"
        bare.mkdir()
        (bare / produce.INPUTS_FILE).write_text(json.dumps(dict(PREPARED, script=None, footage=[], assets=[],
                                                                music=[], looks=[])), encoding="utf-8")
        with mock.patch.object(produce, "prepare", wraps=produce.prepare) as prepare:
            self.started(DRAFT, folder=bare)
        prepare.assert_called_once()
        self.assertEqual(self.inputs(bare)["prompt"], PROMPT)

    def test_a_start_given_a_file_that_is_not_there_says_so_in_words(self):
        with mock.patch.object(produce, "prepare") as prepare, self.assertRaises(ThinkError) as raised:
            self.started(footage=[Path("gone.mp4")])
        self.assertEqual(str(raised.exception), app_think.MISSING.format(name="gone.mp4"))
        prepare.assert_not_called()

    @contextlib.contextmanager
    def preparing(self):
        """produce.prepare counted, with a recording's transcription and the music's length stood in for: no
        test transcribes."""
        with (mock.patch.object(produce.first_cut, "prepare",
                                side_effect=lambda video, out, language: {"source": video.as_posix()}),
              mock.patch.object(produce.eyes, "study", side_effect=_studied),
              mock.patch.object(produce, "analyze", return_value=mock.Mock(duration_seconds=2.0)),
              mock.patch.object(produce, "probe", return_value={"format": {"duration": "60"}}),
              mock.patch.object(produce, "prepare", wraps=produce.prepare) as prepare):
            yield prepare

    def material(self) -> dict:
        talk, picture, script = self.root / "talk.mp4", self.root / "shot.png", self.root / "script.txt"
        talk.write_bytes(b"a recording")
        picture.write_bytes(b"a picture")
        script.write_text("Meet Nomad.", encoding="utf-8")
        return {"footage": [talk], "assets": [picture], "script": script}

    def test_try_again_with_the_same_files_keeps_the_material_prepared(self):
        # Try again repeats the request: its recording is not transcribed a second time.
        material = self.material()
        with self.preparing() as prepare:
            self.started(DRAFT, **material)
            thinker = StandInThinker([DRAFT])
            app_think.start(self.folder, "The same idea, again", thinker, **material)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(self.inputs()["prompt"], "The same idea, again")
        self.assertIn("recording `talk.mp4`", thinker.asked[0][1])

    def test_a_changed_or_added_file_or_no_material_prepares_again(self):
        material = self.material()
        talk, song = material["footage"][0], self.root / "song.mp3"
        song.write_bytes(b"a song")
        with self.preparing() as prepare:
            self.started(DRAFT, **material)                 # no inputs.json yet
            talk.write_bytes(b"a recording, cut")           # the same path, another file
            self.started(DRAFT, **material)
            os.utime(talk, ns=(0, 0))                       # the same size, but changed since
            self.started(DRAFT, **material)
            material["script"].write_text("Meet Nomad, the light one.", encoding="utf-8")
            self.started(DRAFT, **material)
            self.started(DRAFT, **material, music=[song])   # one more file
            inputs = self.inputs()
            for footage in inputs["footage"]:               # as an inputs.json written before sizes were kept
                del footage["stamp"]
            (self.folder / produce.INPUTS_FILE).write_text(json.dumps(inputs), encoding="utf-8")
            self.started(DRAFT, **material, music=[song])
        self.assertEqual(prepare.call_count, 6)

    def test_the_plan_request_is_the_brief_request(self):
        system, request = self.started(DRAFT).asked[0]
        self.assertEqual(request, (self.folder / produce.BRIEF_REQUEST).read_text(encoding="utf-8"))
        self.assertIn(PROMPT, request)
        self.assertIn("Write no file and run nothing", system)
        self.assertIn("```json", system)

    def test_every_plan_request_ends_by_skipping_the_chat_steps(self):
        last = ("Skip the steps above that write a file, run a command or wait for the creator, "
                "and answer with the plan.\n")
        thinker = StandInThinker([DRAFT, DRAFT, dict(DRAFT, open_questions=["Where is it sold?"])])
        app_think.start(self.folder, PROMPT, thinker)
        app_think.change_plan(self.folder, "Make it calmer", thinker)
        app_think.answer_question(self.folder, 1, "$90", thinker)
        for _, request in thinker.asked:
            self.assertTrue(request.endswith(last), request[-300:])
        self.assertNotIn(last, produce.brief_request(self.folder, json.loads(
            (self.folder / produce.INPUTS_FILE).read_text(encoding="utf-8"))))      # the chat's request keeps them

    def test_a_key_that_cannot_search_is_told_to_ask_for_facts(self):
        line = "No web search here: put each needed fact in `open_questions`"
        cannot = self.started(DRAFT, can_search=False).asked[0][1]
        can = self.started(DRAFT, folder=self.root / "other").asked[0][1]
        self.assertIn(line, cannot)
        self.assertNotIn(line, can)

    def test_a_shape_the_creator_chose_is_kept(self):
        thinker = self.started(DRAFT, dict(DRAFT, aspect="16:9"), shape="16:9")
        self.assertIn("The creator chose 16:9", thinker.asked[0][1])
        self.assertIn("aspect: the creator chose 16:9", thinker.asked[1][1])     # another shape costs a fix round
        self.assertEqual(self.draft()["aspect"], "16:9")

    def test_a_draft_failing_the_schema_costs_a_fix_round(self):
        no_summary = {k: v for k, v in DRAFT.items() if k != "summary"}
        short_quote = dict(DRAFT, facts=[dict(DRAFT["facts"][0], quote="900 grams")])
        thinker = self.started(no_summary, short_quote, DRAFT)
        self.assertEqual(len(thinker.asked), 3)
        self.assertIn("'summary' is a required property", thinker.asked[1][1])
        self.assertIn("at least 4 words", thinker.asked[2][1])      # check_brief's rule, without opening the page
        self.assertEqual(self.draft(), DRAFT)

    def test_every_answer_that_writes_the_plan_may_search_the_web(self):
        thinker = StandInThinker([DRAFT, DRAFT, dict(DRAFT, open_questions=["Where is it sold?"])])
        with mock.patch.object(thinker, "answer", wraps=thinker.answer) as answer:
            app_think.start(self.folder, PROMPT, thinker)
            app_think.change_plan(self.folder, "Make it calmer", thinker)
            app_think.answer_question(self.folder, 1, "$90", thinker)
        self.assertEqual([call.kwargs["search"] for call in answer.call_args_list], [True, True, True])


def _unopened(folder: Path) -> list[int]:
    return app_api.describe(folder)["plan_unopened"]


class TestCheckingTheFacts(_Plan):
    def test_a_misquote_costs_a_fix_round_and_each_page_is_read_once(self):
        self.read.side_effect = lambda url: PAGE
        misquoted = dict(DRAFT, facts=[dict(DRAFT["facts"][0], quote="the pack weighs 800 grams")])
        for write in (lambda thinker: app_think.start(self.folder, PROMPT, thinker),
                      lambda thinker: app_think.change_plan(self.folder, "Make it calmer", thinker),
                      lambda thinker: app_think.answer_question(self.folder, 1, "$90", thinker)):
            self.read.reset_mock()
            thinker = StandInThinker([misquoted, DRAFT])
            write(thinker)
            self.assertEqual(len(thinker.asked), 2)
            self.assertIn("fact 1 (It weighs 900 g): the quote is not on https://example.com/pack",
                          thinker.asked[1][1])
            self.assertEqual(self.read.call_count, 1)       # the fix round's check reads the page it already has
            self.assertEqual(self.draft(), DRAFT)
            self.assertEqual(_unopened(self.folder), [])

    def test_a_page_that_cannot_be_read_is_marked_and_not_sent_back(self):
        def read(url: str) -> str:
            if url == SOLD["url"]:
                raise research.ReadError("the site answered 403")
            return PAGE

        self.read.side_effect = read
        thinker = self.started(dict(DRAFT, facts=[DRAFT["facts"][0], SOLD]))
        self.assertEqual(len(thinker.asked), 1)
        self.assertEqual(_unopened(self.folder), [2])
        # A hand edit: the numbers follow a dropped fact, and a fact given another page is no longer marked.
        app_think.edit_plan(self.folder, {"drop_fact": 1})
        self.assertEqual(_unopened(self.folder), [1])
        app_think.edit_plan(self.folder, {"fact": {"number": 1, "url": "https://example.org/shops",
                                                   "quote": SOLD["quote"]}})
        self.assertEqual(_unopened(self.folder), [])


class TestChangingThePlan(_Plan):
    def test_change_plan_sends_the_words_and_the_draft(self):
        self.started(DRAFT)
        calmer = dict(DRAFT, tone="calm")
        thinker = StandInThinker([calmer])
        self.assertEqual(app_think.change_plan(self.folder, "Make it calmer", thinker), calmer)
        request = thinker.asked[0][1]
        self.assertIn("Make it calmer", request)
        self.assertIn(json.dumps(DRAFT, indent=2, ensure_ascii=False), request)
        self.assertIn(PROMPT, request)          # the brief's request, with what the creator provided
        self.assertEqual(self.draft(), calmer)

    def test_answer_question_folds_the_answer_in(self):
        self.started(DRAFT)
        answered = dict(DRAFT, summary="A launch reel. It costs $90.", open_questions=["Where is it sold?"])
        thinker = StandInThinker([answered])
        self.assertEqual(app_think.answer_question(self.folder, 1, "$90", thinker), answered)
        request = thinker.asked[0][1]
        self.assertIn("What does it cost?", request)
        self.assertIn("$90", request)
        self.assertIn(json.dumps(DRAFT, indent=2, ensure_ascii=False), request)
        self.assertEqual(self.draft(), answered)
        with self.assertRaises(produce.ProduceError):       # only one question is left
            app_think.answer_question(self.folder, 2, "Online", StandInThinker([]))

    def test_edit_plan_removes_a_question_and_fills_a_fact(self):
        self.started(DRAFT)
        source = {"number": 1, "url": "https://example.org/nomad", "quote": "it weighs just 900 grams"}
        edited = app_think.edit_plan(self.folder, {"remove_question": 1, "fact": source, "tone": "calm",
                                                   "target_seconds": 20})
        self.assertEqual(edited["open_questions"], ["Where is it sold?"])
        self.assertEqual(edited["facts"], [dict(DRAFT["facts"][0], url=source["url"], quote=source["quote"])])
        self.assertEqual((edited["tone"], edited["target_seconds"]), ("calm", 20))
        self.assertEqual(self.draft(), edited)
        self.assertEqual(app_think.edit_plan(self.folder, {"drop_fact": 1})["facts"], [])

    def test_a_bad_hand_edit_is_one_plain_line_and_changes_nothing(self):
        self.started(DRAFT)
        before = (self.folder / app_think.PLAN_DRAFT).read_bytes()
        for bad in ({"remove_question": 3}, {"drop_fact": 0}, {"aspect": "4:3"}, {"title": ""}, {"colour": "red"},
                    {"tone": "calm", "fact": {"number": 1, "url": "example.org", "quote": "the words on it"}}):
            with self.subTest(bad), self.assertRaises(produce.ProduceError) as raised:
                app_think.edit_plan(self.folder, bad)
            self.assertNotIn("\n", str(raised.exception))
        self.assertEqual((self.folder / app_think.PLAN_DRAFT).read_bytes(), before)

    def test_the_draft_is_never_written_to_brief_json(self):
        self.started(DRAFT)
        app_think.change_plan(self.folder, "Make it calmer", StandInThinker([dict(DRAFT, tone="calm")]))
        app_think.answer_question(self.folder, 1, "$90",
                                  StandInThinker([dict(DRAFT, open_questions=["Where is it sold?"])]))
        app_think.edit_plan(self.folder, {"remove_question": 1})
        self.assertFalse((self.folder / produce.BRIEF_FILE).exists())
        self.assertEqual(self.draft()["open_questions"], [])

    def test_a_change_to_an_approved_plan_starts_from_its_brief(self):
        self.started(DRAFT)
        approved = dict(DRAFT, open_questions=[])           # as Approve leaves it: brief.json and no draft
        (self.folder / produce.BRIEF_FILE).write_text(json.dumps(approved), encoding="utf-8")
        (self.folder / app_think.PLAN_DRAFT).unlink()
        before = (self.folder / produce.BRIEF_FILE).read_bytes()
        calmer = dict(approved, tone="calm")
        thinker = StandInThinker([calmer])
        app_think.change_plan(self.folder, "Make it calmer", thinker)
        self.assertIn(json.dumps(approved, indent=2, ensure_ascii=False), thinker.asked[0][1])
        self.assertEqual((self.folder / produce.BRIEF_FILE).read_bytes(), before)
        self.assertEqual(self.draft(), calmer)

    def test_the_storyboard_request_can_be_of_the_draft(self):
        self.started(dict(DRAFT, open_questions=[]))
        request = produce.storyboard_request(self.folder, self.draft()).read_text(encoding="utf-8")
        self.assertIn('"title": "Nomad reel"', request)
        self.assertFalse((self.folder / produce.BRIEF_FILE).exists())


PLAN = {k: v for k, v in DRAFT.items() if k not in ("facts", "open_questions")}
TITLE = {"visual": {"type": "title", "text": "Hook"}, "duration": 2.0, "reason": "r"}
BOARD = {"script": "s", "scenes": [TITLE]}


class TestTheStoryboard(_Plan):
    def setUp(self):
        super().setUp()
        # Every narration line is read as one second of tone, as the produce tests do.
        speak = mock.patch.object(produce.voiceover, "speak", lambda text, out, voice=None: _tone(out, 1.0))
        speak.start()
        self.addCleanup(speak.stop)

    def stored(self, name: str) -> dict:
        return json.loads((self.folder / name).read_text(encoding="utf-8"))

    def test_approve_writes_the_brief_and_the_storyboard(self):
        self.started(PLAN)
        thinker = StandInThinker([BOARD])
        with mock.patch.object(thinker, "answer", wraps=thinker.answer) as answer:
            self.assertEqual(app_think.approve(self.folder, thinker), self.folder / produce.STORYBOARD_FILE)
        self.assertFalse(answer.call_args.kwargs["search"])         # a storyboard looks nothing up
        self.assertEqual(self.stored(produce.BRIEF_FILE), PLAN)
        self.assertEqual(self.stored(produce.STORYBOARD_FILE), BOARD)
        self.assertFalse((self.folder / app_think.PLAN_DRAFT).exists())
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))      # a new video: nothing to undo
        system, request = thinker.asked[0]
        self.assertEqual(system, app_think.SYSTEM)
        self.assertIn('"title": "Nomad reel"', request)
        self.assertTrue(request.endswith("Skip the steps above that write a file, run a command or wait for the "
                                         "creator, and answer with the storyboard and any composition files.\n"),
                        request[-300:])
        self.assertEqual(request, (self.folder / produce.STORYBOARD_REQUEST).read_text(encoding="utf-8"))

    def test_each_step_tells_the_thinker_the_videos_material(self):
        # An agent may read the folders of these files, and nothing else outside the repository.
        picture, music = _generated(self.root)
        thinker = StandInThinker([PLAN, BOARD, {"ops": [{"op": "title", "number": 1, "text": "Hook!"}],
                                                "summary": "A new title"}])
        app_think.start(self.folder, PROMPT, thinker, assets=[picture], music=[music])
        app_think.approve(self.folder, thinker)
        app_think.change_in_words(self.folder, "Say Hook!", storyboard_edit.version(self.folder), thinker)
        material = app_think._material(self.stored(produce.INPUTS_FILE))
        self.assertEqual(material, [picture.resolve(), music.resolve()])
        self.assertEqual(thinker.material, [material] * 3)      # the plan, the storyboard and the change

    def test_approve_prints_its_steps_and_where_the_storyboard_is(self):
        self.started(PLAN)
        code, out, err = _main(self.root, "approve", self.folder, answers=[dict(BOARD, files=[{"path": "run.exe", "text": ""}]), BOARD])
        self.assertEqual((code, err), (0, ""))
        # A fix round is written and checked again; the last line is what the app reads.
        self.assertEqual(out.splitlines(), [
            "==> Checking the facts", "==> Writing the storyboard",
            "==> Checking the storyboard", "==> Writing the storyboard", "==> Checking the storyboard",
            "==> Done " + json.dumps({"storyboard": str(self.folder / produce.STORYBOARD_FILE)})])
        self.assertEqual(self.stored(produce.STORYBOARD_FILE), BOARD)

    def test_approve_refused_is_one_line(self):
        self.started(DRAFT)
        code, out, err = _main(self.root, "approve", self.folder)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "The plan still has open questions. Answer or remove each one first: "
                              "- What does it cost? - Where is it sold?\n")

    def test_approve_with_no_draft_has_nothing_to_approve(self):
        self.started(PLAN)
        app_think.approve(self.folder, StandInThinker([BOARD]))
        before = {p.name: p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        thinker = StandInThinker([BOARD])
        with self.assertRaises(produce.ProduceError) as raised:
            app_think.approve(self.folder, thinker)
        self.assertEqual(str(raised.exception), "Nothing to approve: the plan has not changed since it was approved.")
        self.assertEqual(thinker.asked, [])
        self.assertEqual({p.name: p.read_bytes() for p in self.folder.iterdir() if p.is_file()}, before)

    def test_an_approved_brief_with_no_storyboard_yet_is_approved_as_it_is(self):
        # As a chat leaves a video after its brief, or an approved plan whose storyboard was never written.
        self.started(PLAN)
        (self.folder / app_think.PLAN_DRAFT).replace(self.folder / produce.BRIEF_FILE)
        self.assertEqual(app_think.approve(self.folder, StandInThinker([BOARD])), self.folder / produce.STORYBOARD_FILE)
        self.assertEqual(self.stored(produce.BRIEF_FILE), PLAN)
        self.assertEqual(self.stored(produce.STORYBOARD_FILE), BOARD)
        self.assertFalse((self.folder / app_think.PLAN_DRAFT).exists())
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))      # a first storyboard

    def test_approving_a_changed_plan_is_one_undo(self):
        self.started(PLAN)
        app_think.approve(self.folder, StandInThinker([BOARD]))
        old = [(self.folder / name).read_bytes() for name in (produce.BRIEF_FILE, produce.STORYBOARD_FILE)]
        app_think.edit_plan(self.folder, {"tone": "calm"})
        app_think.approve(self.folder, StandInThinker([dict(BOARD, script="calmer")]))
        self.assertEqual(self.stored(produce.BRIEF_FILE)["tone"], "calm")
        self.assertEqual(self.stored(produce.STORYBOARD_FILE)["script"], "calmer")
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual([(self.folder / name).read_bytes()
                          for name in (produce.BRIEF_FILE, produce.STORYBOARD_FILE)], old)

    def test_approve_is_refused_while_questions_remain(self):
        self.started(dict(PLAN, open_questions=["What does it cost?"]))
        thinker = StandInThinker([BOARD])
        with self.assertRaises(produce.ProduceError) as raised:
            app_think.approve(self.folder, thinker)
        self.assertIn("What does it cost?", str(raised.exception))
        app_think.edit_plan(self.folder, {"remove_question": 1, "facts": DRAFT["facts"]})
        with mock.patch.object(app_think.research, "read", side_effect=app_think.research.Gone("no page")), \
                self.assertRaises(produce.ProduceError) as raised:
            app_think.approve(self.folder, thinker)                 # a fact whose page is not there
        self.assertIn("fact 1 (It weighs 900 g): no page", str(raised.exception))
        self.assertEqual(thinker.asked, [])
        self.assertTrue((self.folder / app_think.PLAN_DRAFT).is_file())
        for name in (produce.BRIEF_FILE, produce.STORYBOARD_FILE):
            self.assertFalse((self.folder / name).exists())

    def test_approve_reads_a_page_two_facts_share_once(self):
        self.read.side_effect = lambda url: PAGE
        light = {"claim": "It is light", "source": "Nomad", "url": DRAFT["facts"][0]["url"],
                 "quote": "our pack is light and strong"}
        self.started(dict(PLAN, facts=[DRAFT["facts"][0], light]))
        self.read.reset_mock()
        app_think.approve(self.folder, StandInThinker([BOARD]))
        self.assertEqual(self.read.call_count, 1)

    def test_approve_marks_the_pages_it_could_not_open(self):
        self.read.side_effect = lambda url: PAGE
        self.started(dict(PLAN, facts=DRAFT["facts"]))
        self.assertEqual(_unopened(self.folder), [])
        self.read.side_effect = research.ReadError("it could not be reached")
        app_think.approve(self.folder, StandInThinker([BOARD]))
        described = app_api.describe(self.folder)
        self.assertEqual((described["plan_is_draft"], described["plan_unopened"]), (False, [1]))

    def test_a_storyboard_that_would_not_build_costs_a_fix_round(self):
        self.started(dict(PLAN, aspect="16:9", fps=30))
        (self.folder / "f").mkdir()         # a recording, as prepare leaves one; its file is never opened
        (self.folder / "f" / "transcript.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
        (self.folder / "f" / "timing.json").write_text(json.dumps({"words": [], "pauses": []}), encoding="utf-8")
        (self.folder / "f" / "talk.mp4").write_bytes(b"")
        inputs = self.stored(produce.INPUTS_FILE)
        inputs["footage"] = [{"name": "talk.mp4", "source": (self.folder / "f" / "talk.mp4").as_posix(),
                              "duration": 20.0, "folder": "f"}]
        (self.folder / produce.INPUTS_FILE).write_text(json.dumps(inputs), encoding="utf-8")
        span = {"visual": {"type": "footage", "source": "talk.mp4", "start": 2.0, "end": 2.5}, "reason": "r"}
        too_long = {"script": "s", "scenes": [dict(span, narration="Far too long to say in half a second")]}
        thinker = StandInThinker([too_long, BOARD])
        app_think.approve(self.folder, thinker)
        self.assertEqual(len(thinker.asked), 2)
        self.assertIn("scene 1: the narration needs 1.5s but the footage span is 0.5s", thinker.asked[1][1])
        self.assertEqual(self.stored(produce.STORYBOARD_FILE), BOARD)

    def test_composition_files_are_written_inside_the_video(self):
        self.started(PLAN)
        files = [{"path": "intro/index.html", "text": "<div>caf\u00e9</div>\n"},
                 {"path": "intro/css/style.css", "text": "div { color: red }\r\n"},
                 {"path": "board/index.html", "text": "<div></div>"},
                 {"path": "inputs.json", "text": "{}"}]         # lands in the set's folder, not on the video's own
        answer = {"script": "s", "overlay": {"path": "board"}, "files": files, "scenes": [
            {"visual": {"type": "composition", "path": "intro"}, "duration": 2.0, "reason": "r"}]}
        inputs = (self.folder / produce.INPUTS_FILE).read_bytes()
        app_think.approve(self.folder, StandInThinker([answer]))
        (inside,) = (self.folder.resolve() / "compositions").iterdir()     # this answer's own folder
        self.assertRegex(inside.name, "^[0-9a-f]{8}$")
        for file in files:      # byte for byte
            self.assertEqual((inside / file["path"]).read_bytes(), file["text"].encode("utf-8"))
        self.assertEqual((self.folder / produce.INPUTS_FILE).read_bytes(), inputs)
        board = self.stored(produce.STORYBOARD_FILE)
        self.assertNotIn("files", board)
        # Where the engine reads them from wherever it runs, as existing storyboards hold them.
        self.assertEqual(board["scenes"][0]["visual"]["path"], (inside / "intro").as_posix())
        self.assertEqual(board["overlay"]["path"], (inside / "board").as_posix())
        self.assertEqual(produce.check_storyboard(board, self.stored(produce.INPUTS_FILE)), [])

    def test_an_undo_back_to_an_earlier_storyboard_finds_its_own_composition_files(self):
        def answer(text: str) -> dict:
            return {"script": "s", "files": [{"path": "intro/index.html", "text": text}], "scenes": [
                {"visual": {"type": "composition", "path": "intro"}, "duration": 2.0, "reason": "r"}]}

        def page() -> Path:
            return Path(self.stored(produce.STORYBOARD_FILE)["scenes"][0]["visual"]["path"]) / "index.html"

        self.started(PLAN)
        app_think.approve(self.folder, StandInThinker([answer("<div>first</div>")]))
        first = page()
        app_think.edit_plan(self.folder, {"tone": "calm"})
        app_think.approve(self.folder, StandInThinker([answer("<div>second</div>")]))
        self.assertNotEqual(page(), first)
        self.assertEqual(page().read_text(encoding="utf-8"), "<div>second</div>")
        self.assertEqual(first.read_text(encoding="utf-8"), "<div>first</div>")     # both sets are on disk
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(page(), first)
        self.assertEqual(page().read_text(encoding="utf-8"), "<div>first</div>")

    def test_a_composition_without_its_page_costs_a_fix_round(self):
        self.started(PLAN)
        scene = {"visual": {"type": "composition", "path": "compositions/intro"}, "duration": 2.0, "reason": "r"}
        thinker = StandInThinker([{"script": "s", "scenes": [scene]}, BOARD])
        app_think.approve(self.folder, thinker)
        self.assertIn("compositions/intro has no index.html", thinker.asked[1][1])

    def test_a_composition_path_outside_the_video_is_refused(self):
        big, drive = "x" * 600_000, self.root.drive or "C:"
        for n, (path, text, problem) in enumerate((
                ("../x/index.html", "", "is not a relative path that stays in its folder"),
                ("../../../x/index.html", "", "is not a relative path that stays in its folder"),
                ("C:/x/index.html", "", "is not a relative path that stays in its folder"),
                ("/x/index.html", "", "is not a relative path that stays in its folder"),
                # A drive and no root joins under the video's folder on that drive, onto the video's own files.
                (f"{drive}inputs.json", "", "is not a relative path that stays in its folder"),
                (f"{drive.lower()}x/index.html", "", "is not a relative path that stays in its folder"),
                ("x/a.html:b.html", "", "is not a relative path that stays in its folder"),
                ("x/run.exe", "", "is not an .html, .css, .js, .svg or .json file"),
                ("x/index.html", big, "is over 512 KB"))):
            with self.subTest(path):
                folder = self.root / f"video-{n}"
                self.started(PLAN, folder=folder)
                def kept() -> dict:
                    return {p: p.read_bytes() if p.is_file() else None for p in self.root.rglob("*")
                            if p.name != produce.STORYBOARD_REQUEST}

                before, was_there = kept(), (folder / path).exists()
                thinker = StandInThinker([dict(BOARD, files=[{"path": path, "text": text}])] * 4)
                with self.assertRaises(ThinkError):
                    app_think.approve(folder, thinker)
                self.assertIn(f"files: {path} {problem}", thinker.asked[1][1])
                self.assertEqual((folder / path).exists(), was_there)
                self.assertEqual(kept(), before)

    def test_composition_files_of_more_than_4_mb_in_all_are_refused(self):
        self.started(PLAN)
        files = [{"path": f"x/{n}.js", "text": "x" * 500_000} for n in range(9)]
        thinker = StandInThinker([dict(BOARD, files=files), BOARD])
        app_think.approve(self.folder, thinker)
        self.assertIn("files: 4.5 MB in all is over 4 MB", thinker.asked[1][1])
        self.assertFalse((self.folder / "compositions").exists())

    def recorded(self) -> tuple[Path, Path]:
        """A plan started from one recording, prepared as one of a varying frame rate is: the file picked, and
        Frameflow's own copy, which the build reads."""
        picked, copy = self.root / "talk.mp4", self.root / "talk-cfr30.mp4"
        picked.write_bytes(b"a recording")
        copy.write_bytes(b"its copy")

        def transcribed(video, out, language):      # first_cut.prepare's files, with nothing said
            out.mkdir(parents=True)
            (out / "transcript.json").write_text(json.dumps({"segments": []}), encoding="utf-8")
            (out / "timing.json").write_text(json.dumps({"words": [], "pauses": []}), encoding="utf-8")
            return {"source": copy.as_posix()}

        with (mock.patch.object(produce.first_cut, "prepare", side_effect=transcribed),
              mock.patch.object(produce.eyes, "study", side_effect=_studied),
              mock.patch.object(produce, "analyze", return_value=mock.Mock(duration_seconds=20.0))):
            self.started(dict(PLAN, fps=30), footage=[picked])      # a frame rate, so the copy is never opened
        return picked, copy

    def test_a_recording_gone_since_it_was_prepared_stops_approve_before_any_thinking(self):
        _, copy = self.recorded()
        copy.unlink()
        thinker = StandInThinker([])
        with self.assertRaises(ThinkError) as raised:
            app_think.approve(self.folder, thinker)
        self.assertEqual(str(raised.exception), app_think.MISSING.format(name=copy.name))
        self.assertEqual(thinker.asked, [])

    def test_a_recordings_original_may_go_once_frameflow_has_its_copy(self):
        picked, _ = self.recorded()
        picked.unlink()
        self.assertEqual(app_think.approve(self.folder, StandInThinker([BOARD])), self.folder / produce.STORYBOARD_FILE)
        inputs = self.stored(produce.INPUTS_FILE)
        self.assertEqual(app_think._material(inputs), [Path(inputs["footage"][0]["source"])])


def _title(text: str) -> dict:
    return {"visual": {"type": "title", "text": text}, "duration": 2.0, "reason": "r"}


MOMENTS = {"clips": [{"clip": "red.mp4", "moments": [
    {"start": 0, "end": 1, "what": "red", "framing": "wide", "subject": "red"}]}]}


class TestDescribingTheClips(_Plan):
    """The agent's eyes in the app: a thinker that can see describes each clip before the plan."""

    def setUp(self):
        super().setUp()
        self.red = self.root / "red.mp4"
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=180x320:d=1",
                        "-pix_fmt", "yuv420p", str(self.red)], check=True)
        self.steps: list[str] = []

    def test_a_thinker_that_sees_describes_the_clips_before_the_plan(self):
        thinker = StandInThinker([MOMENTS, PLAN], can_see=True)
        app_think.start(self.folder, "a reel", thinker, assets=[self.red], step=self.steps.append)
        self.assertIn("Looking at your clips with Stand-in thinker", self.steps)
        self.assertIn("- red.mp4 0.0–1.0 s · wide · red", thinker.asked[1][1])   # the plan's request
        self.assertTrue((self.folder / "eyes" / "red" / "moments.json").exists())

    def test_moments_past_the_clip_are_sent_back(self):
        late = {"clips": [{"clip": "red.mp4", "moments": [dict(MOMENTS["clips"][0]["moments"][0], end=9)]}]}
        thinker = StandInThinker([late, MOMENTS, PLAN], can_see=True)
        app_think.start(self.folder, "a reel", thinker, assets=[self.red])
        self.assertIn("red.mp4, moment 1", thinker.asked[1][1])          # the fix round names the problem

    def test_a_thinker_that_cannot_see_goes_straight_to_the_plan(self):
        thinker = StandInThinker([PLAN], can_see=False)
        app_think.start(self.folder, "a reel", thinker, assets=[self.red], step=self.steps.append)
        self.assertNotIn("Looking at your clips with Stand-in thinker", self.steps)
        self.assertIn("- red.mp4, 1.0 s", thinker.asked[0][1])

    def test_try_again_neither_studies_nor_describes_again(self):                 # Review Focus 4
        app_think.start(self.folder, "a reel", StandInThinker([MOMENTS, PLAN], can_see=True), assets=[self.red])
        again = StandInThinker([PLAN], can_see=True)                              # only a plan is scripted
        with mock.patch.object(produce.eyes, "frames_at", side_effect=AssertionError("studied again")):
            app_think.start(self.folder, "a reel", again, assets=[self.red])
        self.assertEqual(len(again.asked), 1)


class _EditsWhileAnswering(StandInThinker):
    """A stand-in that rewrites the storyboard by hand while it answers."""

    def __init__(self, answers, path: Path, data: bytes):
        super().__init__(answers)
        self.path, self.data = path, data

    def _next(self, system: str, request: str):
        self.path.write_bytes(self.data)
        return super()._next(system, request)


class TestAChangeInWords(_Plan):
    def setUp(self):
        super().setUp()
        self.folder.mkdir()
        self.board = {"script": "s", "scenes": [_title("One"), _title("Two"), _title("Three")]}
        self.path = self.folder / produce.STORYBOARD_FILE
        self.path.write_text(json.dumps(self.board), encoding="utf-8")
        (self.folder / produce.INPUTS_FILE).write_text(
            json.dumps({"prompt": PROMPT, "footage": [], "assets": [], "music": []}), encoding="utf-8")

    def change(self, thinker, words: str = "Put three first, and drop two") -> dict:
        return app_think.change_in_words(self.folder, words, storyboard_edit.version(self.folder), thinker)

    def titles(self) -> list[str]:
        return [s["visual"]["text"] for s in json.loads(self.path.read_text(encoding="utf-8"))["scenes"]]

    def test_a_change_in_words_lands_as_one_undo(self):
        before = self.path.read_bytes()
        thinker = StandInThinker([{"ops": [{"op": "move", "from": 3, "to": 1}, {"op": "delete", "number": 3}],
                                   "summary": "Moved scene 3 to the start and removed scene 2"}])
        with mock.patch.object(thinker, "answer", wraps=thinker.answer) as answer:
            self.assertEqual(self.change(thinker),
                             {"notes": [], "summary": "Moved scene 3 to the start and removed scene 2"})
        self.assertFalse(answer.call_args.kwargs["search"])         # a change looks nothing up
        self.assertEqual(self.titles(), ["Three", "One"])
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.path.read_bytes(), before)            # byte for byte, in one undo
        self.assertEqual(storyboard_edit.history(self.folder), (False, True))

    def test_the_request_carries_the_storyboard_the_words_and_the_operations(self):
        thinker = StandInThinker([{"ops": [{"op": "delete", "number": 2}], "summary": "Removed scene 2"}])
        self.change(thinker)
        system, request = thinker.asked[0]
        self.assertEqual(system, app_think.SYSTEM)
        self.assertIn(json.dumps(self.board, indent=2, ensure_ascii=False), request)
        self.assertIn("3. Three", request)                          # what each scene says, by its number
        self.assertIn("Put three first, and drop two", request)
        for name in app_think.OPERATIONS:
            self.assertIn(f'{{"op": "{name}"', request)
        self.assertTrue(request.endswith(
            "Frameflow makes the change itself, checking each operation as it checks a change made by hand. "
            "Write no file, run no command and wait for nothing. Answer only with `ops`, the operations in the "
            "order to make them, and `summary`, one line of what changed; or, when these operations cannot make "
            "the change, only with `refused`, why in one line.\n"), request[-400:])

    def test_a_change_the_ops_cannot_make_costs_a_fix_round(self):
        thinker = StandInThinker([{"ops": [{"op": "delete", "number": 9}], "summary": "Removed scene 9"},
                                  {"ops": [{"op": "delete", "number": 3}], "summary": "Removed scene 3"}])
        self.assertEqual(self.change(thinker)["summary"], "Removed scene 3")
        self.assertEqual(len(thinker.asked), 2)
        self.assertIn("- There is no scene 9.", thinker.asked[1][1])
        self.assertEqual(self.titles(), ["One", "Two"])

    def test_a_file_the_creator_did_not_pick_costs_a_fix_round(self):
        picture = self.root / "other.png"
        picture.write_bytes(b"\x89PNG")
        thinker = StandInThinker([
            {"ops": [{"op": "picture", "number": 1, "path": picture.as_posix()}], "summary": "New picture"},
            {"refused": "That picture is not one of the video's files."}])
        with self.assertRaises(storyboard_edit.EditError):
            self.change(thinker)
        self.assertIn("- other.png is not one of your files.", thinker.asked[1][1])

    def test_an_answer_of_neither_shape_or_both_costs_a_fix_round(self):
        ops = [{"op": "delete", "number": 3}]
        thinker = StandInThinker([{"ops": ops, "summary": "Removed scene 3", "refused": "No"}, {"ops": ops},
                                  {"ops": [{"op": "erase", "number": 3}], "summary": "Removed scene 3"},
                                  {"ops": ops, "summary": "Removed scene 3"}])
        self.change(thinker)
        self.assertEqual(len(thinker.asked), 4)
        for asked in thinker.asked[1:3]:
            self.assertIn("- Answer with `ops` and `summary`, or with `refused` alone.", asked[1])
        self.assertEqual(self.titles(), ["One", "Two"])

    def test_a_note_for_the_creator_survives_the_check(self):
        picture = self.folder / "shot.png"
        picture.write_bytes(b"\x89PNG")
        (self.folder / produce.INPUTS_FILE).write_text(json.dumps(
            {"prompt": PROMPT, "footage": [], "assets": [{"path": picture.as_posix(), "kind": "image"}],
             "music": []}), encoding="utf-8")
        shot = {"visual": {"type": "asset", "path": picture.as_posix()}, "narration": "Hello there", "reason": "r"}
        self.path.write_text(json.dumps(dict(self.board, scenes=[shot])), encoding="utf-8")
        card = {"kind": "product", "text": "Hi", "when": "goodbye"}
        thinker = StandInThinker([{"ops": [{"op": "over", "number": 1, "cards": [card]}], "summary": "Added a card"}])
        self.assertEqual(self.change(thinker)["notes"], [
            "Card “Hi” now shows from the start of the scene: “goodbye” is not said in it any more."])

    def test_make_it_shorter_sets_a_length_as_one_undo(self):
        before = self.path.read_bytes()
        thinker = StandInThinker([{"ops": [{"op": "duration", "number": 1, "seconds": 1}],
                                   "summary": "Scene 1 now lasts 1 second"}])
        self.assertEqual(self.change(thinker, "Make scene 1 shorter"),
                         {"notes": [], "summary": "Scene 1 now lasts 1 second"})
        self.assertIn("a title's, picture's or composition's through `duration`", thinker.asked[0][1])
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["scenes"][0]["duration"], 1)
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(storyboard_edit.history(self.folder), (False, True))

    def test_a_refused_change_says_why_and_changes_nothing(self):
        before = self.path.read_bytes()
        thinker = StandInThinker([{"refused": "The music's volume can't be changed in words yet."}])
        with self.assertRaises(storyboard_edit.EditError) as raised:
            self.change(thinker, "Make the music quieter")
        self.assertEqual(str(raised.exception), "The music's volume can't be changed in words yet.")
        self.assertFalse(raised.exception.changed)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))

    def test_a_storyboard_changed_while_thinking_is_refused(self):
        by_hand = json.dumps(dict(self.board, scenes=[_title("By hand")])).encode("utf-8")
        # Its op could not be made on the hand edit; that is still refused as changed, not sent back to fix.
        thinker = _EditsWhileAnswering([{"ops": [{"op": "delete", "number": 3}], "summary": "Removed scene 3"}],
                                       self.path, by_hand)
        with self.assertRaises(storyboard_edit.EditError) as raised:
            self.change(thinker)
        self.assertTrue(raised.exception.changed)
        self.assertEqual(str(raised.exception), storyboard_edit.CHANGED)
        self.assertEqual(len(thinker.asked), 1)
        self.assertEqual(self.path.read_bytes(), by_hand)           # the hand edit is kept
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))

    def test_the_command_line_prints_what_changed(self):
        answer = {"ops": [{"op": "delete", "number": 2}], "summary": "Removed scene 2"}
        code, out, err = _main(self.root, "change", self.folder, "--words", "Drop two", "--version",
                               storyboard_edit.version(self.folder), answers=[answer])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), ["==> Making the change",
                                            '==> Done {"summary": "Removed scene 2", "notes": []}'])
        self.assertEqual(self.titles(), ["One", "Three"])

    def test_the_command_line_tells_a_refusal_from_a_storyboard_changed_outside(self):
        version = storyboard_edit.version(self.folder)
        code, _, err = _main(self.root, "change", self.folder, "--words", "Quieter music", "--version", version,
                             answers=[{"refused": "The music's volume can't be changed in words yet."}])
        # Its own code, which the app reads as a refusal (4), not a failure (1) or changed outside (3).
        self.assertEqual((code, err), (app_think.EXIT_REFUSED, "The music's volume can't be changed in words yet.\n"))
        self.assertEqual(app_think.EXIT_REFUSED, 4)
        code, _, err = _main(self.root, "change", self.folder, "--words", "Drop two", "--version", "0" * 16)
        self.assertEqual((code, err), (app_think.EXIT_CHANGED, storyboard_edit.CHANGED + "\n"))

    def test_a_change_against_an_old_version_is_refused_before_thinking(self):
        thinker = StandInThinker([])
        with self.assertRaises(storyboard_edit.EditError) as raised:
            app_think.change_in_words(self.folder, "Drop two", "0" * 16, thinker)
        self.assertTrue(raised.exception.changed)
        self.assertEqual(thinker.asked, [])

    def test_a_deleted_music_file_or_look_stops_a_change_in_words(self):
        for key, name, entry in (("music", "song.mp3", {"duration": 60.0}), ("looks", "warm.cube", {})):
            with self.subTest(key):
                gone = self.root / name
                gone.write_bytes(b"")
                (self.folder / produce.INPUTS_FILE).write_text(json.dumps(
                    {"prompt": PROMPT, "footage": [], "assets": [], "music": [],
                     key: [dict(entry, path=gone.as_posix())]}), encoding="utf-8")
                gone.unlink()
                thinker = StandInThinker([])
                with self.assertRaises(ThinkError) as raised:
                    self.change(thinker)
                self.assertEqual(str(raised.exception), app_think.MISSING.format(name=name))
                self.assertEqual(thinker.asked, [])


if __name__ == "__main__":
    unittest.main()
