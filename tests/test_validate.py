#!/usr/bin/env python3
"""Validation tests. Run with: python -m unittest discover tests"""
import copy
import unittest

from project.validate import ValidationError, validate

VALID_IR = {
    "schema_version": "0.2.0",
    "project": {
        "name": "test",
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "source_frame_rate_mode": "cfr",
    },
    "tracks": [
        {
            "id": "video-main",
            "type": "video",
            "clips": [
                {
                    "id": "clip1",
                    "source": "C:/media/example.mp4",
                    "source_in": 0.0,
                    "source_out": 4.5,
                    "timeline_start": 0.0,
                    "timeline_duration": 4.5,
                },
                {
                    "id": "clip2",
                    "source": "C:/media/example.mp4",
                    "source_in": 7.0,
                    "source_out": 18.0,
                    "timeline_start": 4.5,
                    "timeline_duration": 11.0,
                },
            ],
        }
    ],
}

VALID_EDIT_PLAN = {
    "source_duration_seconds": 25.7,
    "decisions": [
        {"action": "keep", "start": 0.0, "end": 4.5, "reason": "hook"},
        {"action": "remove", "start": 4.5, "end": 7.0, "reason": "dead air"},
        {"action": "keep", "start": 7.0, "end": 25.7, "reason": "main content"},
    ],
}


class TestIRSchema(unittest.TestCase):
    def test_valid_ir_passes(self):
        validate(VALID_IR, "ir")

    def test_missing_required_field_fails(self):
        ir = copy.deepcopy(VALID_IR)
        del ir["project"]["fps"]
        with self.assertRaises(ValidationError) as ctx:
            validate(ir, "ir")
        self.assertIn("fps", str(ctx.exception))

    def test_invalid_track_type_enum_fails(self):
        ir = copy.deepcopy(VALID_IR)
        ir["tracks"][0]["type"] = "subtitles"
        with self.assertRaises(ValidationError):
            validate(ir, "ir")

    def test_missing_frame_rate_mode_fails(self):
        """The whole point of the VFR finding: silence about provenance is an error."""
        ir = copy.deepcopy(VALID_IR)
        del ir["project"]["source_frame_rate_mode"]
        with self.assertRaises(ValidationError):
            validate(ir, "ir")

    def test_phase0_field_names_are_rejected(self):
        """Migration guard: the old in/out pair must fail loudly, not be ignored."""
        ir = copy.deepcopy(VALID_IR)
        clip = ir["tracks"][0]["clips"][0]
        for field in ("source_in", "source_out", "timeline_start", "timeline_duration"):
            del clip[field]
        clip["in"] = 0.0
        clip["out"] = 4.5
        with self.assertRaises(ValidationError):
            validate(ir, "ir")

    def test_source_in_without_source_out_fails(self):
        ir = copy.deepcopy(VALID_IR)
        del ir["tracks"][0]["clips"][0]["source_out"]
        with self.assertRaises(ValidationError):
            validate(ir, "ir")


class TestIRSemantics(unittest.TestCase):
    def test_inverted_source_range_fails(self):
        ir = copy.deepcopy(VALID_IR)
        clip = ir["tracks"][0]["clips"][0]
        clip["source_in"], clip["source_out"] = 4.5, 1.0
        clip["timeline_duration"] = 3.5
        with self.assertRaises(ValidationError) as ctx:
            validate(ir, "ir")
        self.assertIn("greater than", str(ctx.exception))

    def test_timeline_duration_mismatch_fails(self):
        ir = copy.deepcopy(VALID_IR)
        ir["tracks"][0]["clips"][0]["timeline_duration"] = 9.0
        with self.assertRaises(ValidationError) as ctx:
            validate(ir, "ir")
        self.assertIn("speed changes", str(ctx.exception))

    def test_overlapping_clips_fail(self):
        ir = copy.deepcopy(VALID_IR)
        ir["tracks"][0]["clips"][1]["timeline_start"] = 2.0
        with self.assertRaises(ValidationError) as ctx:
            validate(ir, "ir")
        self.assertIn("may not overlap", str(ctx.exception))

    def test_gap_between_clips_is_allowed(self):
        ir = copy.deepcopy(VALID_IR)
        ir["tracks"][0]["clips"][1]["timeline_start"] = 10.0
        validate(ir, "ir")


class TestEditPlanSchema(unittest.TestCase):
    def test_valid_edit_plan_passes(self):
        validate(VALID_EDIT_PLAN, "edit_plan")

    def test_decision_without_reason_fails(self):
        plan = copy.deepcopy(VALID_EDIT_PLAN)
        del plan["decisions"][0]["reason"]
        with self.assertRaises(ValidationError):
            validate(plan, "edit_plan")

    def test_invalid_action_fails(self):
        plan = copy.deepcopy(VALID_EDIT_PLAN)
        plan["decisions"][0]["action"] = "trim"
        with self.assertRaises(ValidationError):
            validate(plan, "edit_plan")


class TestTranscriptSchema(unittest.TestCase):
    def test_extra_whisper_fields_are_allowed(self):
        """Transcripts come from third-party ASR; unknown fields must not be fatal."""
        transcript = {
            "source": "C:/media/example.mp4",
            "duration_seconds": 25.7,
            "language": "en",
            "segments": [
                {"id": 0, "start": 0.0, "end": 4.5, "text": "hello", "tokens": [1, 2, 3]}
            ],
        }
        validate(transcript, "transcript")

    def test_segment_missing_text_fails(self):
        transcript = {
            "source": "C:/media/example.mp4",
            "duration_seconds": 25.7,
            "segments": [{"start": 0.0, "end": 4.5}],
        }
        with self.assertRaises(ValidationError):
            validate(transcript, "transcript")


if __name__ == "__main__":
    unittest.main()
