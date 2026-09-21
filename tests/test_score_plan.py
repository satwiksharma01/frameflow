#!/usr/bin/env python3
"""Tests for the edit-plan scorer, and for the golden fixture it scores against.

The fixture tests matter as much as the scorer tests: a reference plan that
drifted out of agreement with its own transcript would quietly redefine "good"
and every score taken afterwards would be measuring the wrong thing.
"""
import json
import unittest
from pathlib import Path

from project.score_plan import (
    BOUNDARY_TOLERANCE_SECONDS,
    format_report,
    interior_boundaries,
    load_pauses,
    score,
)
from project.validate import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"
REFERENCE = EXAMPLES / "synthetic-talk.reference-plan.json"
TRANSCRIPT = EXAMPLES / "synthetic-talk.transcript.json"

DURATION = 34.8


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _plan(*spans: tuple[str, float, float]) -> dict:
    return {
        "source_duration_seconds": DURATION,
        "decisions": [{"action": a, "start": s, "end": e, "reason": "test"} for a, s, e in spans],
    }


class TestGoldenFixture(unittest.TestCase):
    """The committed reference plan is the project's definition of a good edit."""

    def test_reference_plan_is_a_valid_edit_plan(self):
        validate(_load(REFERENCE), "edit_plan")

    def test_transcript_fixture_is_valid(self):
        validate(_load(TRANSCRIPT), "transcript")

    def test_transcript_carries_no_absolute_path(self):
        # A fixture that embeds one machine's layout is exactly what is keeping
        # the repository private; a new one must not add to that.
        source = _load(TRANSCRIPT)["source"]
        self.assertFalse(Path(source).is_absolute(), f"fixture source is absolute: {source}")
        self.assertNotIn(":", source)

    def test_every_reference_cut_point_sits_in_a_measured_silence(self):
        result = score(_load(REFERENCE), _load(REFERENCE), load_pauses(TRANSCRIPT))
        self.assertEqual(result["placement"]["cut_points_outside_a_pause"], 0,
                         f"reference places cuts outside measured silence: "
                         f"{result['placement']['where']}")

    def test_scoring_the_reference_against_itself_is_perfect(self):
        result = score(_load(REFERENCE), _load(REFERENCE))
        self.assertEqual(result["agreement"], {"precision": 1.0, "recall": 1.0, "f1": 1.0})
        self.assertEqual(result["boundaries"]["matched_within_tolerance"],
                         result["boundaries"]["reference"])
        self.assertEqual(result["boundaries"]["max_distance_seconds"], 0.0)


class TestInteriorBoundaries(unittest.TestCase):
    def test_recording_edges_are_not_cut_points(self):
        plan = _plan(("keep", 0.0, 10.0), ("remove", 10.0, DURATION))
        self.assertEqual(interior_boundaries(plan), [10.0])

    def test_a_single_span_has_no_cut_points(self):
        self.assertEqual(interior_boundaries(_plan(("keep", 0.0, DURATION))), [])


class TestAgreement(unittest.TestCase):
    """Precision and recall fail in opposite directions; both are reported."""

    def setUp(self):
        self.reference = _plan(("keep", 0.0, 10.0), ("remove", 10.0, 20.0),
                               ("keep", 20.0, DURATION))

    def test_keeping_everything_has_full_recall_and_poor_precision(self):
        result = score(_plan(("keep", 0.0, DURATION)), self.reference)
        self.assertEqual(result["agreement"]["recall"], 1.0)
        self.assertLess(result["agreement"]["precision"], 1.0)

    def test_cutting_too_much_has_full_precision_and_poor_recall(self):
        over = _plan(("keep", 0.0, 10.0), ("remove", 10.0, DURATION))
        result = score(over, self.reference)
        self.assertEqual(result["agreement"]["precision"], 1.0)
        self.assertLess(result["agreement"]["recall"], 1.0)

    def test_cutting_the_wrong_half_scores_zero(self):
        inverted = _plan(("remove", 0.0, 10.0), ("keep", 10.0, 20.0), ("remove", 20.0, DURATION))
        result = score(inverted, self.reference)
        self.assertEqual(result["agreement"]["f1"], 0.0)

    def test_a_plan_that_keeps_nothing_scores_zero_rather_than_dividing_by_zero(self):
        result = score(_plan(("remove", 0.0, DURATION)), self.reference)
        self.assertEqual(result["agreement"], {"precision": 0.0, "recall": 0.0, "f1": 0.0})


class TestBoundaryAccuracy(unittest.TestCase):
    """Two plans can agree on every editorial call and still cut in the wrong place."""

    def setUp(self):
        self.reference = _plan(("keep", 0.0, 10.0), ("remove", 10.0, 20.0),
                               ("keep", 20.0, DURATION))

    def test_drifted_boundaries_are_measured_not_hidden_by_high_agreement(self):
        drifted = _plan(("keep", 0.0, 10.4), ("remove", 10.4, 20.4), ("keep", 20.4, DURATION))
        result = score(drifted, self.reference)
        self.assertGreater(result["agreement"]["f1"], 0.95)
        self.assertEqual(result["boundaries"]["matched_within_tolerance"], 0)
        self.assertAlmostEqual(result["boundaries"]["max_distance_seconds"], 0.4, places=3)

    def test_drift_inside_the_tolerance_still_counts_as_the_same_cut(self):
        nudged = _plan(("keep", 0.0, 10.05), ("remove", 10.05, 20.0), ("keep", 20.0, DURATION))
        result = score(nudged, self.reference)
        self.assertEqual(result["boundaries"]["matched_within_tolerance"], 2)

    def test_a_missing_cut_point_is_not_silently_matched_to_a_distant_one(self):
        result = score(_plan(("keep", 0.0, DURATION)), self.reference)
        self.assertEqual(result["boundaries"]["generated"], 0)
        self.assertEqual(result["boundaries"]["matched_within_tolerance"], 0)
        self.assertIsNone(result["boundaries"]["median_distance_seconds"])


class TestPlacement(unittest.TestCase):
    """After snapping, every cut point should sit inside a measured pause."""

    def setUp(self):
        self.reference = _plan(("keep", 0.0, 10.0), ("remove", 10.0, DURATION))
        self.pauses = [{"start": 9.5, "end": 10.5}]

    def test_a_cut_inside_a_pause_passes(self):
        result = score(self.reference, self.reference, self.pauses)
        self.assertEqual(result["placement"]["cut_points_outside_a_pause"], 0)

    def test_a_cut_outside_every_pause_is_reported_with_its_timestamp(self):
        stray = _plan(("keep", 0.0, 15.0), ("remove", 15.0, DURATION))
        result = score(stray, self.reference, self.pauses)
        self.assertEqual(result["placement"]["cut_points_outside_a_pause"], 1)
        self.assertEqual(result["placement"]["where"], [15.0])

    def test_placement_is_omitted_when_no_pauses_are_supplied(self):
        self.assertNotIn("placement", score(self.reference, self.reference))


class TestLoadPauses(unittest.TestCase):
    def test_reads_a_transcript_silences_list(self):
        self.assertEqual(len(load_pauses(TRANSCRIPT)), len(_load(TRANSCRIPT)["silences"]))

    def test_prefers_a_timing_maps_fine_pauses(self):
        path = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "timing.json"
        path.write_text(json.dumps({"words": [], "pauses": [{"start": 1.0, "end": 1.2}]}),
                        encoding="utf-8")
        self.assertEqual(load_pauses(path), [{"start": 1.0, "end": 1.2}])

    def test_a_file_with_neither_is_an_error(self):
        path = Path(self.enterContext(__import__("tempfile").TemporaryDirectory())) / "other.json"
        path.write_text(json.dumps({"segments": []}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_pauses(path)


class TestReport(unittest.TestCase):
    def test_vacuous_placement_is_not_reported_as_success(self):
        # A plan with no cut points trivially has none outside a pause; saying
        # "every cut point sits inside a measured pause" would read as a pass.
        reference = _plan(("keep", 0.0, 10.0), ("remove", 10.0, DURATION))
        report = format_report(score(_plan(("keep", 0.0, DURATION)), reference, [{"start": 9.5, "end": 10.5}]))
        self.assertIn("no cut points to place", report)

    def test_report_names_where_a_stray_cut_landed(self):
        reference = _plan(("keep", 0.0, 10.0), ("remove", 10.0, DURATION))
        stray = _plan(("keep", 0.0, 15.0), ("remove", 15.0, DURATION))
        report = format_report(score(stray, reference, [{"start": 9.5, "end": 10.5}]))
        self.assertIn("15.0", report)


class TestTolerance(unittest.TestCase):
    def test_default_tolerance_is_tighter_than_the_padding_a_snap_adds(self):
        # PAD_SECONDS is 0.25: a padded boundary and an unpadded one are
        # different cuts and must not be scored as the same one.
        from project.cutpoints import PAD_SECONDS
        self.assertLess(BOUNDARY_TOLERANCE_SECONDS, PAD_SECONDS)


if __name__ == "__main__":
    unittest.main()
