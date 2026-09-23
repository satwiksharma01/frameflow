#!/usr/bin/env python3
"""Tests for reconciliation: what did the human change since Frameflow wrote?

Run with: python -m unittest discover tests
"""
import copy
import unittest
from pathlib import Path

from project.parse_mlt import parse_mlt
from project.reconcile import merge_spans, reconcile, subtract_spans
from project.sidecar import read_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
HUMAN_EDITED = REPO_ROOT / "examples" / "human-edited.mlt"
SHOTCUT_SAVED = REPO_ROOT / "examples" / "shotcut-saved-two-track.mlt"
SOURCE = "C:/media/talk.mp4"


def ir(*spans, fps=30):
    """A main track laid end to end from (source_in, source_out) pairs, in order."""
    clips, cursor = [], 0.0
    for n, (start, end) in enumerate(spans, start=1):
        clips.append({"id": f"clip{n}", "source": SOURCE, "source_in": start,
                      "source_out": end, "timeline_start": cursor,
                      "timeline_duration": end - start})
        cursor += end - start
    return {"schema_version": "0.2.0",
            "project": {"name": "t", "width": 1920, "height": 1080, "fps": fps,
                        "source_frame_rate_mode": "cfr"},
            "tracks": [{"id": "V1", "type": "video", "clips": clips}]}


def kinds(changes):
    return [c.kind for c in changes.clips]


class TestSpanArithmetic(unittest.TestCase):
    def test_merge_joins_overlapping_and_touching_spans(self):
        self.assertEqual(merge_spans([(5, 9), (0, 3), (3, 4), (8, 12)]), [(0, 4), (5, 12)])

    def test_subtract_can_split_a_span(self):
        self.assertEqual(subtract_spans([(0, 10)], [(3, 5)]), [(0, 3), (5, 10)])

    def test_subtract_everything_leaves_nothing(self):
        self.assertEqual(subtract_spans([(2, 4)], [(0, 10)]), [])


class TestReconcile(unittest.TestCase):
    def test_no_sidecar_means_changes_are_unknown(self):
        changes = reconcile(None, ir((0, 5)))
        self.assertFalse(changes.known)
        self.assertIn("cannot be told apart", changes.lines()[0])

    def test_frame_rounding_is_not_reported_as_editing(self):
        """The sidecar holds exact seconds, a parsed project frame-rounded ones."""
        exact = ir((0.0, 4.5123), (7.0071, 18.0))
        rounded = ir((0.0, 4.5), (7.0, 18.0))
        self.assertFalse(reconcile(exact, rounded).any)

    def test_a_deleted_clip(self):
        changes = reconcile(ir((0, 4), (6, 10), (12, 15)), ir((0, 4), (12, 15)))
        self.assertEqual(kinds(changes), ["deleted"])
        self.assertEqual(list(changes.removed.values()), [[(6.0, 10.0)]])

    def test_a_deletion_that_ripples_is_not_a_move(self):
        """Every later clip shifts left; none of them moved."""
        changes = reconcile(ir((0, 4), (6, 10), (12, 15), (20, 22)),
                            ir((6, 10), (12, 15), (20, 22)))
        self.assertEqual(kinds(changes), ["deleted"])
        self.assertEqual(changes.unchanged, 3)

    def test_a_trimmed_clip_and_the_sliver_it_lost(self):
        changes = reconcile(ir((0, 4), (6, 10)), ir((0, 4), (6, 9)))
        self.assertEqual(kinds(changes), ["trimmed"])
        self.assertEqual(list(changes.removed.values()), [[(9.0, 10.0)]])

    def test_a_clip_extended_back_into_removed_material_is_a_restore(self):
        changes = reconcile(ir((0, 4), (6, 10)), ir((0, 5), (6, 10)))
        self.assertEqual(kinds(changes), ["trimmed"])
        self.assertEqual(list(changes.restored.values()), [[(4.0, 5.0)]])

    def test_an_added_clip(self):
        changes = reconcile(ir((0, 4), (10, 12)), ir((0, 4), (6, 8), (10, 12)))
        self.assertEqual(kinds(changes), ["added"])
        self.assertEqual(list(changes.restored.values()), [[(6.0, 8.0)]])

    def test_a_split_clip_removes_nothing(self):
        changes = reconcile(ir((0, 10)), ir((0, 4), (4, 10)))
        self.assertEqual(kinds(changes), ["split"])
        self.assertEqual(changes.removed, {})

    def test_two_clips_joined_into_one(self):
        changes = reconcile(ir((0, 4), (4, 10)), ir((0, 10)))
        self.assertEqual(kinds(changes), ["merged"])

    def test_only_the_clip_that_moved_is_reported(self):
        """Moving the last clip to the front reorders everything, but one move explains it."""
        changes = reconcile(ir((0, 2), (3, 5), (6, 8), (9, 11)),
                            ir((9, 11), (0, 2), (3, 5), (6, 8)))
        self.assertEqual(kinds(changes), ["moved"])
        self.assertEqual(changes.clips[0].after, [(9.0, 11.0)])
        self.assertEqual(changes.removed, {})

    def test_overlapping_finds_the_spans_an_edit_would_touch(self):
        changes = reconcile(ir((0, 4), (6, 10), (12, 15)), ir((0, 4), (12, 15)))
        self.assertEqual(changes.overlapping("removed", SOURCE, 7.0, 8.0), [(6.0, 10.0)])
        self.assertEqual(changes.overlapping("removed", SOURCE, 0.5, 3.5), [])

    def test_an_added_track_is_reported(self):
        after = copy.deepcopy(ir((0, 4)))
        after["tracks"].append({"id": "V2", "type": "video", "clips": [
            {"id": "clip1", "source": SOURCE, "source_in": 20.0, "source_out": 22.0,
             "timeline_start": 1.0, "timeline_duration": 2.0}]})
        changes = reconcile(ir((0, 4)), after)
        self.assertIn("0 -> 1", changes.other_tracks)


class TestRealShotcutEdits(unittest.TestCase):
    """Edits a person actually made in Shotcut, not constructed ones."""

    def test_the_committed_human_edit(self):
        if not HUMAN_EDITED.exists():
            self.skipTest("fixture not present")
        changes = reconcile(read_sidecar(HUMAN_EDITED), parse_mlt(HUMAN_EDITED))
        self.assertEqual(kinds(changes), ["deleted", "split"])
        self.assertEqual(changes.clips[0].before, [(0.0, 4.5)])
        self.assertEqual(changes.clips[1].after, [(20.5, 23.6), (23.6, 25.7)])
        self.assertEqual(list(changes.removed.values()), [[(0.0, 4.5)]])
        self.assertEqual(changes.restored, {})
        self.assertEqual(changes.unchanged, 1)

    def test_a_save_with_no_human_edit_reports_nothing(self):
        """Shotcut rewrites the whole file on save; that alone is not an edit."""
        if not SHOTCUT_SAVED.exists():
            self.skipTest("fixture not present")
        changes = reconcile(read_sidecar(SHOTCUT_SAVED), parse_mlt(SHOTCUT_SAVED))
        self.assertTrue(changes.known)
        self.assertFalse(changes.any)


if __name__ == "__main__":
    unittest.main()
