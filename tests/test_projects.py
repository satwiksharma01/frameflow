"""A creator's projects: folders, the catalog of worlds, its checks, and the requests for new worlds."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import projects
from project.media import _find_tool

CARE_LABEL = """---
{"id": "care-label", "name": "Care label", "family": "print", "lineage": "Woven garment labels.",
 "tags": ["label", "fabric", "minimal"], "source": "proposed"}
---
## Form
The reel reads like the garment's own label. Second sentence.
## Cut
Cuts land on downbeats.
## Camera
Still frames, tight on fabric.
## Type
Small condensed label type where a tag sits.
## Grade
True colour.
## Sound
The song and fabric sounds.
## Signature move
Label lines change with each cut.
"""


class _Projects(unittest.TestCase):
    """A temporary folder standing in for projects/."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.object(projects, "PROJECTS_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestProjects(_Projects):
    def test_a_new_project_has_an_empty_catalog(self):
        projects.new("satwik", "Satwik's reels")
        self.assertEqual(projects.load("satwik")["name"], "Satwik's reels")
        self.assertEqual(projects.index("satwik"), "(no worlds yet)")
        with self.assertRaises(projects.ProjectError):
            projects.new("satwik", "again")
        with self.assertRaises(projects.ProjectError):
            projects.new("Bad Slug", "x")

    def test_the_index_has_one_line_per_world_and_no_bodies(self):
        projects.new("p", "P")
        (self.dir / "p" / "worlds" / "care-label.md").write_text(CARE_LABEL, encoding="utf-8")
        line = projects.index("p")
        self.assertEqual(line, "- `care-label` · Care label · print: The reel reads like the garment's own label.")

    def test_a_hand_edited_world_is_named_with_its_problem(self):          # Review Focus 1
        projects.new("p", "P")
        worlds = self.dir / "p" / "worlds"
        (worlds / "broken.md").write_text("---\n{not json\n---\n## Form\nx\n", encoding="utf-8")
        (worlds / "short.md").write_text(CARE_LABEL.replace("care-label", "short").replace("## Sound\nThe song and fabric sounds.\n", ""), encoding="utf-8")
        problems = projects.check("p")
        self.assertTrue(any("broken" in p and "front matter" in p for p in problems))
        self.assertTrue(any("short" in p and "Sound" in p for p in problems))
        with self.assertRaises(projects.ProjectError):
            projects.worlds("p")

    def test_the_digest_follows_the_catalog(self):
        projects.new("p", "P")
        empty = projects.digest("p")
        (self.dir / "p" / "worlds" / "care-label.md").write_text(CARE_LABEL, encoding="utf-8")
        self.assertNotEqual(projects.digest("p"), empty)
        self.assertEqual(projects.digest(None), "")

    def test_a_drop_moves_the_world_aside(self):
        projects.new("p", "P")
        (self.dir / "p" / "worlds" / "care-label.md").write_text(CARE_LABEL, encoding="utf-8")
        projects.drop("p", "care-label")
        self.assertEqual(projects.worlds("p"), [])
        self.assertTrue((self.dir / "p" / "worlds" / "dropped" / "care-label.md").exists())


class TestNewWorlds(_Projects):
    def test_propose_asks_for_seven_worlds_across_three_families(self):
        projects.new("p", "P")
        request = projects.propose("p").read_text(encoding="utf-8")
        self.assertIn("creative/world-format.md", request)
        self.assertIn("at least three families", request)
        self.assertIn('"source": "proposed"', request)

    def test_a_reel_becomes_a_sheet_its_cuts_and_a_request(self):
        projects.new("p", "P")
        reel = self.dir / "reel.mp4"           # 4 s: 2 s red then 2 s blue, with a 330 Hz tone
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y",
                        "-f", "lavfi", "-i", "color=red:s=180x320:d=2", "-f", "lavfi", "-i", "color=blue:s=180x320:d=2",
                        "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
                        "-filter_complex", "[0][1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2", "-shortest", str(reel)],
                       check=True)
        request = projects.from_reel("p", reel).read_text(encoding="utf-8")
        study = self.dir / "p" / "reels" / "reel"
        self.assertTrue((study / "sheet.jpg").stat().st_size > 0)
        cuts = json.loads((study / "study.json").read_text(encoding="utf-8"))["cuts"]
        self.assertTrue(any(abs(t - 2.0) < 0.2 for t in cuts))
        self.assertTrue((study / "tempo.json").is_file())
        self.assertIn('"source": "reel"', request)
        self.assertIn(reel.resolve().as_posix(), request)

    def test_a_video_without_a_direction_cannot_become_a_world(self):
        projects.new("p", "P")
        with self.assertRaises(projects.ProjectError):
            projects.from_video("p", self.dir / "no-such-video")


if __name__ == "__main__":
    unittest.main()
