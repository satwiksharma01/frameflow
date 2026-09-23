#!/usr/bin/env python3
"""Tests for operations: changes to a project the creator already has.

Run with: python -m unittest discover tests
"""
import copy
import unittest
from pathlib import Path

from project.cutpoints import PAD_SECONDS, frame_align
from project.operations import apply, check, resolve
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
    return {"operations": [{"action": action, "start": start, "end": end, "reason": "test", **extra}]}


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
        result = run(current, {"operations": [{
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

    def test_nothing_is_changed_in_place(self):
        base = ir((0, 4), (6, 10))
        before = copy.deepcopy(base)
        run(base, op("remove", 1, 2))
        self.assertEqual(base, before)


if __name__ == "__main__":
    unittest.main()
