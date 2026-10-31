"""Shorts from one long recording: the moments an editor picks, checked, each built as its own cut."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import shorts
from project.editor_agent import check_plan

TRANSCRIPT = {
    "source": "C:/media/talk.mp4",
    "duration_seconds": 100.0,
    "language": "en",
    "segments": [
        {"start": 0.0, "end": 9.5, "text": "Hi, so, where was I."},
        {"start": 9.5, "end": 40.5, "text": "Nobody tells you this about starting a channel."},
        {"start": 40.5, "end": 100.0, "text": "Anyway, that's it for today."},
    ],
    "silences": [{"start": 9.2, "end": 9.8}, {"start": 40.1, "end": 40.9}],
}


def moment(**fields):
    return {"title": "Nobody tells you", "start": 10.0, "end": 40.0,
            "hook": "Nobody tells you this - a claim that makes you stay", "reason": "a tip with its payoff",
            **fields}


class TestAMomentAsACut(unittest.TestCase):
    def test_only_the_moment_is_kept_less_what_the_editor_removed_inside_it(self):
        plan = shorts.edit_plan(moment(remove=[{"start": 20.0, "end": 22.0, "reason": "false start"}]), 100.0)
        self.assertEqual([(d["action"], d["start"], d["end"]) for d in plan["decisions"]],
                         [("remove", 0.0, 10.0), ("keep", 10.0, 20.0), ("remove", 20.0, 22.0),
                          ("keep", 22.0, 40.0), ("remove", 40.0, 100.0)])
        self.assertEqual(check_plan(plan, TRANSCRIPT), [])

    def test_a_moment_that_runs_the_whole_recording_is_one_keep(self):
        plan = shorts.edit_plan(moment(start=0.0, end=100.0), 100.0)
        self.assertEqual([(d["action"], d["start"], d["end"]) for d in plan["decisions"]], [("keep", 0.0, 100.0)])

    def test_the_editors_doubt_about_a_removal_is_kept(self):
        plan = shorts.edit_plan(moment(remove=[{"start": 20.0, "end": 22.0, "reason": "maybe a retake",
                                                "confidence": "low"}]), 100.0)
        self.assertEqual(plan["decisions"][2]["confidence"], "low")


class TestCheckingThePlan(unittest.TestCase):
    def test_a_good_plan_passes(self):
        self.assertEqual(shorts.check_shorts({"shorts": [moment()]}, TRANSCRIPT), [])

    def test_each_mistake_is_named_with_its_short(self):
        plan = {"shorts": [
            moment(),
            moment(start=90.0, end=120.0),                                             # past the end
            moment(remove=[{"start": 5.0, "end": 12.0, "reason": "r"}]),               # starts before the moment
            moment(remove=[{"start": 20.0, "end": 25.0, "reason": "r"},
                           {"start": 24.0, "end": 26.0, "reason": "r"}]),              # overlap
            moment(remove=[{"start": 10.05, "end": 39.0, "reason": "r"}]),             # leaves a sliver
        ]}
        problems = shorts.check_shorts(plan, TRANSCRIPT)
        self.assertEqual([p.split(" ", 2)[1] for p in problems], ["2", "3", "4", "5"], problems)

    def test_a_plan_that_breaks_the_schema_is_reported(self):
        problems = shorts.check_shorts({"shorts": [{"start": 10.0, "end": 40.0}]}, TRANSCRIPT)
        self.assertEqual(len(problems), 1)
        self.assertIn("title", problems[0])


class TestTheRequest(unittest.TestCase):
    def test_request_carries_the_count_transcript_schema_and_next_step(self):
        request = shorts.build_request(TRANSCRIPT, 3, "only the money tips", Path("out/shorts_plan.json"),
                                       'python -m project.shorts "talk.mp4" --build')
        self.assertIn("3", request.split("## Recording")[0])           # how many to pick
        self.assertIn("Nobody tells you this", request)                 # transcript
        self.assertIn("[40.10-40.90]", request)                         # measured silences
        self.assertIn("only the money tips", request)                   # brief
        self.assertIn("out/shorts_plan.json", request)
        self.assertIn("--build", request)
        self.assertIn('"hook"', request)                                # schema


class TestBuilding(unittest.TestCase):
    def test_each_short_becomes_its_own_vertical_project_with_captions(self):
        built = []

        def fake_build(video, out_dir, plan, verify=True, editor=None, captions=False, vertical=False, name=None):
            source = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))["source"]
            built.append((out_dir.name, name, captions, vertical, source, plan["decisions"][1]["start"]))
            return out_dir / f"{name}.osp"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "transcript.json").write_text(json.dumps(TRANSCRIPT), encoding="utf-8")
            (out / "timing.json").write_text(json.dumps({"words": [], "pauses": []}), encoding="utf-8")
            with mock.patch.object(shorts.first_cut, "build", fake_build):
                projects = shorts.build(Path("C:/media/talk.mp4"), out,
                                        {"shorts": [moment(), moment(title="Second", start=50.0, end=80.0)]})
            self.assertTrue((out / "short-2" / "timing.json").exists())

        self.assertEqual(built, [("short-1", "talk-short-1", True, True, "C:/media/talk.mp4", 10.0),
                                 ("short-2", "talk-short-2", True, True, "C:/media/talk.mp4", 50.0)])
        self.assertEqual([p.name for p in projects], ["talk-short-1.osp", "talk-short-2.osp"])


if __name__ == "__main__":
    unittest.main()
