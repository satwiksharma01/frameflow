#!/usr/bin/env python3
"""Tests for operations: changes to a project the creator already has.

Run with: python -m unittest discover tests
"""
import copy
import tempfile
import unittest
from pathlib import Path

from project.cutpoints import PAD_SECONDS, frame_align
from project.operations import add_broll, add_graphics, apply, check, move_with_cut, resolve
from project.parse_mlt import parse_mlt
from project.reconcile import HumanChanges, reconcile, source_key
from project.sidecar import read_sidecar
from project.validate import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
HUMAN_EDITED = REPO_ROOT / "examples" / "human-edited.mlt"
SOURCE = "C:/media/talk.mp4"
FPS = 30
UNCHANGED = HumanChanges(known=True)


def ir(*spans, gaps=None):
    """A main track from (source_in, source_out) pairs, end to end unless gaps say otherwise."""
    clips, cursor = [], 0.0
    for n, (start, end) in enumerate(spans, start=1):
        cursor += (gaps or {}).get(n, 0.0)
        clips.append({"id": f"clip{n}", "source": SOURCE, "source_in": start, "source_out": end,
                      "timeline_start": cursor, "timeline_duration": end - start})
        cursor += end - start
    return {"schema_version": "0.2.0",
            "project": {"name": "t", "width": 1920, "height": 1080, "fps": FPS,
                        "source_frame_rate_mode": "cfr"},
            "tracks": [{"id": "V1", "type": "video", "clips": clips}]}


def op(action, start, end, **extra):
    return {"summary": "test", "operations": [
        {"action": action, "start": start, "end": end, "reason": "test", **extra}]}


def run(project, doc, changes=UNCHANGED, pauses=None):
    """Resolve and apply; fail loudly if either step reports a problem."""
    operations, problems = resolve(doc, project, changes, pauses)
    assert not problems, problems
    result, problems = apply(project, operations)
    assert not problems, problems
    validate(result, "ir")
    return result


def spans(project):
    return [(c["source_in"], c["source_out"]) for c in project["tracks"][0]["clips"]]


def starts(project):
    return [c["timeline_start"] for c in project["tracks"][0]["clips"]]


class TestRemove(unittest.TestCase):
    BASE = ir((0, 4), (6, 10), (12, 15))

    def test_removing_a_whole_clip_ripples_what_follows(self):
        result = run(self.BASE, op("remove", 6, 10))
        self.assertEqual(spans(result), [(0, 4), (12, 15)])
        self.assertEqual(starts(result), [0, 4])

    def test_removing_the_middle_of_a_clip_splits_it(self):
        result = run(self.BASE, op("remove", 7, 8))
        self.assertEqual(spans(result), [(0, 4), (6, 7), (8, 10), (12, 15)])
        self.assertEqual(starts(result), [0, 4, 5, 7])

    def test_removing_the_start_of_a_clip_trims_it(self):
        self.assertEqual(spans(run(self.BASE, op("remove", 5, 7))), [(0, 4), (7, 10), (12, 15)])

    def test_one_removal_can_span_several_clips(self):
        self.assertEqual(spans(run(self.BASE, op("remove", 3, 13))), [(0, 3), (13, 15)])

    def test_clip_ids_are_renumbered_because_nothing_refers_to_them(self):
        result = run(self.BASE, op("remove", 7, 8))
        self.assertEqual([c["id"] for c in result["tracks"][0]["clips"]],
                         ["clip1", "clip2", "clip3", "clip4"])

    def test_a_gap_the_human_left_survives_an_unrelated_removal(self):
        result = run(ir((0, 4), (6, 10), (12, 15), gaps={3: 2.0}), op("remove", 1, 2))
        self.assertEqual(starts(result), [0, 1, 3, 9])

    def test_removing_what_is_not_in_the_cut_is_reported(self):
        self.assertIn("nothing to remove", check(op("remove", 4.5, 5.5), self.BASE, UNCHANGED)[0])

    def test_a_flash_frame_is_refused(self):
        problems = check(op("remove", 4.05, 10), ir((4, 10), (12, 15)), UNCHANGED)
        self.assertIn("flash frame", problems[0])

    def test_removing_everything_is_refused(self):
        problems = check(op("remove", 0, 15), self.BASE, UNCHANGED)
        self.assertIn("everything", problems[0])


class TestRestore(unittest.TestCase):
    BASE = ir((0, 4), (6, 10), (12, 15))

    def test_restoring_a_whole_gap_joins_the_clips_either_side(self):
        """The first cut removed 4-6; putting it back should read as one clip, not three."""
        self.assertEqual(spans(run(self.BASE, op("restore", 4, 6))), [(0, 10), (12, 15)])

    def test_joined_clips_keep_the_outer_fades(self):
        project = ir((0, 4), (6, 10), (12, 15))
        first, second = project["tracks"][0]["clips"][:2]
        first.update(fade_in={"picture": 1.0}, fade_out={"sound": 1.0})
        second["fade_out"] = {"picture": 2.0}
        joined = run(project, op("restore", 4, 6))["tracks"][0]["clips"][0]
        self.assertEqual((joined["fade_in"], joined["fade_out"]), ({"picture": 1.0}, {"picture": 2.0}))

    def test_restoring_part_of_a_gap_lands_in_recording_order(self):
        result = run(self.BASE, op("restore", 10.5, 11.5))
        self.assertEqual(spans(result), [(0, 4), (6, 10), (10.5, 11.5), (12, 15)])
        self.assertEqual(starts(result), [0, 4, 8, 9])

    def test_restoring_before_the_first_clip(self):
        result = run(ir((6, 10)), op("restore", 1, 3))
        self.assertEqual(spans(result), [(1, 3), (6, 10)])

    def test_only_the_missing_part_of_a_span_is_added(self):
        """Restoring 3-7 must not duplicate 3-4 and 6-7, which are already in the cut."""
        self.assertEqual(spans(run(self.BASE, op("restore", 3, 7))), [(0, 10), (12, 15)])

    def test_what_is_put_back_is_framed_like_the_recording_around_it(self):
        """In a vertical cut, speech put back is cropped like its neighbours, not letterboxed."""
        project = ir((0, 4), (12, 15))
        for clip in project["tracks"][0]["clips"]:
            clip["transform"] = {"fill": True, "position": {"x": 0.05}}
        result = run(project, op("restore", 6, 10))
        self.assertEqual(spans(result), [(0, 4), (6, 10), (12, 15)])
        self.assertEqual(result["tracks"][0]["clips"][1]["transform"], {"fill": True, "position": {"x": 0.05}})

    def test_what_is_put_back_is_as_loud_as_the_recording_around_it(self):
        project = ir((0, 4), (12, 15))
        for clip in project["tracks"][0]["clips"]:
            clip["volume_db"] = 13.2
        result = run(project, op("restore", 6, 10))
        self.assertEqual(result["tracks"][0]["clips"][1]["volume_db"], 13.2)

    def test_restoring_what_is_already_there_is_reported(self):
        self.assertIn("already in the cut", check(op("restore", 1, 3), self.BASE, UNCHANGED)[0])


class TestPlacement(unittest.TestCase):
    PAUSES = {source_key(SOURCE): [{"start": 6.8, "end": 7.6}, {"start": 8.9, "end": 9.5},
                                   {"start": 3.0, "end": 3.08}]}

    def test_both_ends_land_in_pauses_on_the_speech_side(self):
        operations, problems = resolve(op("remove", 7.0, 9.1), ir((0, 12)), UNCHANGED, self.PAUSES)
        self.assertEqual(problems, [])
        self.assertAlmostEqual(operations[0].start, frame_align(6.8 + PAD_SECONDS, FPS), places=6)
        self.assertAlmostEqual(operations[0].end, frame_align(9.5 - PAD_SECONDS, FPS), places=6)

    def test_a_boundary_in_a_pause_under_three_frames_is_refused(self):
        """Finding 5's 80ms gap. The first cut can only warn; here the editor can move it."""
        problems = check(op("remove", 3.04, 7.0), ir((0, 12)), UNCHANGED, self.PAUSES)
        self.assertIn("under three frames", problems[0])

    def test_a_boundary_far_from_any_pause_is_allowed_but_noted(self):
        operations, problems = resolve(op("remove", 1.0, 7.0), ir((0, 12)), UNCHANGED, self.PAUSES)
        self.assertEqual(problems, [])
        self.assertIn("mid-word", operations[0].notes[0])


class TestHumanEditsWin(unittest.TestCase):
    LAST_KNOWN = ir((0, 4), (6, 10), (12, 15))
    CURRENT = ir((0, 4), (12, 15), (16, 18))          # human deleted 6-10, added 16-18

    def setUp(self):
        self.changes = reconcile(self.LAST_KNOWN, self.CURRENT)

    def test_restoring_what_the_creator_removed_is_refused(self):
        problems = check(op("restore", 6, 10), self.CURRENT, self.changes)
        self.assertIn("took out 6.00-10.00s themselves", problems[0])

    def test_removing_what_the_creator_put_back_is_refused(self):
        problems = check(op("remove", 16, 18), self.CURRENT, self.changes)
        self.assertIn("put back 16.00-18.00s themselves", problems[0])

    def test_an_explicit_request_can_override_with_a_reason(self):
        doc = op("restore", 6, 10, override_human_edit="asked to put back the part about pricing")
        result = run(self.CURRENT, doc, self.changes)
        self.assertIn((6, 10), spans(result))

    def test_an_edit_next_to_the_creators_is_not_an_undo(self):
        """Removing 12-13 touches only material the creator left alone."""
        self.assertEqual(check(op("remove", 12, 13), self.CURRENT, self.changes), [])

    def test_placement_nudging_through_silence_is_not_an_undo(self):
        """Asked for 4.5-6.0s, which stops where the creator's cut begins. Placement
        lands the end 50ms inside that cut - in a pause, so it is silence, not a
        reversal of what they did. The guard checks the requested span."""
        pauses = {source_key(SOURCE): [{"start": 5.8, "end": 6.6}]}
        operations, problems = resolve(op("restore", 4.5, 6.0), self.CURRENT, self.changes, pauses)
        self.assertEqual(problems, [])
        self.assertGreater(operations[0].end, 6.0)

    def test_removing_more_is_never_an_undo(self):
        """Extending the creator's own cut does not reverse it."""
        self.assertEqual(check(op("remove", 3, 4), self.CURRENT, self.changes), [])

    def test_the_creators_split_survives_an_unrelated_change(self):
        """A real Shotcut edit: the creator deleted the intro and split the last clip."""
        if not HUMAN_EDITED.exists():
            self.skipTest("fixture not present")
        current = parse_mlt(HUMAN_EDITED)
        changes = reconcile(read_sidecar(HUMAN_EDITED), current)
        source = current["tracks"][0]["clips"][0]["source"]
        result = run(current, {"summary": "test", "operations": [{
            "action": "remove", "start": 8.0, "end": 9.0, "reason": "test",
            "source": Path(source).name}]}, changes)
        self.assertEqual([(c["source_in"], c["source_out"]) for c in result["tracks"][0]["clips"]],
                         [(7.0, 8.0), (9.0, 18.0), (20.5, 23.6), (23.6, 25.7)])


class TestSources(unittest.TestCase):
    def two_recordings(self):
        project = ir((0, 4))
        project["tracks"][0]["clips"].append({
            "id": "clip2", "source": "C:/media/other.mp4", "source_in": 0.0, "source_out": 2.0,
            "timeline_start": 4.0, "timeline_duration": 2.0})
        return project

    def test_two_recordings_need_a_source(self):
        self.assertIn('name one in "source"', check(op("remove", 1, 2), self.two_recordings(),
                                                    UNCHANGED)[0])

    def test_an_unknown_recording_is_reported(self):
        problems = check(op("remove", 1, 2, source="nope.mp4"), self.two_recordings(), UNCHANGED)
        self.assertIn("not a recording on the main track", problems[0])

    def test_naming_the_recording_by_file_name_works(self):
        result = run(self.two_recordings(), op("remove", 0.5, 1.5, source="other.mp4"))
        self.assertEqual(spans(result)[-2:], [(0, 0.5), (1.5, 2)])

    def test_the_schema_rejects_an_unknown_action(self):
        self.assertIn("schema", check(op("move", 1, 2), ir((0, 4)), UNCHANGED)[0])

    def test_no_operations_is_a_valid_answer(self):
        """"Nothing to change" has to be sayable, or an editor is forced to invent a change."""
        self.assertEqual(check({"summary": "already as tight as it can be", "operations": []},
                               ir((0, 4)), UNCHANGED), [])

    def test_a_summary_is_required(self):
        self.assertIn("summary", check({"operations": []}, ir((0, 4)), UNCHANGED)[0])

    def test_nothing_is_changed_in_place(self):
        base = ir((0, 4), (6, 10))
        before = copy.deepcopy(base)
        run(base, op("remove", 1, 2))
        self.assertEqual(base, before)


class TestGraphics(unittest.TestCase):
    BASE = ir((0, 4), (6, 10))          # 0-4s of the recording, then 6-10s from 4s on the timeline

    def graphic(self, at, duration=2.0, **extra):
        return {"at": at, "duration": duration, "reason": "test", "text": "Hello", **extra}

    def test_a_graphic_appears_where_its_moment_plays(self):
        project = copy.deepcopy(self.BASE)
        self.assertEqual(add_graphics(project, [self.graphic(7.0)]), [])
        track = project["tracks"][-1]
        self.assertEqual((track["id"], track["type"]), ("Graphics", "graphics"))
        self.assertEqual(track["clips"], [{"id": "clip1", "timeline_start": 5.0, "timeline_duration": 2.0,
                                           "generator": "hyperframes", "text": "Hello"}])
        validate(project, "ir")

    def test_a_moment_that_was_cut_is_reported(self):
        project = copy.deepcopy(self.BASE)
        self.assertIn("not in the cut", add_graphics(project, [self.graphic(5.0)])[0])
        self.assertEqual(len(project["tracks"]), 1)     # no empty Graphics track left behind

    def test_overlapping_graphics_are_reported(self):
        project = copy.deepcopy(self.BASE)
        problems = add_graphics(project, [self.graphic(1.0), self.graphic(2.0)])
        self.assertIn("overlap", problems[0])

    def test_graphics_land_after_the_operations(self):
        """Removing 1-3s pulls a graphic at 3.5s of the recording to 1.5s on the timeline."""
        doc = op("remove", 1, 3)
        doc["graphics"] = [self.graphic(3.5, duration=1.0)]
        self.assertEqual(check(doc, self.BASE, UNCHANGED), [])
        result = run(self.BASE, doc)
        add_graphics(result, doc["graphics"])
        self.assertAlmostEqual(result["tracks"][-1]["clips"][0]["timeline_start"], 1.5, places=1)

    def test_a_product_card_or_lower_third_keeps_its_lines(self):
        project = copy.deepcopy(self.BASE)
        card = self.graphic(7.0, kind="product", subtitle="Packs into its own pocket", price="$129")
        validate({"summary": "s", "operations": [], "graphics": [card]}, "operations")
        self.assertEqual(add_graphics(project, [card]), [])
        clip = project["tracks"][-1]["clips"][0]
        self.assertEqual((clip["text"], clip["generator_params"]), (
            "Hello", {"layout": "product", "subtitle": "Packs into its own pocket", "price": "$129"}))
        validate(project, "ir")

    def test_a_graphic_needs_text_or_a_composition(self):
        bare = {"at": 1.0, "duration": 1.0, "reason": "test"}
        self.assertIn("text, or a composition", add_graphics(copy.deepcopy(self.BASE), [bare])[0])

    def test_b_roll_comes_in_where_its_moment_plays(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "jacket.png"
            image.write_bytes(b"png")
            entry = {"path": str(image), "at": 7.0, "duration": 2.0, "reason": "test"}
            validate({"summary": "s", "operations": [], "broll": [entry]}, "operations")
            project = copy.deepcopy(self.BASE)
            self.assertEqual(add_broll(project, [entry]), [])
            self.assertIn("not in the cut", add_broll(copy.deepcopy(self.BASE), [dict(entry, at=5.0)])[0])
        track = project["tracks"][1]
        self.assertEqual((track["id"], track["type"]), ("B-roll", "broll"))
        self.assertEqual(track["clips"][0]["timeline_start"], 5.0)


class TestMovingWithTheCut(unittest.TestCase):
    """Graphics and B-roll go where their moment of the recording plays after an edit."""

    def test_what_follows_a_removed_span_moves_up_and_what_was_in_it_goes(self):
        before = ir((0, 10))
        before["tracks"] += [
            {"id": "Graphics", "type": "graphics", "clips": [
                {"id": "clip1", "timeline_start": 1.5, "timeline_duration": 1.0, "generator": "hyperframes",
                 "text": "Gone"},
                {"id": "clip2", "timeline_start": 4.0, "timeline_duration": 2.0, "generator": "hyperframes",
                 "text": "Moved", "source": "C:/g/a.mov", "source_in": 0.0, "source_out": 2.0}]},
            {"id": "B-roll", "type": "broll", "clips": [
                {"id": "clip1", "source": "C:/media/street.mp4", "source_in": 0.0, "source_out": 2.0,
                 "timeline_start": 7.5, "timeline_duration": 2.0}]}]
        after = run(before, op("remove", 1, 3))
        self.assertEqual(move_with_cut(before, after), {"moved": 2, "removed": 1})
        graphics, b_roll = after["tracks"][1]["clips"], after["tracks"][2]["clips"]
        self.assertEqual([(c["text"], c["timeline_start"]) for c in graphics], [("Moved", 2.0)])
        self.assertEqual(b_roll[0]["timeline_start"], 5.5)
        validate(after, "ir")

    def test_one_whose_start_was_cut_starts_where_the_cut_is_now(self):
        before = ir((0, 10))
        before["tracks"].append({"id": "B-roll", "type": "broll", "clips": [
            {"id": "clip1", "source": "C:/media/street.mp4", "source_in": 0.0, "source_out": 2.0,
             "timeline_start": 2.0, "timeline_duration": 2.0}]})
        after = run(before, op("remove", 1, 3))
        move_with_cut(before, after)
        self.assertEqual((after["tracks"][1]["clips"][0]["timeline_start"],
                          after["tracks"][1]["clips"][0]["timeline_duration"]), (1.0, 2.0))

    def test_b_roll_keeps_its_length_until_the_next_clip_or_the_end(self):
        before = ir((0, 10))
        before["tracks"].append({"id": "B-roll", "type": "broll", "clips": [
            {"id": f"clip{n}", "source": "C:/media/street.mp4", "source_in": 0.0, "source_out": d,
             "timeline_start": t, "timeline_duration": d} for n, (t, d) in enumerate([(3.5, 2.5), (6.0, 2.0),
                                                                                       (8.0, 2.0)], start=1)]})
        doc = {"summary": "test", "operations": [
            {"action": "remove", "start": 4, "end": 5.5, "reason": "test"},
            {"action": "remove", "start": 9, "end": 10, "reason": "test"}]}
        after = run(before, doc)                            # the cut is now 7.5 s long
        move_with_cut(before, after)
        self.assertEqual([(c["timeline_start"], c["timeline_duration"], c["source_out"])
                          for c in after["tracks"][1]["clips"]],
                         [(3.5, 1.0, 1.0),                  # cut short where the next one now starts
                          (4.5, 2.0, 2.0), (6.5, 1.0, 1.0)])  # and where the video now ends
        validate(after, "ir")


if __name__ == "__main__":
    unittest.main()
