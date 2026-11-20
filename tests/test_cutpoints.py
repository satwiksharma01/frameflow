#!/usr/bin/env python3
"""Tests for cut-point snapping and join verification logic.

Both are the automated form of checks done by hand on a real recording, so the
cases here are the ones that actually went wrong there.

Run with: python -m unittest discover tests
"""
import unittest

from project import cutpoints
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


WORDS = [{"start": 1.0, "end": 1.3, "text": " Hello"}, {"start": 1.5, "end": 1.9, "text": " there."},
         {"start": 2.6, "end": 2.7, "text": " The"}, {"start": 2.7, "end": 3.0, "text": " goal"},
         {"start": 3.0, "end": 3.2, "text": " is"}, {"start": 10.0, "end": 10.1, "text": " the"},
         {"start": 10.1, "end": 10.4, "text": " goal"}]
PAUSES = [{"start": 0.0, "end": 1.0}, {"start": 1.9, "end": 2.6}, {"start": 3.2, "end": 3.9},
          {"start": 9.4, "end": 10.0}, {"start": 10.4, "end": 11.0}]


class TestSpanOf(unittest.TestCase):
    """Where words a creator types are said in their recording, cut in the pauses around them."""

    def test_a_phrase_is_cut_in_the_pauses_around_it(self):
        start, end = cutpoints.span_of(WORDS, PAUSES, "The goal, is", 30)
        self.assertTrue(2.3 <= start <= 2.4, start)          # breathing in, a quarter second before "The"
        self.assertTrue(3.4 <= end <= 3.5, end)              # a quarter second after "is"

    def test_case_and_punctuation_are_ignored(self):
        self.assertEqual(cutpoints.span_of(WORDS, PAUSES, "the GOAL is!", 30),
                         cutpoints.span_of(WORDS, PAUSES, "The goal, is", 30))

    def test_of_two_places_the_one_nearest_the_scene_wins(self):
        self.assertTrue(2.3 <= cutpoints.span_of(WORDS, PAUSES, "the goal", 30)[0] <= 2.4)
        start, end = cutpoints.span_of(WORDS, PAUSES, "the goal", 30, near=9.0)
        self.assertTrue(9.7 <= start <= 9.8 and 10.6 <= end <= 10.7, (start, end))

    def test_words_not_said_give_none(self):
        self.assertIsNone(cutpoints.span_of(WORDS, PAUSES, "goodbye", 30))
        self.assertIsNone(cutpoints.span_of(WORDS, PAUSES, "goal the", 30))      # said, but not in that order

    def test_a_phrase_with_nothing_to_search_for_is_refused_not_found_everywhere(self):
        for phrase in ("", "  ...  ", "\u0928\u092e\u0938\u094d\u0924\u0947"):        # the last is Hindi
            with self.assertRaises(ValueError):
                cutpoints.span_of(WORDS, PAUSES, phrase, 30)

    def test_without_a_pause_the_cut_falls_between_the_words(self):
        start, end = cutpoints.span_of(WORDS, [], "goal", 30)
        self.assertAlmostEqual(start, 2.7, places=1)          # "The" ends where "goal" begins
        self.assertAlmostEqual(end, 3.0, places=1)

    def test_the_end_of_a_recording_caps_the_last_words(self):
        self.assertAlmostEqual(cutpoints.span_of(WORDS, [], "the goal", 30, near=9.0, length=10.5)[1], 10.5, places=1)


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


class TestKeptPieces(unittest.TestCase):
    """The stretches of a scene that play once its long pauses are cut, at 20 fps so quarter-seconds fall on frames."""

    def test_a_span_with_no_long_pause_is_one_piece(self):
        self.assertEqual(cutpoints.kept_pieces(1.0, 7.0, [{"start": 3.0, "end": 3.6}], 20), [(1.0, 7.0)])

    def test_a_long_pause_inside_is_cut_to_the_breath_either_side(self):
        self.assertEqual(cutpoints.kept_pieces(1.0, 7.0, [{"start": 3.0, "end": 5.0}], 20), [(1.0, 3.25), (4.75, 7.0)])

    def test_a_pause_over_the_span_s_edge_is_left_to_the_span(self):
        self.assertEqual(cutpoints.kept_pieces(1.0, 7.0, [{"start": 0.5, "end": 2.0}, {"start": 6.0, "end": 8.0}], 20),
                         [(1.0, 7.0)])

    def test_two_long_pauses_a_word_apart_keep_the_word(self):
        pieces = cutpoints.kept_pieces(0.0, 6.0, [{"start": 1.0, "end": 2.5}, {"start": 2.8, "end": 4.0}], 20)
        self.assertEqual(pieces, [(0.0, 1.25), (2.25, 3.05), (3.75, 6.0)])
        self.assertTrue(all(b > a for a, b in pieces), pieces)


class TestTrimEdges(unittest.TestCase):
    """A long pause at a scene's edge is cut where a cut inside the scene would stop or resume, at 20 fps."""

    def test_a_span_starting_inside_a_long_pause_starts_a_breath_before_the_words(self):
        self.assertEqual(cutpoints.trim_edges(2.0, 7.0, [{"start": 1.0, "end": 3.0}], 20), (2.75, 7.0))

    def test_a_span_ending_inside_a_long_pause_ends_a_breath_after_the_words(self):
        self.assertEqual(cutpoints.trim_edges(1.0, 6.5, [{"start": 6.0, "end": 8.0}], 20), (1.0, 6.25))

    def test_a_span_with_a_long_pause_at_both_edges_is_trimmed_at_both(self):
        pauses = [{"start": 1.0, "end": 3.0}, {"start": 6.0, "end": 8.0}]
        self.assertEqual(cutpoints.trim_edges(2.0, 6.5, pauses, 20), (2.75, 6.25))

    def test_a_short_pause_at_an_edge_is_left_as_it_is(self):
        pauses = [{"start": 1.8, "end": 2.4}, {"start": 6.8, "end": 7.3}]
        self.assertEqual(cutpoints.trim_edges(2.0, 7.0, pauses, 20), (2.0, 7.0))

    def test_a_span_inside_one_long_pause_is_never_emptied(self):
        for start, end in [(1.5, 2.5), (1.1, 1.2), (2.8, 2.9)]:
            a, b = cutpoints.trim_edges(start, end, [{"start": 1.0, "end": 3.0}], 20)
            self.assertLess(a, b, (start, end))


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
        before, after = words_at_boundary(lambda clip: self.WORDS, {"source_in": 0.9, "source_out": 1.9},
                                          {"source_in": 4.0, "source_out": 4.7})
        self.assertEqual((before, after), ("cut", "Claude"))

    def test_each_side_s_word_is_from_its_own_clip_s_recording(self):
        # Cut from one recording to another: the same source seconds say different words in each.
        said = {"talk.mp4": self.WORDS, "demo.mp4": [{"start": 4.0, "end": 4.4, "text": "Next"}]}
        before, after = words_at_boundary(lambda clip: said[clip["source"]],
                                          {"source": "talk.mp4", "source_in": 0.9, "source_out": 1.9},
                                          {"source": "demo.mp4", "source_in": 4.0, "source_out": 4.7})
        self.assertEqual((before, after), ("cut", "Next"))

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
        before, after = words_at_boundary(lambda clip: words, {"source_in": 121.37, "source_out": 122.20},
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
