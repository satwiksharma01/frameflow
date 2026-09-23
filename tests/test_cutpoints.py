#!/usr/bin/env python3
"""Tests for cut-point snapping and join verification logic.

Both are the automated form of checks done by hand on a real recording, so the
cases here are the ones that actually went wrong there.

Run with: python -m unittest discover tests
"""
import unittest

from project.cutpoints import PAD_SECONDS, find_pause, frame_align, snap_plan
from project.verify_cuts import tokenize, word_survived, words_at_boundary

FPS = 30.0
FRAME = 1 / FPS


def plan(*boundaries, duration=30.0):
    """A keep/remove/keep... plan from a list of internal boundaries."""
    edges = [0.0, *boundaries, duration]
    actions = ["keep" if i % 2 == 0 else "remove" for i in range(len(edges) - 1)]
    return {
        "source_duration_seconds": duration,
        "decisions": [
            {"action": a, "start": s, "end": e, "reason": "test"}
            for a, s, e in zip(actions, edges, edges[1:])
        ],
    }


class TestFindPause(unittest.TestCase):
    PAUSES = [{"start": 2.0, "end": 3.0}, {"start": 10.0, "end": 10.2}, {"start": 20.0, "end": 22.0}]

    def test_a_pause_containing_the_boundary_wins(self):
        self.assertEqual(find_pause(self.PAUSES, 2.5), self.PAUSES[0])

    def test_nearest_pause_within_the_window(self):
        self.assertEqual(find_pause(self.PAUSES, 10.4), self.PAUSES[1])

    def test_nothing_within_the_window(self):
        self.assertIsNone(find_pause(self.PAUSES, 15.0))

    def test_ties_prefer_the_longer_pause(self):
        pauses = [{"start": 4.9, "end": 5.0}, {"start": 5.5, "end": 6.5}]
        self.assertEqual(find_pause(pauses, 5.25, window=1.0), pauses[1])


class TestSnapPlan(unittest.TestCase):
    def test_boundary_moves_into_the_pause_and_lands_on_a_frame(self):
        snapped, notes = snap_plan(plan(5.0), [{"start": 5.4, "end": 6.4}], FPS)
        boundary = snapped["decisions"][0]["end"]
        self.assertAlmostEqual(boundary, frame_align(5.4 + PAD_SECONDS, FPS), places=6)
        self.assertEqual(boundary * FPS, round(boundary * FPS))          # on a frame
        self.assertEqual(snapped["decisions"][1]["start"], boundary)      # stays contiguous
        self.assertEqual([n.status for n in notes], ["snapped"])

    def test_keep_side_gets_the_padding_before_a_removal(self):
        snapped, _ = snap_plan(plan(5.0), [{"start": 4.8, "end": 6.8}], FPS)
        # Cut belongs just after the kept speech stops, not in the middle.
        self.assertAlmostEqual(snapped["decisions"][0]["end"], frame_align(5.05, FPS), places=6)

    def test_kept_speech_after_a_removal_gets_padding_too(self):
        # remove -> keep boundary: the cut should sit near the end of the pause.
        p = plan(5.0, 12.0)
        snapped, _ = snap_plan(p, [{"start": 10.0, "end": 12.6}], FPS)
        self.assertAlmostEqual(snapped["decisions"][1]["end"], frame_align(12.6 - PAD_SECONDS, FPS),
                               places=6)

    def test_no_pause_nearby_is_reported_and_left_alone(self):
        snapped, notes = snap_plan(plan(5.0), [{"start": 20.0, "end": 21.0}], FPS)
        self.assertEqual(snapped["decisions"][0]["end"], 5.0)
        self.assertEqual(notes[0].status, "no-pause")
        self.assertIn("mid-word", notes[0].detail)

    def test_the_gap_that_defeated_run_3_is_flagged_as_unsafe(self):
        # 80ms between "cut" and "ac-tually" is 2.4 frames at 30fps. Cutting there
        # produced "decided to contact Claude"; nothing frame-aligned works.
        snapped, notes = snap_plan(plan(5.0), [{"start": 5.0, "end": 5.08}], FPS)
        self.assertEqual(notes[0].status, "tight")
        self.assertIn("no safe cut point", notes[0].detail)
        self.assertGreater(snapped["decisions"][0]["end"], 0)

    def test_the_same_gap_is_fine_at_60fps(self):
        # Frame rate is an editability decision: 80ms is 4.8 frames at 60fps.
        _, notes = snap_plan(plan(5.0), [{"start": 5.0, "end": 5.08}], 60.0)
        self.assertNotIn("tight", [n.status for n in notes])

    def test_cut_stays_at_least_a_frame_inside_the_pause(self):
        snapped, _ = snap_plan(plan(5.0), [{"start": 4.99, "end": 5.30}], FPS)
        boundary = snapped["decisions"][0]["end"]
        self.assertGreaterEqual(boundary, 4.99 + FRAME - 1e-9)
        self.assertLessEqual(boundary, 5.30 - FRAME + 1e-9)

    def test_snapping_never_collapses_a_neighbouring_span(self):
        p = plan(5.0, 5.4)
        snapped, notes = snap_plan(p, [{"start": 5.3, "end": 9.0}], FPS)
        for d in snapped["decisions"]:
            self.assertGreater(d["end"] - d["start"], 0)
        self.assertTrue(all(a["end"] == b["start"] for a, b in
                            zip(snapped["decisions"], snapped["decisions"][1:])))

    def test_snapping_keeps_a_low_confidence_flag(self):
        """Snapping rewrites boundaries; it must not drop the editor's doubt.

        Losing the flag here would hide exactly the decisions the creator was
        told to review, and nothing downstream would notice.
        """
        p = plan(5.0)
        p["decisions"][1]["confidence"] = "low"
        snapped, _ = snap_plan(p, [{"start": 5.4, "end": 6.4}], FPS)
        self.assertEqual(snapped["decisions"][1]["confidence"], "low")

    def test_plan_stays_contiguous_and_covers_the_source(self):
        snapped, _ = snap_plan(plan(5.0, 12.0, 20.0),
                               [{"start": 5.2, "end": 6.0}, {"start": 11.5, "end": 12.5},
                                {"start": 19.0, "end": 21.0}], FPS)
        decisions = snapped["decisions"]
        self.assertEqual(decisions[0]["start"], 0.0)
        self.assertEqual(decisions[-1]["end"], 30.0)
        for a, b in zip(decisions, decisions[1:]):
            self.assertEqual(a["end"], b["start"])


class TestJoinVerification(unittest.TestCase):
    WORDS = [
        {"start": 1.0, "end": 1.4, "text": "decided"},
        {"start": 1.4, "end": 1.6, "text": "to"},
        {"start": 1.6, "end": 1.9, "text": "cut"},
        {"start": 4.0, "end": 4.3, "text": "Claude"},
        {"start": 4.3, "end": 4.7, "text": "has"},
    ]

    def test_boundary_words_are_the_ones_either_side_of_the_cut(self):
        before, after = words_at_boundary(self.WORDS, {"source_in": 0.9, "source_out": 1.9},
                                          {"source_in": 4.0, "source_out": 4.7})
        self.assertEqual((before, after), ("cut", "Claude"))

    def test_a_word_inside_the_removed_span_is_not_expected(self):
        """The false positive from the first real verification run.

        Whisper stretched one word across three seconds, so proximity alone
        picked a word that had been deliberately cut, and the verifier demanded
        to hear it. A boundary word has to sit inside its own clip.
        """
        words = [
            {"start": 122.00, "end": 122.24, "text": "better"},
            {"start": 122.24, "end": 125.24, "text": "so"},     # drifted; spans the cut
            {"start": 125.24, "end": 126.11, "text": "take"},   # inside the removed span
        ]
        before, after = words_at_boundary(words, {"source_in": 121.37, "source_out": 122.20},
                                          {"source_in": 122.70, "source_out": 123.20})
        self.assertEqual(before, "better")
        self.assertEqual(after, "")  # nothing reliable on that side - check only what we have

    def test_a_surviving_word_is_recognised(self):
        self.assertTrue(word_survived("cut", tokenize("the part that Claude decided to cut")))

    def test_a_swallowed_word_is_caught(self):
        # The real failure: "decided to cut. Claude..." rendered as "decided to go."
        self.assertFalse(word_survived("cut", tokenize("the part that Claude decided to go")))

    def test_whisper_wobble_on_a_name_is_not_reported_as_missing(self):
        self.assertTrue(word_survived("Claude", tokenize("so cloud has analyzed this script")))

    def test_missing_word_entirely_is_caught(self):
        self.assertFalse(word_survived("cut", tokenize("decided to")))


if __name__ == "__main__":
    unittest.main()
