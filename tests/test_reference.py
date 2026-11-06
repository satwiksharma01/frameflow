"""Make it like this: a reference video's structure, through Agent Video, into a Frameflow storyboard."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from project import produce, reference
from project.first_cut import TIMING_FILE
from project.media import _find_tool
from project.validate import validate

BRIEF = {"title": "Talk", "format": "reel", "aspect": "9:16", "target_seconds": 4, "audience": "travellers",
         "tone": "calm", "summary": "A short talk.", "facts": [], "skills": []}
ANALYSIS = {
    "version": 1,
    "hook": {"status": "observed", "summary": "A red card opens it.",
             "evidence": [{"start": 0, "end": 2, "note": "The first frames are red."}]},
    "captionStyle": {"status": "unknown", "summary": "unknown", "evidence": []},
    "visualStyle": {"status": "observed", "summary": "Two flat cards, cut once.",
                    "evidence": [{"start": 0, "end": 4, "note": "The contact sheet."}]},
    "audioStyle": {"status": "unknown", "summary": "unknown", "evidence": []},
    "structure": [{"start": 0, "end": 2, "purpose": "Opening"}, {"start": 2, "end": 4, "purpose": "Second card"}],
    "uncertainties": ["The reference has no sound or captions to observe."],
    "reviewNotes": []}


def _concept(concept_id: str, scenes: list[dict]) -> dict:
    return {"id": concept_id, "title": concept_id.replace("-", " "), "summary": "s", "adaptation": "a",
            "storyboard": {"script": "A talk.", "spoken_captions": False, "scenes": scenes}}


def _footage(start: float, end: float, reason: str) -> dict:
    return {"visual": {"type": "footage", "source": "talk.mp4", "start": start, "end": end}, "reason": reason}


# Two beats cut inside the measured pause at 1.0-1.6 s, or the whole recording in one.
CONCEPTS = {"version": 1, "concepts": [
    _concept("two-beats", [_footage(0.0, 1.3, "Open like the reference"), _footage(1.3, 4.0, "Then the rest")]),
    _concept("one-take", [_footage(0.0, 4.0, "All of it")])]}


def _node_22() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    return int(version.split(".")[0] or 0) >= 22


class TestTheReferenceFlow(unittest.TestCase):
    def setUp(self):
        if not _node_22():
            self.skipTest("Agent Video needs Node.js 22 or newer")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        ffmpeg = _find_tool("ffmpeg")
        self.reference = root / "reference.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=30:d=2", "-f", "lavfi",
                        "-i", "color=c=blue:s=640x360:r=30:d=2", "-filter_complex", "[0][1]concat=n=2:v=1:a=0",
                        "-pix_fmt", "yuv420p", str(self.reference)], check=True)
        talk = root / "talk.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4", "-f", "lavfi",
                        "-i", "sine=f=440:d=4", "-pix_fmt", "yuv420p", "-shortest", str(talk)], check=True)
        # A produce folder as --prepare leaves it: the recording's measured pauses in its own folder.
        self.folder = root / "video"
        (self.folder / "footage" / "talk").mkdir(parents=True)
        (self.folder / "footage" / "talk" / TIMING_FILE).write_text(json.dumps({
            "source": talk.as_posix(), "duration_seconds": 4.0, "words": [],
            "pauses": [{"start": 1.0, "end": 1.6}]}), encoding="utf-8")
        (self.folder / produce.INPUTS_FILE).write_text(json.dumps({
            "prompt": "p", "script": None, "assets": [], "music": [], "looks": [],
            "footage": [{"name": "talk.mp4", "source": talk.as_posix(), "duration": 4.0, "folder": "footage/talk"}]}),
            encoding="utf-8")
        (self.folder / produce.BRIEF_FILE).write_text(json.dumps(BRIEF), encoding="utf-8")

    def prepared(self) -> Path:
        request = produce.reference_session(self.folder, self.reference)
        for name, document in (("analysis.json", ANALYSIS), ("concepts.json", CONCEPTS)):
            (request.parent / name).write_text(json.dumps(document), encoding="utf-8")
        return request

    def test_the_reference_is_measured_for_the_agent_to_look_at(self):
        request = produce.reference_session(self.folder, self.reference)
        self.assertEqual(request.name, "analysis-request.md")
        self.assertIn("Detected pacing", request.read_text(encoding="utf-8"))
        timings = json.loads((self.folder / reference.FOLDER / "source-timings.json").read_text(encoding="utf-8"))
        self.assertEqual(timings, {"talk.mp4": {"pauses": [{"start": 1.0, "end": 1.6}], "words": []}})

    def test_a_second_session_is_refused_rather_than_written_over(self):
        produce.reference_session(self.folder, self.reference)
        with self.assertRaises(reference.AgentVideoError) as cm:
            produce.reference_session(self.folder, self.reference)
        self.assertIn("already", str(cm.exception))

    def test_the_agents_concepts_are_checked_and_listed(self):
        self.prepared()
        self.assertEqual([c["id"] for c in reference.concepts(self.folder)], ["two-beats", "one-take"])

    def test_one_concept_is_not_enough(self):
        request = self.prepared()
        (request.parent / "concepts.json").write_text(json.dumps({"version": 1, "concepts": CONCEPTS["concepts"][:1]}),
                                                      encoding="utf-8")
        with self.assertRaises(reference.AgentVideoError):
            reference.concepts(self.folder)

    def test_the_chosen_concept_becomes_the_storyboard(self):
        self.prepared()
        path = produce.use_concept(self.folder, "two-beats")
        board = json.loads(path.read_text(encoding="utf-8"))
        validate(board, "storyboard")
        self.assertEqual(path, self.folder / produce.STORYBOARD_FILE)
        self.assertEqual([(s["visual"]["start"], s["visual"]["end"]) for s in board["scenes"]], [(0.0, 1.3), (1.3, 4.0)])

    def test_a_sample_keeps_only_the_opening_scenes(self):
        self.prepared()
        board = json.loads(produce.use_concept(self.folder, "two-beats", sample=2).read_text(encoding="utf-8"))
        self.assertEqual([(s["visual"]["start"], s["visual"]["end"]) for s in board["scenes"]], [(0.0, 1.3)])
        # Then the whole concept, in a handoff of its own.
        board = json.loads(produce.use_concept(self.folder, "two-beats").read_text(encoding="utf-8"))
        self.assertEqual(len(board["scenes"]), 2)

    def test_a_concept_that_is_not_there_is_refused(self):
        self.prepared()
        with self.assertRaises(reference.AgentVideoError):
            produce.use_concept(self.folder, "three-beats")


if __name__ == "__main__":
    unittest.main()
