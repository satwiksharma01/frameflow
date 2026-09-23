#!/usr/bin/env python3
"""Round-trip tests for the project bridge: IR -> MLT -> IR.

Round-tripping is only lossless at frame granularity - a timeline is discrete -
so comparisons go through quantize_ir() rather than demanding float equality
the format cannot deliver.

Run with: python -m unittest discover tests
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from project.parse_mlt import ParseError, parse_mlt, parse_time, quantize_ir
from project.sidecar import merge_sidecar, read_sidecar, sidecar_path, write_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_IR = REPO_ROOT / "examples" / "meet-recording.ir.json"
EXAMPLE_MLT = REPO_ROOT / "examples" / "meet-recording.mlt"
HUMAN_EDITED_MLT = REPO_ROOT / "examples" / "human-edited.mlt"
SHOTCUT_SAVED_TWO_TRACK = REPO_ROOT / "examples" / "shotcut-saved-two-track.mlt"
SHOTCUT_REFERENCE = REPO_ROOT / "phase0" / "shotcut_reference.mlt"
NORMALIZED_MEDIA = REPO_ROOT / "media" / "meet-recording-cfr30.mp4"
SECOND_MEDIA = REPO_ROOT / "media" / "synthetic-talk.mp4"


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


def _multitrack_ir(main_source: Path, broll_source: Path) -> dict:
    """A main video track with B-roll laid over its middle, from a second file."""
    return {
        "schema_version": "0.2.0",
        "project": {"name": "two-track", "width": 1920, "height": 1080, "fps": 30,
                    "source_frame_rate_mode": "cfr"},
        "tracks": [
            {"id": "V1", "type": "video", "clips": [
                {"id": "clip1", "source": main_source.as_posix(), "source_in": 0.0,
                 "source_out": 4.0, "timeline_start": 0.0, "timeline_duration": 4.0},
                {"id": "clip2", "source": main_source.as_posix(), "source_in": 6.0,
                 "source_out": 10.0, "timeline_start": 4.0, "timeline_duration": 4.0},
            ]},
            {"id": "V2", "type": "broll", "clips": [
                {"id": "clip1", "source": broll_source.as_posix(), "source_in": 1.0,
                 "source_out": 3.0, "timeline_start": 2.0, "timeline_duration": 2.0},
            ]},
        ],
    }


class TestMultiTrack(unittest.TestCase):
    """Phase 3.7. Until this worked, B-roll, short-form and graphics were all blocked."""

    def setUp(self):
        if not (NORMALIZED_MEDIA.exists() and SECOND_MEDIA.exists()):
            self.skipTest("two media files are needed to compile two sources")
        from project.compile_mlt import build_mlt
        self.ir = _multitrack_ir(NORMALIZED_MEDIA, SECOND_MEDIA)
        self.mlt = build_mlt(self.ir)

    def test_each_distinct_source_gets_one_producer(self):
        producers = self.mlt.findall("producer")
        resources = [p.find("property[@name='resource']").text for p in producers
                     if p.get("id", "").startswith("producer")]
        self.assertEqual(len(resources), 2)
        self.assertEqual(len(set(resources)), 2)

    def test_clips_from_the_same_file_share_a_producer(self):
        """Two clips cut from one recording must not declare it twice."""
        playlist = self.mlt.find("playlist[@id='playlist0']")
        used = {e.get("producer") for e in playlist.findall("entry")}
        self.assertEqual(len(used), 1)

    def test_each_track_becomes_its_own_playlist(self):
        ids = [p.get("id") for p in self.mlt.findall("playlist")]
        self.assertIn("playlist0", ids)
        self.assertIn("playlist1", ids)

    def test_the_broll_track_points_at_the_second_file(self):
        entry = self.mlt.find("playlist[@id='playlist1']/entry")
        producer = self.mlt.find(f"producer[@id='{entry.get('producer')}']")
        self.assertTrue(
            producer.find("property[@name='resource']").text.endswith("synthetic-talk.mp4"))

    def test_an_upper_track_starting_late_gets_a_blank(self):
        blank = self.mlt.find("playlist[@id='playlist1']/blank")
        self.assertEqual(int(blank.get("length")), 60)      # 2.0s at 30fps

    def test_the_tractor_wires_background_plus_both_tracks(self):
        tractor = self.mlt.find("tractor")
        producers = [t.get("producer") for t in tractor.findall("track")]
        self.assertEqual(producers, ["background", "playlist0", "playlist1"])

    def test_every_content_track_gets_its_own_pair_of_transitions(self):
        tractor = self.mlt.find("tractor")
        services = [t.find("property[@name='mlt_service']").text
                    for t in tractor.findall("transition")]
        self.assertEqual(services, ["mix", "qtblend", "mix", "qtblend"])

    def test_the_background_spans_the_longest_track(self):
        """A shorter first track must not end the project before an upper one."""
        ir = _multitrack_ir(NORMALIZED_MEDIA, SECOND_MEDIA)
        ir["tracks"][1]["clips"][0]["timeline_start"] = 20.0   # B-roll outlasts V1
        from project.compile_mlt import build_mlt
        mlt = build_mlt(ir)
        background = mlt.find("playlist[@id='background']/entry")
        self.assertEqual(int(background.get("out")), 22 * 30 - 1)

    def test_two_tracks_round_trip(self):
        from project.compile_mlt import compile_file
        with tempfile.TemporaryDirectory() as tmp:
            ir_path = Path(tmp) / "two-track.ir.json"
            ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
            out = Path(tmp) / "two-track.mlt"
            compile_file(ir_path, out)
            parsed = parse_mlt(out)
        self.assertEqual(quantize_ir(self.ir), quantize_ir(parsed))

    def test_track_semantics_survive_the_round_trip(self):
        from project.compile_mlt import compile_file
        with tempfile.TemporaryDirectory() as tmp:
            ir_path = Path(tmp) / "two-track.ir.json"
            ir_path.write_text(json.dumps(self.ir), encoding="utf-8")
            out = Path(tmp) / "two-track.mlt"
            compile_file(ir_path, out)
            parsed = parse_mlt(out)
        self.assertEqual([t["type"] for t in parsed["tracks"]], ["video", "broll"])
        self.assertEqual([t["id"] for t in parsed["tracks"]], ["V1", "V2"])


class TestCompilerRefusals(unittest.TestCase):
    """What the compiler will not guess at, and says so."""

    def _ir(self, tracks):
        return {"schema_version": "0.2.0",
                "project": {"name": "x", "width": 1920, "height": 1080, "fps": 30,
                            "source_frame_rate_mode": "cfr"},
                "tracks": tracks}

    def test_an_audio_track_is_refused_by_name(self):
        from project.compile_mlt import build_mlt
        ir = self._ir([{"id": "A1", "type": "audio", "clips": [
            {"id": "c1", "source": "x.wav", "timeline_start": 0.0, "timeline_duration": 1.0}]}])
        with self.assertRaises(NotImplementedError) as cm:
            build_mlt(ir)
        self.assertIn("A1", str(cm.exception))

    def test_a_caption_clip_with_no_source_is_refused_by_name(self):
        from project.compile_mlt import build_mlt
        ir = self._ir([{"id": "C1", "type": "captions", "clips": [
            {"id": "caption7", "text": "hello", "timeline_start": 0.0,
             "timeline_duration": 1.0}]}])
        with self.assertRaises(NotImplementedError) as cm:
            build_mlt(ir)
        self.assertIn("caption7", str(cm.exception))

    def test_a_project_with_no_clips_anywhere_is_an_error(self):
        from project.compile_mlt import build_mlt
        with self.assertRaises(ValueError):
            build_mlt(self._ir([{"id": "V1", "type": "video", "clips": []}]))


class TestPortableProjects(unittest.TestCase):
    """Door 3. "Projects break when files move" is a listed editing pain point;
    MLT resolves a relative resource against the .mlt's own directory, so a
    self-contained folder can survive being moved."""

    def _project(self, root: Path) -> Path:
        """A one-clip project with its media inside the project folder."""
        from project.compile_mlt import compile_file
        root.mkdir(parents=True, exist_ok=True)
        (root / "media").mkdir(exist_ok=True)
        shutil.copy(SECOND_MEDIA, root / "media" / "clip.mp4")
        ir = {"schema_version": "0.2.0",
              "project": {"name": "portable", "width": 1920, "height": 1080, "fps": 30,
                          "source_frame_rate_mode": "cfr"},
              "tracks": [{"id": "V1", "type": "video", "clips": [
                  {"id": "clip1", "source": (root / "media" / "clip.mp4").as_posix(),
                   "source_in": 0.0, "source_out": 3.0,
                   "timeline_start": 0.0, "timeline_duration": 3.0}]}]}
        ir_path = root / "p.ir.json"
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        return compile_file(ir_path, root / "p.mlt", relative_paths=True)

    def setUp(self):
        if not SECOND_MEDIA.exists():
            self.skipTest("media not present")

    def test_media_inside_the_project_is_referenced_relatively(self):
        with tempfile.TemporaryDirectory() as tmp:
            mlt = self._project(Path(tmp) / "proj")
            text = mlt.read_text(encoding="utf-8")
        self.assertIn("<property name=\"resource\">media/clip.mp4</property>", text)
        self.assertNotIn(tmp.replace("\\", "/"), text)

    def test_a_moved_project_still_finds_its_media(self):
        """The whole point: rename the folder and the project still resolves."""
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "before"
            self._project(original)
            moved = Path(tmp) / "after renaming"
            original.rename(moved)

            parsed = parse_mlt(moved / "p.mlt")
            source = Path(parsed["tracks"][0]["clips"][0]["source"])
            self.assertTrue(source.exists(), f"{source} should exist after the move")
            self.assertEqual(source.parent.parent.name, "after renaming")

    def test_the_parser_hands_back_an_absolute_path(self):
        """The IR carries absolute paths; only the .mlt is relative."""
        with tempfile.TemporaryDirectory() as tmp:
            mlt = self._project(Path(tmp) / "proj")
            parsed = parse_mlt(mlt)
        self.assertTrue(Path(parsed["tracks"][0]["clips"][0]["source"]).is_absolute())

    def test_a_source_that_cannot_be_made_relative_stays_absolute(self):
        from project.compile_mlt import resource_path
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            other_drive = [f"{d}:/" for d in "CDEFGH"
                           if Path(f"{d}:/").exists() and not here.as_posix().upper().startswith(d)]
            if not other_drive:
                self.skipTest("no second drive to test the cross-drive case")
            written = resource_path(Path(other_drive[0]) / "somewhere" / "clip.mp4", here)
        self.assertTrue(Path(written).is_absolute())

    def test_no_project_dir_means_absolute(self):
        from project.compile_mlt import resource_path
        self.assertTrue(Path(resource_path(SECOND_MEDIA, None)).is_absolute())

    def test_paths_are_absolute_unless_asked_for(self):
        """Shotcut writes absolute paths and has not been shown to read
        relative ones, so portability is opt-in until it has."""
        from project.compile_mlt import compile_file
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            root.mkdir()
            (root / "media").mkdir()
            shutil.copy(SECOND_MEDIA, root / "media" / "clip.mp4")
            ir = {"schema_version": "0.2.0",
                  "project": {"name": "p", "width": 1920, "height": 1080, "fps": 30,
                              "source_frame_rate_mode": "cfr"},
                  "tracks": [{"id": "V1", "type": "video", "clips": [
                      {"id": "clip1", "source": (root / "media" / "clip.mp4").as_posix(),
                       "source_in": 0.0, "source_out": 3.0,
                       "timeline_start": 0.0, "timeline_duration": 3.0}]}]}
            ir_path = root / "p.ir.json"
            ir_path.write_text(json.dumps(ir), encoding="utf-8")
            text = compile_file(ir_path, root / "p.mlt").read_text(encoding="utf-8")
        self.assertIn("media/clip.mp4</property>", text)
        self.assertNotIn(">media/clip.mp4<", text)          # not the relative form

    def test_project_folder_property_matches_the_path_style(self):
        """Shotcut gates path handling on this; it must agree with what we wrote."""
        from project.compile_mlt import compile_file
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            absolute = self._project(root).read_text(encoding="utf-8")
        self.assertIn('<property name="shotcut:projectFolder">1</property>', absolute)

    def test_default_compile_declares_absolute_paths_to_shotcut(self):
        from project.compile_mlt import compile_file
        with tempfile.TemporaryDirectory() as tmp:
            ir_path = Path(tmp) / "p.ir.json"
            ir = json.loads(EXAMPLE_IR.read_text(encoding="utf-8"))
            ir_path.write_text(json.dumps(ir), encoding="utf-8")
            if not NORMALIZED_MEDIA.exists():
                self.skipTest("media not present")
            text = compile_file(ir_path, Path(tmp) / "p.mlt").read_text(encoding="utf-8")
        self.assertIn('<property name="shotcut:projectFolder">0</property>', text)


class TestShotcutSavedMultiTrack(unittest.TestCase):
    """Phase 3.7's gate, captured. This file is a two-track Frameflow project
    that Shotcut opened, rendered as a real timeline, and saved over."""

    def setUp(self):
        if not SHOTCUT_SAVED_TWO_TRACK.exists():
            self.skipTest("Shotcut-saved fixture not present")
        self.ir = parse_mlt(SHOTCUT_SAVED_TWO_TRACK)

    def test_both_tracks_survive_a_human_save(self):
        self.assertEqual([t["id"] for t in self.ir["tracks"]], ["V1", "V2"])

    def test_clips_and_timings_are_unchanged(self):
        v1, v2 = self.ir["tracks"]
        self.assertEqual([(c["timeline_start"], c["timeline_duration"]) for c in v1["clips"]],
                         [(0.0, 5.0), (5.0, 5.0)])
        self.assertEqual([(c["timeline_start"], c["timeline_duration"]) for c in v2["clips"]],
                         [(3.0, 3.0)])

    def test_the_second_source_file_survives(self):
        sources = {Path(c["source"]).name for t in self.ir["tracks"] for c in t["clips"]}
        self.assertEqual(sources, {"meet-recording-cfr30.mp4", "synthetic-talk.mp4"})

    def test_shotcut_stripped_every_frameflow_property(self):
        """Finding 3, now confirmed for multi-track: our namespace does not survive."""
        self.assertNotIn("frameflow:", SHOTCUT_SAVED_TWO_TRACK.read_text(encoding="utf-8"))

    def test_the_sidecar_is_what_restores_the_broll_track_type(self):
        """Without it the B-roll track degrades to a plain video track, because
        shotcut:name is the only track identity Shotcut keeps."""
        without = parse_mlt(SHOTCUT_SAVED_TWO_TRACK, use_sidecar=False)
        self.assertEqual([t["type"] for t in without["tracks"]], ["video", "video"])
        self.assertEqual([t["type"] for t in self.ir["tracks"]], ["video", "broll"])


class TestUnsupportedContent(unittest.TestCase):
    """What an edit that regenerates the project would lose. Each case starts
    from a project Shotcut really saved and adds one thing a creator might."""

    def setUp(self):
        if not SHOTCUT_SAVED_TWO_TRACK.exists():
            self.skipTest("Shotcut-saved fixture not present")
        import xml.etree.ElementTree as ET
        self.ET = ET
        self.tree = ET.parse(SHOTCUT_SAVED_TWO_TRACK)
        self.root = self.tree.getroot()

    def found(self):
        from project.parse_mlt import unsupported_content
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.mlt"
            self.tree.write(path, encoding="utf-8", xml_declaration=True)
            return unsupported_content(path)

    def _add_filter(self, owner, name):
        f = self.ET.SubElement(owner, "filter", {"id": "filter0"})
        self.ET.SubElement(f, "property", {"name": "mlt_service"}).text = "brightness"
        self.ET.SubElement(f, "property", {"name": "shotcut:filter"}).text = name

    def test_a_real_save_loses_nothing(self):
        self.assertEqual(self.found(), [])

    def test_a_filter_on_a_clip_is_named_with_its_clip(self):
        playlist = self.root.find("playlist[@id='playlist0']")
        producer = self.root.find(f"producer[@id='{playlist.find('entry').get('producer')}']")
        self._add_filter(producer, "fadeInBrightness")
        self.assertEqual(self.found(), ["the fadeInBrightness filter on clip 1 on V1"])

    def test_a_filter_on_a_track(self):
        self._add_filter(self.root.find("playlist[@id='playlist1']"), "brightness")
        self.assertEqual(self.found(), ["the brightness filter on track V2"])

    def test_a_filter_on_the_whole_project(self):
        self._add_filter(self.root.find("tractor"), "audioGain")
        self.assertEqual(self.found(), ["the audioGain filter on the whole project"])

    def test_a_hidden_track(self):
        self.root.find("tractor").findall("track")[2].set("hide", "video")
        self.assertIn('track V2 is hidden or muted (hide="video")', self.found())

    def test_a_title_or_image_clip(self):
        playlist = self.root.find("playlist[@id='playlist1']")
        producer = self.root.find(f"producer[@id='{playlist.find('entry').get('producer')}']")
        for prop in producer.findall("property"):
            if prop.get("name") == "mlt_service":
                prop.text = "qtext"
        self.assertEqual(self.found(), ["a clip of type qtext, clip 1 on V2"])

    def test_a_crossfade_between_clips(self):
        """Shotcut writes a crossfade as a tractor that a playlist entry points at."""
        crossfade = self.ET.SubElement(self.root, "tractor", {"id": "tractor1"})
        self.root.remove(crossfade)
        self.root.insert(list(self.root).index(self.root.find("tractor")), crossfade)
        self.root.find("playlist[@id='playlist0']").findall("entry")[1].set("producer", "tractor1")
        self.assertEqual(self.found(), ["a transition at clip 2 on V1"])

    def test_items_in_the_playlist_panel(self):
        self.ET.SubElement(self.root.find("playlist[@id='main_bin']"), "entry",
                           {"producer": "producer0", "in": "0", "out": "10"})
        self.assertEqual(self.found(), ["1 item(s) in Shotcut's playlist panel"])

    def test_several_things_are_all_reported(self):
        self.root.find("tractor").findall("track")[1].set("hide", "audio")
        self._add_filter(self.root.find("tractor"), "audioGain")
        self.assertEqual(len(self.found()), 2)


if __name__ == "__main__":
    unittest.main()
