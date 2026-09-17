#!/usr/bin/env python3
"""Round-trip tests for the project bridge: IR -> MLT -> IR.

Round-tripping is only lossless at frame granularity - a timeline is discrete -
so comparisons go through quantize_ir() rather than demanding float equality
the format cannot deliver.

Run with: python -m unittest discover tests
"""
import json
import tempfile
import unittest
from pathlib import Path

from project.parse_mlt import ParseError, parse_mlt, parse_time, quantize_ir
from project.sidecar import merge_sidecar, read_sidecar, sidecar_path, write_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_IR = REPO_ROOT / "examples" / "meet-recording.ir.json"
EXAMPLE_MLT = REPO_ROOT / "examples" / "meet-recording.mlt"
HUMAN_EDITED_MLT = REPO_ROOT / "examples" / "human-edited.mlt"
SHOTCUT_REFERENCE = REPO_ROOT / "phase0" / "shotcut_reference.mlt"
NORMALIZED_MEDIA = REPO_ROOT / "media" / "meet-recording-cfr30.mp4"


class TestParseTime(unittest.TestCase):
    def test_plain_frame_count(self):
        self.assertEqual(parse_time("150", 30), 150)

    def test_timecode_with_milliseconds(self):
        self.assertEqual(parse_time("00:00:05.000", 30), 150)

    def test_timecode_with_frame_field(self):
        self.assertEqual(parse_time("00:00:05:15", 30), 165)

    def test_hours_and_minutes(self):
        self.assertEqual(parse_time("01:02:03.000", 30), (3600 + 120 + 3) * 30)

    def test_empty_is_zero(self):
        self.assertEqual(parse_time(None, 30), 0)
        self.assertEqual(parse_time("", 30), 0)

    def test_unrecognised_format_raises(self):
        with self.assertRaises(ParseError):
            parse_time("1:2:3:4:5", 30)


class TestParseShotcutDialect(unittest.TestCase):
    """Shotcut writes <chain> elements and timecode in/out, not our dialect."""

    def setUp(self):
        if not SHOTCUT_REFERENCE.exists():
            self.skipTest("Shotcut reference project not present")
        self.ir = parse_mlt(SHOTCUT_REFERENCE)

    def test_reads_ntsc_frame_rate_from_profile(self):
        self.assertAlmostEqual(self.ir["project"]["fps"], 30000 / 1001, places=6)

    def test_skips_the_background_track(self):
        self.assertEqual(len(self.ir["tracks"]), 1)
        self.assertEqual(self.ir["tracks"][0]["id"], "V1")

    def test_resolves_chain_resource(self):
        source = self.ir["tracks"][0]["clips"][0]["source"]
        self.assertTrue(source.endswith(".mp4"))

    def test_defaults_provenance_when_property_absent(self):
        self.assertEqual(self.ir["project"]["source_frame_rate_mode"], "cfr")


class TestRoundTrip(unittest.TestCase):
    def test_committed_example_round_trips(self):
        """Parsing the committed .mlt reproduces the committed IR, frame for frame."""
        if not (EXAMPLE_IR.exists() and EXAMPLE_MLT.exists()):
            self.skipTest("example artifacts not present")
        original = json.loads(EXAMPLE_IR.read_text(encoding="utf-8"))
        parsed = parse_mlt(EXAMPLE_MLT)
        self.assertEqual(quantize_ir(original), quantize_ir(parsed))

    def test_track_type_survives_our_own_round_trip(self):
        if not EXAMPLE_MLT.exists():
            self.skipTest("example artifacts not present")
        self.assertEqual(parse_mlt(EXAMPLE_MLT)["tracks"][0]["type"], "video")

    def test_provenance_survives_our_own_round_trip(self):
        if not EXAMPLE_MLT.exists():
            self.skipTest("example artifacts not present")
        self.assertEqual(
            parse_mlt(EXAMPLE_MLT)["project"]["source_frame_rate_mode"],
            "normalized_from_vfr",
        )

    def test_full_compile_then_parse(self):
        """The compile step needs the real media file, which is not committed."""
        if not NORMALIZED_MEDIA.exists():
            self.skipTest("normalized media not present; run project.media --normalize first")
        from project.compile_mlt import compile_file

        original = json.loads(EXAMPLE_IR.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "roundtrip.mlt"
            compile_file(EXAMPLE_IR, out)
            self.assertEqual(quantize_ir(original), quantize_ir(parse_mlt(out)))

    def test_gaps_round_trip_as_blanks(self):
        """A gap between clips must survive as a blank, not silently close up."""
        if not NORMALIZED_MEDIA.exists():
            self.skipTest("normalized media not present")
        from project.compile_mlt import compile_file

        ir = json.loads(EXAMPLE_IR.read_text(encoding="utf-8"))
        # Push the last clip two seconds later, leaving a hole in the timeline.
        ir["tracks"][0]["clips"][2]["timeline_start"] += 2.0

        with tempfile.TemporaryDirectory() as tmp:
            ir_path = Path(tmp) / "gapped.ir.json"
            ir_path.write_text(json.dumps(ir), encoding="utf-8")
            out = Path(tmp) / "gapped.mlt"
            compile_file(ir_path, out)
            parsed = parse_mlt(out)

        self.assertEqual(quantize_ir(ir), quantize_ir(parsed))
        self.assertAlmostEqual(parsed["tracks"][0]["clips"][2]["timeline_start"], 17.5, places=3)


class TestHumanEditedProject(unittest.TestCase):
    """A real project edited and re-saved by Shotcut.

    Shotcut rewrites the file in its own dialect: timecode in/out, and a
    duplicated producer for each cut created by a split. This fixture is that
    output, captured so the parser stays honest without needing Shotcut
    installed to run the tests.
    """

    def setUp(self):
        if not HUMAN_EDITED_MLT.exists():
            self.skipTest("human-edited fixture not present")

    def test_parses_shotcut_rewritten_timeline(self):
        ir = parse_mlt(HUMAN_EDITED_MLT)
        clips = ir["tracks"][0]["clips"]
        self.assertEqual(len(clips), 3)
        total = sum(c["timeline_duration"] for c in clips)
        self.assertAlmostEqual(total, 16.2, places=3)

    def test_duplicate_producers_resolve_to_same_source(self):
        """A split makes Shotcut emit producer0 and producer1 for one file."""
        ir = parse_mlt(HUMAN_EDITED_MLT)
        sources = {Path(c["source"]).name for c in ir["tracks"][0]["clips"]}
        self.assertEqual(len(sources), 1)

    def test_provenance_is_lost_without_the_sidecar(self):
        """Shotcut strips frameflow:* properties, so the .mlt alone cannot carry it."""
        ir = parse_mlt(HUMAN_EDITED_MLT, use_sidecar=False)
        self.assertEqual(ir["project"]["source_frame_rate_mode"], "cfr")

    def test_sidecar_restores_provenance(self):
        if not sidecar_path(HUMAN_EDITED_MLT).exists():
            self.skipTest("sidecar not present")
        ir = parse_mlt(HUMAN_EDITED_MLT, use_sidecar=True)
        self.assertEqual(ir["project"]["source_frame_rate_mode"], "normalized_from_vfr")


class TestSidecar(unittest.TestCase):
    def test_write_then_read(self):
        ir = {"project": {"name": "x", "source_frame_rate_mode": "normalized_from_vfr"},
              "tracks": [{"id": "V1", "type": "broll", "clips": []}]}
        with tempfile.TemporaryDirectory() as tmp:
            mlt = Path(tmp) / "p.mlt"
            write_sidecar(mlt, ir)
            self.assertEqual(read_sidecar(mlt), ir)

    def test_missing_sidecar_reads_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_sidecar(Path(tmp) / "absent.mlt"))

    def test_timeline_structure_wins_over_sidecar(self):
        """The human edited the .mlt, so it is authoritative about clips."""
        parsed = {
            "project": {"name": "parsed", "source_frame_rate_mode": "cfr"},
            "tracks": [{"id": "V1", "type": "video", "clips": [{"id": "clip1"}]}],
        }
        stale = {
            "project": {"name": "original", "source_frame_rate_mode": "normalized_from_vfr"},
            "tracks": [{"id": "V1", "type": "broll",
                        "clips": [{"id": "clip1"}, {"id": "clip2"}, {"id": "clip3"}]}],
        }
        merged = merge_sidecar(parsed, stale)
        self.assertEqual(len(merged["tracks"][0]["clips"]), 1)          # structure from .mlt
        self.assertEqual(merged["tracks"][0]["type"], "broll")          # semantics from sidecar
        self.assertEqual(merged["project"]["source_frame_rate_mode"], "normalized_from_vfr")

    def test_merge_without_sidecar_is_identity(self):
        parsed = {"project": {"name": "p"}, "tracks": []}
        self.assertEqual(merge_sidecar(parsed, None), parsed)


if __name__ == "__main__":
    unittest.main()
