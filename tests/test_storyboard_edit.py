"""The changes a creator makes to a storyboard in the app, one operation at a time."""
import json
import sys
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from project import storyboard_edit
from project.media import _find_tool
from project.storyboard_edit import EditError

WORDS = [{"start": 1.0, "end": 1.3, "text": " Hello"}, {"start": 1.5, "end": 1.9, "text": " there."},
         {"start": 2.6, "end": 2.7, "text": " The"}, {"start": 2.7, "end": 3.0, "text": " goal"},
         {"start": 3.0, "end": 3.2, "text": " is"}, {"start": 10.0, "end": 10.1, "text": " the"},
         {"start": 10.1, "end": 10.4, "text": " goal"}]
PAUSES = [{"start": 0.0, "end": 1.0}, {"start": 1.9, "end": 2.6}, {"start": 3.2, "end": 3.9},
          {"start": 9.4, "end": 10.0}, {"start": 10.4, "end": 11.0}]
BRIEF = {"title": "Nomad reel", "format": "product reel", "aspect": "9:16", "target_seconds": 15, "fps": 30,
         "audience": "a", "tone": "t", "summary": "s"}


def footage(start: float, end: float) -> dict:
    return {"visual": {"type": "footage", "source": "talk.mp4", "start": start, "end": end}, "reason": "r"}


class _Video(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "my video"            # a space, as in "E:\\my projects"
        (self.folder / "f").mkdir(parents=True)
        (self.folder / "f" / "timing.json").write_text(json.dumps({"words": WORDS, "pauses": PAUSES}))
        self.image = (self.folder / "shot.png").as_posix()
        Path(self.image).write_bytes(b"\x89PNG")
        self.look = self.folder / "warm.cube"
        self.look.write_text("LUT_3D_SIZE 2\n")
        self.inputs = {"footage": [{"name": "talk.mp4", "source": "C:/x/talk.mp4", "duration": 20.0, "folder": "f"}],
                       "assets": [{"path": self.image, "kind": "image"}], "music": [],
                       "looks": [{"path": self.look.as_posix()}]}
        self.board = {"script": "s", "scenes": [
            footage(0.8, 2.0), footage(2.3, 3.4),
            {"visual": {"type": "title", "text": "Hook"}, "narration": "Meet it", "reason": "r"},
            footage(9.7, 10.6)],
            "sections": [{"title": "A", "from": 1}, {"title": "B", "from": 3}]}
        self.write()

    def write(self) -> None:
        for name, document in (("inputs.json", self.inputs), ("brief.json", BRIEF), ("storyboard.json", self.board)):
            (self.folder / name).write_text(json.dumps(document), encoding="utf-8")

    def stored(self) -> dict:
        return json.loads((self.folder / "storyboard.json").read_text(encoding="utf-8"))

    def apply(self, **op) -> list[str]:
        return storyboard_edit.apply(self.folder, op)

    def spans(self) -> list:
        return [(s["visual"].get("start"), s["visual"].get("end")) for s in self.stored()["scenes"]]

    def refused(self, op: dict, chosen=()) -> str:
        before = (self.folder / "storyboard.json").read_bytes(), (self.folder / "inputs.json").read_bytes()
        with self.assertRaises(EditError) as raised:
            storyboard_edit.apply(self.folder, op, chosen)
        self.assertEqual(before, ((self.folder / "storyboard.json").read_bytes(),
                                  (self.folder / "inputs.json").read_bytes()))     # nothing written
        return str(raised.exception)


class TestOrder(_Video):
    def test_a_move_renumbers_and_the_moved_scene_joins_the_chapter_it_lands_in(self):
        self.apply(op="move", **{"from": 4, "to": 1})
        self.assertEqual(self.spans(), [(9.7, 10.6), (0.8, 2.0), (2.3, 3.4), (None, None)])
        self.assertEqual(self.stored()["sections"], [{"title": "A", "from": 1}, {"title": "B", "from": 4}])

    def test_moving_a_chapters_first_scene_away_starts_it_at_the_next(self):
        self.apply(op="move", **{"from": 3, "to": 1})
        self.assertEqual(self.spans(), [(None, None), (0.8, 2.0), (2.3, 3.4), (9.7, 10.6)])
        self.assertEqual(self.stored()["sections"], [{"title": "A", "from": 1}, {"title": "B", "from": 4}])

    def test_a_scene_moved_to_the_front_of_its_chapter_stays_in_it(self):
        self.apply(op="move", **{"from": 4, "to": 3})            # chapter B is [title, scene 4]: 4 onto the title
        self.assertEqual(self.spans(), [(0.8, 2.0), (2.3, 3.4), (9.7, 10.6), (None, None)])
        self.assertEqual(self.stored()["sections"], [{"title": "A", "from": 1}, {"title": "B", "from": 3}])

    def test_a_change_waits_for_a_reader_holding_the_storyboard_open(self):
        reader = (self.folder / "storyboard.json").open("rb")   # as a thumbnail does; Windows refuses a replace then
        self.addCleanup(reader.close)
        threading.Timer(0.3, reader.close).start()
        self.apply(op="delete", number=4)
        self.assertEqual(len(self.stored()["scenes"]), 3)

    def test_deleting_a_chapters_last_scene_removes_the_chapter(self):
        self.apply(op="delete", number=4)
        self.apply(op="delete", number=3)
        self.assertEqual(self.stored()["sections"], [{"title": "A", "from": 1}])

    def test_the_only_scene_cannot_be_deleted(self):
        self.board["scenes"] = self.board["scenes"][:1]
        self.board.pop("sections")
        self.write()
        self.assertEqual(self.refused({"op": "delete", "number": 1}), "A video needs at least one scene.")

    def test_a_scene_that_is_not_there_is_named(self):
        self.assertEqual(self.refused({"op": "delete", "number": 9}), "There is no scene 9.")


class TestWords(_Video):
    def test_new_words_pick_the_span_where_they_are_said(self):
        self.apply(op="words", number=1, words="the goal is")
        start, end = self.spans()[0]
        self.assertTrue(2.3 <= start <= 2.4 and 3.4 <= end <= 3.5, (start, end))
        self.assertEqual(storyboard_edit.said(self.stored()["scenes"][0], self.folder, self.inputs), "The goal is")

    def test_words_not_said_are_refused_and_nothing_changes(self):
        self.assertEqual(self.refused({"op": "words", "number": 1, "words": "goodbye"}),
                         "Not said in your recording. The words stay as they were.")

    def test_words_with_nothing_to_search_for_are_refused_with_the_reason(self):
        self.assertIn("has no words Frameflow can search for yet",
                      self.refused({"op": "words", "number": 1, "words": "..."}))

    def test_words_on_a_title_are_its_narration_and_empty_words_give_it_a_duration(self):
        self.assertEqual(self.apply(op="words", number=3, words="Meet the Nomad"), [])
        self.assertEqual(self.stored()["scenes"][2]["narration"], "Meet the Nomad")
        self.assertEqual(self.apply(op="words", number=3, words="  "), ["It now lasts 3 seconds."])
        scene = self.stored()["scenes"][2]
        self.assertNotIn("narration", scene)
        self.assertEqual(scene["duration"], 3.0)

    def test_a_card_whose_words_leave_the_scene_shows_from_its_start(self):
        self.board["scenes"][0]["cards"] = [{"kind": "product", "text": "Nomad", "when": "Hello"}]
        self.write()
        notes = self.apply(op="words", number=1, words="there")
        self.assertEqual(self.stored()["scenes"][0]["cards"], [{"kind": "product", "text": "Nomad"}])
        self.assertEqual(notes, ["Card “Nomad” now shows from the start of the scene: "
                                 "“Hello” is not said in it any more."])

    def test_a_title_s_words_on_screen_change_and_only_on_a_title(self):
        self.apply(op="title", number=3, text="Hook, again")
        self.assertEqual(self.stored()["scenes"][2]["visual"]["text"], "Hook, again")
        self.assertEqual(self.refused({"op": "title", "number": 1, "text": "x"}), "Only a title has words on screen.")


class TestPictures(_Video):
    def test_a_picture_on_footage_covers_it_with_b_roll_and_keeps_the_recording(self):
        self.apply(op="picture", number=1, path=self.image)
        scene = self.stored()["scenes"][0]
        self.assertEqual(scene["visual"], footage(0.8, 2.0)["visual"])
        self.assertEqual(scene["broll"], [{"path": self.image, "duration": 1.2}])

    def test_a_picture_on_a_title_replaces_it(self):
        self.apply(op="picture", number=3, path=self.image)
        scene = self.stored()["scenes"][2]
        self.assertEqual(scene["visual"], {"type": "asset", "path": self.image})
        self.assertEqual(scene["narration"], "Meet it")            # what is said stays

    def test_a_file_not_chosen_is_refused_and_inputs_are_unchanged(self):
        other = (self.folder / "other.png")
        other.write_bytes(b"\x89PNG")
        self.assertEqual(self.refused({"op": "picture", "number": 3, "path": other.as_posix()}),
                         "other.png is not one of your files.")

    def test_a_chosen_clip_is_added_to_inputs_once(self):
        try:
            ffmpeg = _find_tool("ffmpeg")
        except Exception:
            self.skipTest("FFmpeg not found")
        clip = self.folder / "walk.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30", "-t", "2",
                        "-pix_fmt", "yuv420p", str(clip)], check=True)
        chosen = [str(clip)]
        storyboard_edit.apply(self.folder, {"op": "picture", "number": 3, "path": str(clip)}, chosen)
        storyboard_edit.apply(self.folder, {"op": "add", "after": 4, "scene": {"kind": "file", "path": str(clip)}},
                              chosen)
        assets = json.loads((self.folder / "inputs.json").read_text())["assets"]
        clips = [a for a in assets if a["kind"] == "clip"]
        self.assertEqual(len(clips), 1)
        self.assertEqual((round(clips[0]["duration"]), clips[0]["size"]), (2, "320x240"))

    def test_a_chosen_file_frameflow_cannot_read_is_refused(self):
        notes = self.folder / "notes.mp4"
        notes.write_text("not a video")
        self.assertEqual(self.refused({"op": "picture", "number": 3, "path": str(notes)}, [str(notes)]),
                         "Frameflow can't read notes.mp4 as a picture or a clip.")


class TestAdding(_Video):
    def test_adding_from_the_recording_finds_the_words(self):
        self.apply(op="add", after=4, scene={"kind": "recording", "words": "hello there"})
        scene = self.stored()["scenes"][4]
        self.assertEqual((scene["visual"]["type"], scene["visual"]["source"]), ("footage", "talk.mp4"))
        self.assertEqual(scene["reason"], "Added by the creator in the app")
        self.assertTrue(0.7 <= scene["visual"]["start"] <= 0.8, scene["visual"])

    def test_adding_a_title_after_scene_2_joins_chapter_a(self):
        self.apply(op="add", after=2, scene={"kind": "title", "text": "Halfway"})
        board = self.stored()
        self.assertEqual(board["scenes"][2], {"visual": {"type": "title", "text": "Halfway"}, "duration": 2.0,
                                              "reason": "Added by the creator in the app"})
        self.assertEqual(board["sections"], [{"title": "A", "from": 1}, {"title": "B", "from": 4}])

    def test_adding_at_the_start_joins_the_first_chapter(self):
        self.apply(op="add", after=0, scene={"kind": "file", "path": self.image})
        board = self.stored()
        self.assertEqual(board["scenes"][0]["visual"], {"type": "asset", "path": self.image})
        self.assertEqual(board["scenes"][0]["duration"], 3.0)
        self.assertEqual(board["sections"], [{"title": "A", "from": 1}, {"title": "B", "from": 4}])


class TestChapters(_Video):
    def test_removing_the_first_chapter_gives_its_scenes_to_the_next_which_starts_at_1(self):
        self.apply(op="remove_chapter", number=1)
        self.assertEqual(self.stored()["sections"], [{"title": "B", "from": 1}])

    def test_removing_a_later_chapter_gives_its_scenes_to_the_one_before(self):
        self.apply(op="remove_chapter", number=2)
        self.assertEqual(self.stored()["sections"], [{"title": "A", "from": 1}])

    def test_removing_the_only_chapter_leaves_no_sections(self):
        self.apply(op="remove_chapter", number=1)
        self.apply(op="remove_chapter", number=1)
        self.assertNotIn("sections", self.stored())

    def test_renaming_a_chapter_confirms_it(self):
        self.apply(op="rename_chapter", number=2, title="  The turn ")
        self.assertEqual(self.stored()["sections"][1], {"title": "The turn", "from": 3, "confirmed": True})
        self.apply(op="keep_chapter", number=1)
        self.assertTrue(self.stored()["sections"][0]["confirmed"])


class TestTheWholeVideo(_Video):
    def test_captions_switch_on_and_off(self):
        self.apply(op="video", spoken_captions=True)
        self.assertTrue(self.stored()["spoken_captions"])
        self.apply(op="video", spoken_captions=False)
        self.assertFalse(self.stored()["spoken_captions"])

    def test_cut_to_the_beat_without_music_is_refused(self):
        self.assertEqual(self.refused({"op": "video", "cut_to_beat": True}), "This video has no music to cut to.")

    def test_a_look_must_be_one_the_video_can_use(self):
        self.apply(op="video", look="warm.cube")
        self.assertEqual(self.stored()["look"], {"path": "warm.cube"})
        self.assertEqual(self.refused({"op": "video", "look": "teal.cube"}), "teal.cube is not one of this video's looks.")
        self.apply(op="video", look=None)
        self.assertNotIn("look", self.stored())


class TestChecks(_Video):
    def test_a_change_that_breaks_the_storyboard_says_why_and_writes_nothing(self):
        message = self.refused({"op": "over", "number": 3, "broll": [{"path": self.image}]})
        self.assertTrue(message.startswith("That change can't be made: "), message)
        self.assertIn("B-roll goes over footage", message)

    def test_over_replaces_what_it_names_and_empty_removes_it(self):
        self.apply(op="over", number=1, caption="Hi", cards=[{"kind": "lower_third", "text": "Satwik"}])
        scene = self.stored()["scenes"][0]
        self.assertEqual((scene["caption"], scene["cards"]), ("Hi", [{"kind": "lower_third", "text": "Satwik"}]))
        self.apply(op="over", number=1, caption="", cards=[])
        self.assertNotIn("caption", self.stored()["scenes"][0])
        self.assertNotIn("cards", self.stored()["scenes"][0])

    def test_an_unknown_change_is_named(self):
        self.assertEqual(self.refused({"op": "shuffle"}), "Unknown change 'shuffle'.")


if __name__ == "__main__":
    unittest.main()


class TestVersionsAndUndo(_Video):
    def edit(self, **op) -> list[str]:
        return storyboard_edit.edit(self.folder, op, storyboard_edit.version(self.folder))

    def bytes(self) -> bytes:
        return (self.folder / "storyboard.json").read_bytes()

    def test_a_version_is_16_hex_digits_and_changes_with_the_file(self):
        before = storyboard_edit.version(self.folder)
        self.assertRegex(before, r"^[0-9a-f]{16}$")
        self.edit(op="delete", number=4)
        self.assertNotEqual(storyboard_edit.version(self.folder), before)

    def test_an_edit_against_an_old_version_is_refused_as_changed(self):
        old = storyboard_edit.version(self.folder)
        self.edit(op="delete", number=4)
        now = self.bytes()
        with self.assertRaises(EditError) as raised:
            storyboard_edit.edit(self.folder, {"op": "delete", "number": 1}, old)
        self.assertTrue(raised.exception.changed)
        self.assertEqual(str(raised.exception), "The storyboard changed outside the app, so it was reloaded. "
                                                "Your last change was not made.")
        self.assertEqual(self.bytes(), now)

    def test_undo_and_redo_walk_the_history(self):
        first = self.bytes()
        self.edit(op="delete", number=4)
        second = self.bytes()
        self.edit(op="delete", number=3)
        self.edit(op="delete", number=2)
        self.assertEqual(storyboard_edit.history(self.folder), (True, False))
        for _ in range(3):
            storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.bytes(), first)
        self.assertEqual(storyboard_edit.history(self.folder), (False, True))
        storyboard_edit.redo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.bytes(), second)

    def test_a_new_edit_after_undo_clears_redo(self):
        self.edit(op="delete", number=4)
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.edit(op="delete", number=3)
        self.assertEqual(storyboard_edit.history(self.folder), (True, False))

    def test_undo_past_the_beginning_says_so(self):
        for step, message in ((storyboard_edit.undo, "Nothing to undo."), (storyboard_edit.redo, "Nothing to redo.")):
            with self.assertRaises(EditError) as raised:
                step(self.folder, storyboard_edit.version(self.folder))
            self.assertEqual(str(raised.exception), message)

    def test_undo_is_refused_when_the_file_changed_outside_the_app(self):
        self.edit(op="delete", number=4)
        old = storyboard_edit.version(self.folder)
        self.board["script"] = "written by an editor"
        self.write()
        with self.assertRaises(EditError) as raised:
            storyboard_edit.undo(self.folder, old)
        self.assertTrue(raised.exception.changed)
        self.assertIn("written by an editor", self.bytes().decode())

    def test_undo_never_reaches_back_past_a_change_made_outside_the_app(self):
        self.edit(op="delete", number=4)
        self.board = self.stored()
        self.board["script"] = "written by an editor"
        self.write()                                              # the app reloads, and holds this version
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))
        with self.assertRaises(EditError) as raised:
            storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(str(raised.exception), "Nothing to undo.")
        self.assertIn("written by an editor", self.bytes().decode())

    def test_a_refused_edit_leaves_no_history(self):
        with self.assertRaises(EditError):
            self.edit(op="words", number=1, words="goodbye")
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))

    def test_the_history_survives_a_new_process(self):
        first = self.bytes()
        code = ("import sys; from pathlib import Path; from project import storyboard_edit as e; "
                "f = Path(sys.argv[1]); e.edit(f, {'op': 'delete', 'number': 4}, e.version(f))")
        subprocess.run([sys.executable, "-c", code, str(self.folder)], check=True, cwd=Path(__file__).parent.parent)
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.bytes(), first)

    def test_history_keeps_the_newest_200(self):
        for _ in range(103):
            self.edit(op="move", **{"from": 1, "to": 2})
            self.edit(op="move", **{"from": 2, "to": 1})
        self.assertEqual(len(list((self.folder / "app_cache" / "undo").iterdir())), 200)

    def both(self) -> tuple[bytes, bytes]:
        return (self.folder / "brief.json").read_bytes(), self.bytes()

    def replace(self) -> None:
        storyboard_edit.replace(self.folder, dict(BRIEF, tone="calm"), dict(self.board, script="new"),
                                storyboard_edit.version(self.folder))

    def test_one_undo_brings_back_the_old_plan_and_storyboard(self):
        old = self.both()
        self.replace()
        new = self.both()
        self.assertEqual(json.loads(new[0])["tone"], "calm")
        self.assertEqual(self.stored()["script"], "new")
        self.assertEqual(storyboard_edit.history(self.folder), (True, False))
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.both(), old)
        self.assertEqual(storyboard_edit.history(self.folder), (False, True))
        storyboard_edit.redo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.both(), new)

    def test_a_hand_edit_after_a_replace_undoes_on_its_own(self):
        old = self.both()
        self.replace()
        new = self.both()
        self.edit(op="delete", number=4)
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.both(), new)          # the hand edit only: the plan stays the new one
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.both(), old)

    def test_a_replace_in_a_new_video_leaves_nothing_to_undo(self):
        (self.folder / "storyboard.json").unlink()
        storyboard_edit.replace(self.folder, BRIEF, self.board, None)
        self.assertEqual(self.stored(), self.board)
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))

    def test_a_replace_against_an_old_version_is_refused_as_changed(self):
        old, before = storyboard_edit.version(self.folder), self.both()
        self.edit(op="delete", number=4)
        now = self.both()
        with self.assertRaises(EditError) as raised:
            storyboard_edit.replace(self.folder, dict(BRIEF, tone="calm"), self.board, old)
        self.assertTrue(raised.exception.changed)
        self.assertEqual(self.both(), now)
        self.assertNotEqual(now, before)

    def test_edit_many_makes_every_op_as_one_undo(self):
        first = self.bytes()
        ops = [{"op": "delete", "number": 4}, {"op": "move", "from": 3, "to": 1}]
        self.assertEqual(storyboard_edit.edit_many(self.folder, ops, storyboard_edit.version(self.folder)), [])
        self.assertEqual([s["visual"]["type"] for s in self.stored()["scenes"]], ["title", "footage", "footage"])
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.bytes(), first)
        self.assertEqual(storyboard_edit.history(self.folder), (False, True))

    def test_edit_many_is_refused_when_the_version_moved(self):
        old = storyboard_edit.version(self.folder)
        self.edit(op="delete", number=4)
        now = self.bytes()
        with self.assertRaises(EditError) as raised:
            storyboard_edit.edit_many(self.folder, [{"op": "delete", "number": 1}], old)
        self.assertTrue(raised.exception.changed)
        self.assertEqual(str(raised.exception), storyboard_edit.CHANGED)
        self.assertEqual(self.bytes(), now)

    def test_edit_many_with_an_op_that_cannot_be_made_makes_none(self):
        first = self.bytes()
        with self.assertRaises(EditError) as raised:
            storyboard_edit.edit_many(self.folder, [{"op": "delete", "number": 4}, {"op": "delete", "number": 9}],
                                      storyboard_edit.version(self.folder))
        self.assertEqual(str(raised.exception), "There is no scene 9.")
        self.assertEqual(self.bytes(), first)
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))

    def test_check_ops_says_the_first_refusal_and_writes_nothing(self):
        first = self.bytes()
        delete = {"op": "delete", "number": 4}
        self.assertEqual(storyboard_edit.check_ops(self.folder, [delete, {"op": "delete", "number": 3}]), [])
        # Each op sees the storyboard the ones before it left: there is no scene 4 the second time.
        self.assertEqual(storyboard_edit.check_ops(self.folder, [delete, delete, {"op": "nonsense"}]),
                         ["There is no scene 4."])
        self.assertEqual(storyboard_edit.check_ops(self.folder, [{"op": "title", "number": 3, "text": 5}]),
                         ["An operation is not in the shape the request gives for it."])
        self.assertEqual(self.bytes(), first)
        self.assertEqual(storyboard_edit.history(self.folder), (False, False))

    def test_check_ops_leaves_the_ops_as_they_were_given(self):
        ops = [{"op": "over", "number": 1, "cards": [{"kind": "product", "text": "Hi", "when": "goodbye"}]}]
        given = json.loads(json.dumps(ops))
        self.assertEqual(storyboard_edit.check_ops(self.folder, ops), [])
        self.assertEqual(ops, given)

    def test_a_length_is_set_on_a_title_and_undone(self):
        self.edit(op="add", after=0, scene={"kind": "title", "text": "Hook"})
        before = self.bytes()
        self.assertEqual(self.edit(op="duration", number=1, seconds=1.5), [])
        self.assertEqual(self.stored()["scenes"][0]["duration"], 1.5)
        storyboard_edit.undo(self.folder, storyboard_edit.version(self.folder))
        self.assertEqual(self.bytes(), before)

    def test_a_length_is_refused_where_a_recording_or_narration_sets_it(self):
        self.edit(op="add", after=0, scene={"kind": "title", "text": "Hook"})
        for number in (2, 4):       # a recording's scene, and a narrated title
            self.assertEqual(self.refused({"op": "duration", "number": number, "seconds": 2}),
                             f"Scene {number}'s length comes from its recording or its narration.")
        for seconds in (0.4, 601, "2", True, None):
            self.assertEqual(self.refused({"op": "duration", "number": 1, "seconds": seconds}),
                             "A scene lasts from 0.5 to 600 seconds.")

    def test_check_ops_refuses_a_file_the_creator_did_not_pick(self):
        other = Path(self.tmp.name) / "other.png"
        other.write_bytes(b"\x89PNG")
        self.assertEqual(storyboard_edit.check_ops(self.folder, [{"op": "picture", "number": 3,
                                                                  "path": other.as_posix()}]),
                         ["other.png is not one of your files."])
