"""The taste engine's direction step: its schemas, the roll, the requests and checks, and the storyboard's contract."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import direction, projects
from project.transcribe import REPO_ROOT
from project.validate import ValidationError, validate
from test_produce import BRIEF
from test_projects import CARE_LABEL

CONTRACT = {"thesis": "The reel reads like the garment's own label, not a caption over a bedroom.",
            "own_world": "True colour; small condensed label type where a tag sits; cuts on downbeats.",
            "story": "Collar, placket, the full fit, the label.",
            "first_two_seconds": "Collar and placket, a label line stamped on the first downbeat.",
            "signature_move": "The label lines change with each cut, like flipping a tag."}


def _world(id, family):
    return projects.World(id=id, front={"id": id, "name": id, "family": family}, sections={}, path=Path(f"{id}.md"))


CANDIDATES = [{"id": f"c{n}", "name": f"C{n}", "family": f, "why": "w", "how": "h", "literal": False}
              for n, f in enumerate(["print", "screen", "music", "ritual", "print", "screen", "music"])]

FRAMING = {"mechanism": "An outfit shown piece by piece.", "viewer_scene": "Scrolling on a phone, sound on.",
           "cultural_home": "Menswear forums and shop floors.", "must_prove": "That the fit is worth a look.",
           "rut": {"default": "Centred white text, a warm grade, a cut on every beat.",
                   "opposite": "Black and white slow motion with a piano."}}

FAMILIES = ["print", "screen", "music", "broadcast", "interface", "ritual"]


def card(kind, source, **extra):
    """A card with every contract field filled."""
    return {"id": kind if kind in ("lead", "standard") else source, "kind": kind, "source": source, "name": source,
            **{f: "x" for f in ("thesis", "own_world", "story", "first_two_seconds", "signature_move", "honest_risk")},
            **extra}


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


class TestSchemas(unittest.TestCase):
    def test_a_world_needs_three_tags_and_a_known_family(self):
        world = {"id": "care-label", "name": "Care label", "family": "print", "lineage": "Garment labels.",
                 "tags": ["label", "type", "minimal"], "source": "proposed"}
        validate(world, "world")
        for broken in ({**world, "tags": ["a", "b"]}, {**world, "family": "film"}, {**world, "source": "ai"}):
            with self.assertRaises(ValidationError):
                validate(broken, "world")

    def test_the_brief_takes_a_mode(self):
        validate({**BRIEF, "mode": "show"}, "brief")
        with self.assertRaises(ValidationError):
            validate({**BRIEF, "mode": "dance"}, "brief")

    def test_a_direction_has_a_16_hex_seed_or_none(self):
        direction = {**CONTRACT, "name": "Care label", "source": {"kind": "world", "id": "care-label"},
                     "seed": "0123456789abcdef", "pinned": False}
        validate(direction, "direction")
        validate({**direction, "seed": None, "pinned": True, "source": {"kind": "pin"}}, "direction")
        with self.assertRaises(ValidationError):
            validate({**direction, "seed": "xyz"}, "direction")


class TestKnowledge(unittest.TestCase):
    def test_the_index_lists_every_file_and_each_mode_has_a_section(self):
        creative = REPO_ROOT / "creative"
        index = (creative / "INDEX.md").read_text(encoding="utf-8")
        for name in ("modes.md", "calibration.md", "world-format.md"):
            self.assertIn(name, index)
        modes = (creative / "modes.md").read_text(encoding="utf-8")
        for mode in ("Stop", "Show", "Persuade", "Teach", "Tell"):
            self.assertIn(f"\n## {mode}\n", modes)
        self.assertIn("or from the category plus what it avoids", (creative / "calibration.md").read_text(encoding="utf-8"))

    def test_the_example_world_in_the_format_guide_passes_the_check(self):
        text = (REPO_ROOT / "creative" / "world-format.md").read_text(encoding="utf-8")
        example = text.split("```markdown\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(projects.world_problems("care-label", example), [])


class TestRoll(unittest.TestCase):
    def test_the_same_inputs_give_the_same_roll_and_another_round_differs(self):
        worlds = [_world(f"w{n}", f) for n, f in enumerate(["print", "screen", "music", "ritual", "interface"])]
        key = direction.seed_key(BRIEF, "d", 0, "plain")
        self.assertEqual(direction.roll(key, worlds, [], set(), "plain"), direction.roll(key, worlds, [], set(), "plain"))
        rounds = {json.dumps(direction.roll(direction.seed_key(BRIEF, "d", n, "plain"), worlds, [], set(), "plain"))
                  for n in range(6)}
        self.assertGreater(len(rounds), 1)

    def test_in_a_project_a_world_leads_with_two_challengers_of_other_families(self):
        worlds = [_world("a", "print"), _world("b", "print"), _world("c", "screen"), _world("d", "music")]
        dealt = direction.roll(direction.seed_key(BRIEF, "d", 0, "plain"), worlds, [], set(), "plain")
        self.assertEqual(dealt["lead"]["kind"], "world")
        self.assertEqual(len(dealt["challengers"]), 2)
        families = {w.id: w.front["family"] for w in worlds}
        picked = [dealt["lead"]["id"], *dealt["challengers"]]
        self.assertEqual(len({families[i] for i in picked}), 3)

    def test_bolder_or_a_used_up_catalog_lets_candidates_lead(self):
        worlds = [_world("a", "print"), _world("b", "screen")]
        key = direction.seed_key(BRIEF, "d", 1, "bolder")
        self.assertFalse(direction.catalog_leads(worlds, set(), "bolder"))
        self.assertFalse(direction.catalog_leads(worlds, {"a", "b"}, "plain"))
        dealt = direction.roll(key, worlds, CANDIDATES, set(), "bolder")
        self.assertEqual(dealt["lead"]["kind"], "candidate")
        self.assertLessEqual(len(dealt["challengers"]), 3)

    def test_no_project_means_no_challengers_and_shown_never_return(self):
        key = direction.seed_key(BRIEF, "", 0, "plain")
        first = direction.roll(key, [], CANDIDATES, set(), "plain")
        self.assertEqual(first["challengers"], [])
        again = direction.roll(key, [], CANDIDATES, {first["lead"]["id"]}, "plain")
        self.assertNotEqual(again["lead"]["id"], first["lead"]["id"])


class TestDirectionStep(unittest.TestCase):
    """A video folder with its confirmed brief and inputs, in project p: care-label and 29 more worlds."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        patcher = mock.patch.object(projects, "PROJECTS_DIR", root / "projects")
        patcher.start()
        self.addCleanup(patcher.stop)
        projects.new("p", "P")
        self.worlds = root / "projects" / "p" / "worlds"
        (self.worlds / "care-label.md").write_text(CARE_LABEL, encoding="utf-8")
        for n in range(29):
            self._add_world(f"w{n:02d}", FAMILIES[n % 6])
        self.video = root / "video"
        self.inputs = {"prompt": "an outfit reel", "script": None, "footage": [], "assets": [], "music": [], "project": "p"}
        _write(self.video / "inputs.json", self.inputs)
        _write(self.video / "brief.json", BRIEF)

    def _add_world(self, id, family):
        text = CARE_LABEL.replace("care-label", id).replace('"Care label"', f'"World {id}"').replace('"print"', f'"{family}"')
        (self.worlds / f"{id}.md").write_text(text, encoding="utf-8")

    def _to_hand(self, inputs=None, candidates=()):
        """Frame (with these candidates), roll, and write a hand of the lead and the standard."""
        inputs = inputs or self.inputs
        direction.advance(self.video, BRIEF, inputs)
        _write(self.video / "direction" / "candidates.json", {"framing": FRAMING, "candidates": list(candidates)})
        direction.advance(self.video, BRIEF, inputs)
        rolled = json.loads((self.video / "direction" / "roll.json").read_text(encoding="utf-8"))
        hand = {"cards": [card("lead", rolled["lead"]["id"]), card("standard", "standard")]}
        _write(self.video / "direction" / "hand.json", hand)
        return rolled, hand

    def test_a_project_s_request_asks_for_framing_only_and_carries_the_index_not_bodies(self):
        message, path = direction.advance(self.video, BRIEF, self.inputs)
        request = path.read_text(encoding="utf-8")
        self.assertIn("`care-label` · Care label · print", request)
        self.assertNotIn("Label lines change with each cut", request)       # a world body
        self.assertNotIn("seven candidates", request)
        self.assertLess(len(request), 14000)

    def test_without_a_project_seven_candidates_are_asked_for(self):
        _, path = direction.advance(self.video, BRIEF, {**self.inputs, "project": None})
        self.assertIn("seven candidates", path.read_text(encoding="utf-8"))

    def test_candidates_are_checked(self):
        doc = {"framing": FRAMING, "candidates": CANDIDATES[:6]}
        self.assertTrue(direction.check_candidates(doc, asked=True))
        dup = {"framing": FRAMING, "candidates": CANDIDATES[:6] + [dict(CANDIDATES[0])]}
        self.assertTrue(any("distinct" in p for p in direction.check_candidates(dup, asked=True)))
        literal = [dict(c, literal=(n < 2)) for n, c in enumerate(CANDIDATES)]
        self.assertTrue(direction.check_candidates({"framing": FRAMING, "candidates": literal}, asked=True))
        self.assertEqual(direction.check_candidates({"framing": FRAMING, "candidates": CANDIDATES}, asked=True), [])

    def test_a_hand_is_checked_against_its_roll(self):
        roll = {"lead": {"kind": "world", "id": "a"}, "challengers": ["b"], "seed": "0" * 16}
        good = {"cards": [card("lead", "a", raises=[{"from": "b", "discipline": "one rhythm"}]),
                          card("challenger", "b", verdict="declined", kept="one rhythm"),
                          card("standard", "standard")]}
        unraised = {"cards": [card("lead", "a")] + good["cards"][1:]}
        self.assertTrue(direction.check_hand(unraised, roll))      # a declined challenger must raise the lead
        self.assertEqual(direction.check_hand(good, roll), [])
        two_picks = {"cards": good["cards"] + [card("pick", "c"), card("pick", "d")]}
        self.assertTrue(direction.check_hand(two_picks, roll))
        no_standard = {"cards": good["cards"][:2]}
        self.assertTrue(direction.check_hand(no_standard, roll))

    def test_a_world_added_mid_round_does_not_change_the_hand_s_check(self):      # Review Focus 5
        rolled, hand = self._to_hand()
        self._add_world("zz-new", "music")
        self.assertEqual(direction.check_hand(hand, json.loads((self.video / "direction" / "roll.json").read_text())), [])
        text, _ = direction.advance(self.video, BRIEF, self.inputs)
        self.assertIn(rolled["lead"]["id"], text)

    def test_choose_writes_the_contract_and_reroll_moves_it_aside(self):          # Review Focus 3
        self._to_hand()
        path = direction.choose(self.video, "lead")
        chosen = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(chosen["source"]["kind"], "world")
        self.assertRegex(chosen["seed"], "^[0-9a-f]{16}$")
        direction.reroll(self.video, "bolder")
        self.assertFalse((self.video / "direction.json").exists())
        self.assertTrue((self.video / "direction" / "round-0" / "direction.json").exists())
        self.assertIn("foreign forms only", (self.video / "direction" / "request.md").read_text(encoding="utf-8"))

    def test_two_rerolls_in_a_row_ask_what_is_missing(self):
        direction.advance(self.video, BRIEF, self.inputs)
        direction.reroll(self.video, "plain")
        request = (self.video / "direction" / "request.md").read_text(encoding="utf-8")
        self.assertNotIn("ask the creator what quality is missing", request)
        direction.reroll(self.video, "plain")
        request = (self.video / "direction" / "request.md").read_text(encoding="utf-8")
        self.assertIn("ask the creator what quality is missing", request)

    def test_a_plain_reroll_without_a_project_rolls_the_candidates_left(self):
        alone = {**self.inputs, "project": None}
        _write(self.video / "inputs.json", alone)
        first, _ = self._to_hand(alone, CANDIDATES)
        path = direction.reroll(self.video, "plain")
        self.assertEqual(path.name, "hand_request.md")       # no new candidates asked for: rolled over the rest
        again = json.loads((self.video / "direction" / "roll.json").read_text(encoding="utf-8"))
        self.assertNotEqual(again["lead"]["id"], first["lead"]["id"])

    def test_a_pin_skips_the_roll(self):
        path = direction.pin(self.video, "like a skate video on tape", BRIEF)
        request = path.read_text(encoding="utf-8")
        self.assertIn("like a skate video on tape", request)
        self.assertIn('"pinned": true', request)
        self.assertEqual(direction.advance(self.video, BRIEF, self.inputs)[1], path)   # not overwritten by a roll

    def test_the_storyboard_section_is_empty_without_a_direction(self):
        self.assertEqual(direction.storyboard_section(self.video), "")

    def test_the_storyboard_section_carries_the_contract_and_its_rules(self):
        self._to_hand()
        direction.choose(self.video, "lead")
        section = direction.storyboard_section(self.video)
        self.assertTrue(section.startswith("## Direction\n\n"))
        self.assertIn("left out, not imitated, and listed after the script for the creator", section)
        self.assertIn(".md", section)                       # the world file it came from


if __name__ == "__main__":
    unittest.main()
