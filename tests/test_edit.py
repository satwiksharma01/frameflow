#!/usr/bin/env python3
"""Tests for `edit`: changing a project the creator already has.

Run with: python -m unittest discover tests
"""
import json
import shutil
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET
from pathlib import Path

from project.change_agent import (build_agent_request, build_context, build_tool, pause_lines,
                                  phrase_lines)
from project.edit import EditError, apply_change, backup, load
from project.parse_mlt import parse_mlt
from project.reconcile import HumanChanges, reconcile
from project.sidecar import read_sidecar, sidecar_path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHOTCUT_SAVED = REPO_ROOT / "examples" / "shotcut-saved-two-track.mlt"
MAIN_MEDIA = REPO_ROOT / "media" / "meet-recording-cfr30.mp4"
SECOND_MEDIA = REPO_ROOT / "media" / "synthetic-talk.mp4"

WORDS = [{"start": 0.1, "end": 0.5, "text": "Hello"}, {"start": 0.5, "end": 0.9, "text": "there."},
         {"start": 2.0, "end": 2.4, "text": "This"}, {"start": 2.4, "end": 2.9, "text": "part"},
         {"start": 2.9, "end": 3.5, "text": "goes."}, {"start": 5.0, "end": 5.6, "text": "Bye."}]
PAUSES = [{"start": 0.95, "end": 1.9}, {"start": 3.6, "end": 4.9}, {"start": 4.0, "end": 4.1}]


class TestTheView(unittest.TestCase):
    def test_phrases_are_marked_in_out_or_partly(self):
        lines = phrase_lines(WORDS, kept=[(0.0, 1.0), (3.0, 6.0)])
        self.assertEqual(lines, ["+ [0.10-0.90] Hello there.",
                                 "~ [2.00-3.50] This part goes.",
                                 "+ [5.00-5.60] Bye."])

    def test_a_removed_phrase_is_marked_out(self):
        self.assertTrue(phrase_lines(WORDS, kept=[(0.0, 1.0)])[1].startswith("- "))

    def test_pauses_say_how_much_of_them_plays(self):
        lines = pause_lines(PAUSES, kept=[(0.0, 1.2), (4.5, 6.0)])
        self.assertEqual(lines, ["[0.95-1.90] 0.95s, 0.25s of it in the cut",
                                 "[3.60-4.90] 1.30s, 0.40s of it in the cut"])

    def test_pauses_too_short_to_cut_in_are_not_listed(self):
        self.assertNotIn("4.00-4.10", "\n".join(pause_lines(PAUSES, kept=[])))

    def test_the_context_carries_everything_the_editor_needs(self):
        ir = {"schema_version": "0.2.0",
              "project": {"name": "t", "width": 1920, "height": 1080, "fps": 30,
                          "source_frame_rate_mode": "cfr"},
              "tracks": [{"id": "V1", "type": "video", "clips": [
                  {"id": "clip1", "source": "C:/m/talk.mp4", "source_in": 0.0, "source_out": 1.2,
                   "timeline_start": 0.0, "timeline_duration": 1.2}]}]}
        timing = {"source": "C:/m/talk.mp4", "duration_seconds": 6.0,
                  "words": WORDS, "pauses": PAUSES}
        context = build_context("cut the goodbye", ir, HumanChanges(known=True), timing)
        for expected in ("cut the goodbye", "No changes since Frameflow", "| 1 | 0:00.00-0:01.20",
                         "Hello there.", "- [5.00-5.60] Bye.", "[3.60-4.90] 1.30s, not in the cut"):
            self.assertIn(expected, context)

    def test_the_agent_request_says_where_to_write_and_how_to_check(self):
        request = build_agent_request("CONTEXT", Path("out/operations.json"),
                                      'python -m project.edit "p.mlt" --apply')
        for expected in ("CONTEXT", "out/operations.json", "--apply", '"override_human_edit"',
                         "Put every boundary in a measured pause"):
            self.assertIn(expected, request)

    def test_the_tool_is_the_operations_schema(self):
        tool = build_tool()
        self.assertEqual(tool.name, "submit_operations")
        self.assertEqual(tool.input_schema["required"], ["summary", "operations"])


class TestEditingAProject(unittest.TestCase):
    """On a copy of a project Shotcut really saved, so the real file is never touched."""

    def setUp(self):
        if not (SHOTCUT_SAVED.exists() and MAIN_MEDIA.exists()):
            self.skipTest("Shotcut-saved fixture or its media not present")
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.mlt = self.folder / "project.mlt"
        # The fixture names its media relative to examples/, and the copy is not there.
        self.mlt.write_text(SHOTCUT_SAVED.read_text(encoding="utf-8").replace(
            "../media/", MAIN_MEDIA.parent.as_posix() + "/"), encoding="utf-8")
        shutil.copy(sidecar_path(SHOTCUT_SAVED), sidecar_path(self.mlt))
        # A timing map for the main recording, so nothing needs transcribing.
        (self.folder / "timing.json").write_text(json.dumps({
            "source": MAIN_MEDIA.resolve().as_posix(), "duration_seconds": 25.7,
            "words": [{"start": 1.0, "end": 2.0, "text": "Hello."}],
            "pauses": [{"start": 2.1, "end": 2.9}, {"start": 3.4, "end": 4.2}]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _add_filter(self):
        tree = ET.parse(self.mlt)
        tractor = tree.getroot().find("tractor")
        f = ET.SubElement(tractor, "filter", {"id": "filter0"})
        ET.SubElement(f, "property", {"name": "shotcut:filter"}).text = "audioGain"
        tree.write(self.mlt, encoding="utf-8", xml_declaration=True)

    def test_an_edit_that_would_lose_an_effect_stops_and_names_it(self):
        self._add_filter()
        with self.assertRaises(EditError) as cm:
            load(self.mlt)
        self.assertIn("the audioGain filter on the whole project", str(cm.exception))

    def test_the_creator_can_choose_to_discard_it(self):
        self._add_filter()
        project = load(self.mlt, discard_unsupported=True)
        self.assertEqual(project.discarded, ["the audioGain filter on the whole project"])

    def test_the_existing_timing_map_is_used(self):
        self.assertEqual(load(self.mlt).timing["words"][0]["text"], "Hello.")

    def test_backup_keeps_the_project_and_its_sidecar(self):
        kept = backup(self.mlt)
        self.assertEqual(kept.read_bytes(), self.mlt.read_bytes())
        self.assertTrue(sidecar_path(kept).exists())
        self.assertEqual(kept.parent.name, "history")

    def test_no_operations_leaves_the_project_untouched(self):
        before = self.mlt.read_bytes()
        result = apply_change(load(self.mlt), {"summary": "nothing to do", "operations": []})
        self.assertIsNone(result)
        self.assertEqual(self.mlt.read_bytes(), before)
        self.assertFalse((self.folder / "history").exists())

    def test_rejected_operations_leave_the_project_untouched(self):
        before = self.mlt.read_bytes()
        with self.assertRaises(EditError):
            apply_change(load(self.mlt), {"summary": "x", "operations": [
                {"action": "remove", "start": 20.0, "end": 21.0, "reason": "not in the cut",
                 "source": MAIN_MEDIA.name}]})
        self.assertEqual(self.mlt.read_bytes(), before)

    def test_a_change_lands_and_becomes_the_new_baseline(self):
        project = load(self.mlt)
        result = apply_change(project, {"summary": "tighten", "operations": [
            {"action": "remove", "start": 2.5, "end": 3.8, "reason": "tighten",
             "source": MAIN_MEDIA.name}]}, verify=False)
        self.assertEqual(result, self.mlt)

        after = parse_mlt(self.mlt)
        main = [(c["source_in"], c["source_out"]) for c in after["tracks"][0]["clips"]]
        # Both ends placed in their pauses, on frames: 2.1+0.25 = 2.35s is exactly
        # half a frame, which rounds to even like the rest of the pipeline (frame 70).
        self.assertEqual(main[:2], [(0.0, 2.333333), (3.933333, 5.0)])
        self.assertEqual([t["id"] for t in after["tracks"]], ["V1", "V2"])      # B-roll track kept
        self.assertEqual(after["tracks"][1]["type"], "broll")
        self.assertFalse(reconcile(read_sidecar(self.mlt), after).any)          # new baseline
        self.assertEqual(len(list((self.folder / "history").glob("*.mlt"))), 1)


class TestEditingAnOpenShotProject(unittest.TestCase):
    """The same loop on the default editor's project: a first cut as Frameflow
    writes it for OpenShot, with B-roll above the main track."""

    def setUp(self):
        from project.openshot_template import profile_dirs
        if not (MAIN_MEDIA.exists() and SECOND_MEDIA.exists()):
            self.skipTest("media not present")
        if not profile_dirs():
            self.skipTest("OpenShot's profiles not found; is OpenShot installed?")
        from project.compile_osp import compile_file
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

        def clip(clip_id, source, source_in, start, duration):
            return {"id": clip_id, "source": source.resolve().as_posix(), "source_in": source_in,
                    "source_out": source_in + duration, "timeline_start": start,
                    "timeline_duration": duration}

        ir = {"schema_version": "0.2.0",
              "project": {"name": "project", "width": 1920, "height": 1080, "fps": 30,
                          "source_frame_rate_mode": "cfr"},
              "tracks": [{"id": "V1", "type": "video", "clips": [
                             clip("clip1", MAIN_MEDIA, 0.0, 0.0, 5.0),
                             clip("clip2", MAIN_MEDIA, 5.0, 5.0, 5.0)]},
                         {"id": "V2", "type": "broll", "clips": [
                             clip("clip1", SECOND_MEDIA, 0.0, 3.0, 3.0)]}]}
        ir_path = self.folder / "project.ir.json"
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        self.osp = compile_file(ir_path, self.folder / "project.osp")
        (self.folder / "timing.json").write_text(json.dumps({
            "source": MAIN_MEDIA.resolve().as_posix(), "duration_seconds": 25.7,
            "words": [{"start": 1.0, "end": 2.0, "text": "Hello."}],
            "pauses": [{"start": 2.1, "end": 2.9}, {"start": 3.4, "end": 4.2}]}), encoding="utf-8")

    def test_a_change_lands_and_becomes_the_new_baseline(self):
        from project.parse_osp import parse_osp
        result = apply_change(load(self.osp), {"summary": "tighten", "operations": [
            {"action": "remove", "start": 2.5, "end": 3.8, "reason": "tighten",
             "source": MAIN_MEDIA.name}]}, verify=False)
        self.assertEqual(result, self.osp)

        after = parse_osp(self.osp)
        main = [(c["source_in"], c["source_out"]) for c in after["tracks"][0]["clips"]]
        self.assertEqual(main[:2], [(0.0, 2.333333), (3.933333, 5.0)])
        self.assertEqual([t["id"] for t in after["tracks"]], ["V1", "V2"])      # B-roll track kept
        self.assertEqual(after["tracks"][1]["type"], "broll")
        self.assertFalse(reconcile(read_sidecar(self.osp), after).any)          # new baseline
        self.assertEqual(len(list((self.folder / "history").glob("*.osp"))), 1)

    def test_a_graphic_lands_on_its_own_track(self):
        """A card at 6s of the recording plays at 6s on the timeline (clip 2 runs 5-10s)."""
        from project import hyperframes
        from project.parse_osp import parse_osp
        caption = REPO_ROOT / "media" / "caption.mov"
        if not caption.exists():
            self.skipTest("media not present")
        render = lambda composition, out, fps: Path(shutil.copy(caption, out))
        with mock.patch.object(hyperframes, "render", render):
            apply_change(load(self.osp), {"summary": "title", "operations": [], "graphics": [
                {"at": 6.0, "duration": 2.0, "text": "Hello", "reason": "title",
                 "source": MAIN_MEDIA.name}]}, verify=False)
        after = parse_osp(self.osp)
        graphics = after["tracks"][-1]
        self.assertEqual((graphics["id"], graphics["type"]), ("Graphics", "graphics"))
        clip = graphics["clips"][0]
        self.assertEqual((clip["timeline_start"], clip["timeline_duration"]), (6.0, 2.0))
        self.assertEqual(Path(clip["source"]).parent, self.folder / "graphics")
        self.assertEqual(len(after["tracks"][0]["clips"]), 2)        # the cut is untouched

    def test_captions_move_with_the_cut(self):
        """A caption at 6s of the recording plays at 6s; after 2.33-3.93s is removed, at 4.4s."""
        from project.compile_osp import compile_file
        from project.parse_osp import parse_osp
        caption = REPO_ROOT / "media" / "caption.mov"
        if not caption.exists():
            self.skipTest("media not present")
        ir_path = self.folder / "project.ir.json"
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        ir["tracks"].append({"id": "Captions", "type": "captions", "clips": [
            {"id": "clip1", "source": caption.resolve().as_posix(), "source_in": 0.0, "source_out": 1.0,
             "timeline_start": 6.0, "timeline_duration": 1.0}]})
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        compile_file(ir_path, self.osp)

        apply_change(load(self.osp), {"summary": "tighten", "operations": [
            {"action": "remove", "start": 2.5, "end": 3.8, "reason": "tighten",
             "source": MAIN_MEDIA.name}]}, verify=False)
        after = parse_osp(self.osp)
        captions = next(t for t in after["tracks"] if t["type"] == "captions")
        self.assertAlmostEqual(captions["clips"][0]["timeline_start"], 4.4, places=3)
        # The B-roll's first moment, 3s, was removed: it starts where the cut now is, and keeps its length.
        b_roll = after["tracks"][1]["clips"][0]
        self.assertAlmostEqual(b_roll["timeline_start"], 2.333333, places=5)
        self.assertEqual(b_roll["timeline_duration"], 3.0)

    def test_a_crop_moved_by_hand_survives_an_edit(self):
        """A vertical cut whose crop the creator moved in OpenShot at 2s: after a cut
        is made in that clip, both halves keep the move, in recording time."""
        from project.compile_osp import compile_file
        from project.parse_osp import parse_osp
        ir_path = self.folder / "project.ir.json"
        ir = json.loads(ir_path.read_text(encoding="utf-8"))
        ir["project"].update(width=1080, height=1920)
        ir["tracks"] = ir["tracks"][:1]
        for clip in ir["tracks"][0]["clips"]:
            clip["transform"] = {"fill": True}
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        compile_file(ir_path, self.osp)
        # What OpenShot writes when the creator changes Location X with the playhead at 2s.
        osp = json.loads(self.osp.read_text(encoding="utf-8"))
        first = min(osp["clips"], key=lambda c: c["position"])
        first["location_x"]["Points"].append({"co": {"X": 61, "Y": 0.1}, "interpolation": 1})
        self.osp.write_text(json.dumps(osp), encoding="utf-8")

        apply_change(load(self.osp), {"summary": "tighten", "operations": [
            {"action": "remove", "start": 2.5, "end": 3.8, "reason": "tighten",
             "source": MAIN_MEDIA.name}]}, verify=False)
        after = parse_osp(self.osp)
        halves = after["tracks"][0]["clips"][:2]
        self.assertEqual([(c["source_in"], c["source_out"]) for c in halves], [(0.0, 2.333333), (3.933333, 5.0)])
        moved = {"fill": True, "position": {"x": [{"at": 0.0, "value": 0.0},
                                                  {"at": 2.0, "value": halves[0]["transform"]["position"]["x"][1]["value"],
                                                   "curve": "linear"}]}}
        self.assertEqual([c["transform"] for c in halves], [moved, moved])
        self.assertGreater(moved["position"]["x"][1]["value"], 0)

    def test_a_cut_inside_a_faded_clip_keeps_each_fade_on_its_outer_edge(self):
        """Fade In and Out on clip 1 (0-5s); removing 2.5-3.8s splits it in two."""
        from project.openshot_template import keyframe
        from project.parse_osp import parse_osp
        data = json.loads(self.osp.read_text(encoding="utf-8"))
        data["clips"][0]["alpha"] = {"Points": keyframe(0.0)["Points"] + keyframe(1.0, x=31)["Points"]
                                     + keyframe(1.0, x=121)["Points"] + keyframe(0.0, x=151)["Points"]}
        self.osp.write_text(json.dumps(data), encoding="utf-8")
        apply_change(load(self.osp), {"summary": "tighten", "operations": [
            {"action": "remove", "start": 2.5, "end": 3.8, "reason": "tighten",
             "source": MAIN_MEDIA.name}]}, verify=False)
        left, right = parse_osp(self.osp)["tracks"][0]["clips"][:2]
        self.assertEqual((left.get("fade_in"), left.get("fade_out")), ({"picture": 1.0}, None))
        self.assertEqual((right.get("fade_in"), right.get("fade_out")), (None, {"picture": 1.0}))

    def test_an_edit_that_would_lose_a_hand_drawn_curve_stops_and_names_it(self):
        from project.openshot_template import keyframe
        data = json.loads(self.osp.read_text(encoding="utf-8"))
        data["clips"][0]["alpha"] = {"Points": keyframe(1.0)["Points"] + keyframe(0.2, x=60)["Points"]
                                     + keyframe(1.0, x=120)["Points"]}
        self.osp.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(EditError) as cm:
            load(self.osp)
        self.assertIn("changed alpha on clip 1 on V1", str(cm.exception))
        self.assertIn("Remove them in OpenShot", str(cm.exception))

    def test_a_project_from_an_editor_frameflow_does_not_know_is_refused(self):
        other = self.folder / "project.kdenlive"
        other.write_text("<mlt/>", encoding="utf-8")
        with self.assertRaises(EditError):
            load(other)


if __name__ == "__main__":
    unittest.main()
