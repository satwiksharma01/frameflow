# The Taste Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a direction step between brief and storyboard. Frameflow's code rolls a committed direction from the creator's project catalog, or from fresh candidates, and the storyboard follows it as a contract.

**Architecture:** Two new modules beside `produce.py`. `project/projects.py` owns the creator's projects (a git-ignored `projects/<slug>/` with `project.json`, an optional brand kit and `worlds/<id>.md`). `project/direction.py` owns the direction step: requests, checks, the seeded roll, the printed hand, choose, re-roll and pin. `produce.py` gains CLI flags and calls into both. Frameflow's own knowledge is plain Markdown in `creative/`, which agents read on demand. The engine never calls a model; it writes requests and checks answers, as the brief and storyboard stages do.

**Tech Stack:** Python 3.13, `unittest`, `jsonschema` (already a dependency), ffmpeg (CI installs it on both runners).

**Spec:** `docs/superpowers/specs/2026-11-22-taste-engine-design.md` (research: `docs/superpowers/specs/2026-11-22-creative-engine-research.md`)

**One departure from the spec, for Satwik to confirm:** the spec says a world from a reel "runs the existing reference analysis". Agent Video's `reference-prepare` measures a reference *against a video's prepared media and brief*, and a project has neither. So `from-reel` makes its own study of the reel instead: a contact sheet, the cut times and the tempo, from ffmpeg and `beats`. The agent writes the world from that. Same outcome, no Node dependency, and no fake brief.

## Global Constraints

- The repository is public: `projects/` is git-ignored, and nothing a creator writes into it is committed.
- No new dependencies. A world file's front matter is a JSON object between two `---` lines, not YAML: PyYAML is not in `requirements.txt`.
- Requests carry the catalog **index** and file **paths**, never world bodies or the `creative/` files themselves.
- Without `direction.json`, `storyboard_request.md` is exactly what it is today; the app is not touched.
- The roll is reproducible: the same brief, catalog, round and register always give the same lead and challengers.
- Every test runs on CI (Ubuntu and Windows, ffmpeg and Node 22 installed, no OpenShot, Piper or Pillow). Tests run with `python -m unittest discover -s tests -p "<file>"`.
- Keep each file's own line endings (new files: LF; `docs/findings.md` and `README.md` are CRLF).
- No commits without Satwik's word. Each task ends with its files ready; when he says "commit", stage and commit by path (`git add -- <paths>`, `git commit -F msg -- <paths>`), with no Co-Authored-By line.
- Names fixed by the spec: modes `stop`, `show`, `persuade`, `teach`, `tell`; world families `print`, `screen`, `music`, `broadcast`, `interface`, `ritual`; world sections `Form`, `Cut`, `Camera`, `Type`, `Grade`, `Sound`, `Signature move`; world `source` one of `proposed`, `reel`, `video`, `creator`; seven candidates, three or more families, at most one literal; at most three challengers; one pick card at most; one standard card always.
- Inside a project with unshown worlds, the catalog leads (Satwik, 2026-11-22). Candidates lead only with no project, an empty or used-up catalog, or a bolder re-roll.

## Review Focus

1. **A world file the creator hand-edited badly** (front matter not JSON, a section missing): `projects check` and the direction step name the file and the problem; nothing crashes with a traceback. Pinned in Task 3.
2. **`--direction` before the brief is confirmed** (open questions remain): refused with the same message the storyboard gives. Pinned in Task 7.
3. **Re-rolling after a choice:** `--reroll` after `--choose` moves `direction.json` aside with the round, so the storyboard never reads a stale direction. Pinned in Task 6.
4. **A video whose project was deleted** (`inputs.json` names a slug with no folder): `--direction`, `--storyboard` and `--build` say "project <slug> is not in projects/" instead of a traceback. Pinned in Task 7.
5. **The catalog changes mid-round** (a world added after the roll): the hand is still checked against `roll.json`'s lead and challengers, not a fresh roll. Pinned in Task 6.

---

## File structure

| File | Responsibility |
|---|---|
| `project/schema/world.schema.json` | a world file's front matter |
| `project/schema/project.schema.json` | `project.json` |
| `project/schema/candidates.schema.json` | the framing and candidates the agent writes |
| `project/schema/hand.schema.json` | the hand the agent writes |
| `project/schema/direction.schema.json` | the chosen direction, the contract |
| `project/schema/brief.schema.json` | gains optional `mode` |
| `project/validate.py` | registers the five new kinds |
| `creative/INDEX.md`, `modes.md`, `calibration.md`, `world-format.md` | Frameflow's knowledge, read on demand |
| `project/projects.py` | projects: new, load, worlds, check, index, digest, drop, brand file, requests (propose, from a reel, from a video), CLI |
| `project/direction.py` | the direction step: state, requests, checks, roll, hand text, choose, re-roll, pin, the storyboard's Direction section |
| `project/hyperframes.py` | `kit_file(path)`: use a project's brand kit for a block of work |
| `project/produce.py` | `--project`, `--direction`, `--choose`, `--reroll`, `--pin`; `mode` in the brief request; the Direction section; the project's brand kit |
| `.gitignore` | `projects/` |
| `.claude/skills/produce/SKILL.md`, `.claude/skills/project/SKILL.md` | the agent's procedure |
| `tests/test_projects.py`, `tests/test_direction.py`, `tests/test_produce.py` | tests |

A video's direction files live in `<video folder>/direction/`. They are `request.md`, `candidates.json`, `roll.json`, `hand_request.md`, `hand.json` and `state.json`, and earlier rounds sit in `direction/round-<n>/`. The chosen `direction.json` sits in the video folder itself, beside `brief.json`.

---

### Task 1: Schemas

**Files:**
- Create: `project/schema/world.schema.json`, `project.schema.json`, `candidates.schema.json`, `hand.schema.json`, `direction.schema.json`
- Modify: `project/schema/brief.schema.json` (add `mode`), `project/validate.py:20-30` (`SCHEMA_FILES`)
- Test: `tests/test_direction.py` (class `TestSchemas`)

**Interfaces:**
- Produces: kinds `"world"`, `"project"`, `"candidates"`, `"hand"`, `"direction"` for `project.validate.validate(document, kind)`.
- Shapes, all `additionalProperties: false`, every string `minLength: 1` unless noted:
  - `world`: required `id` (pattern `^[a-z0-9][a-z0-9-]{0,62}$`), `name`, `family` (enum of the six), `lineage`, `tags` (array of strings, `minItems: 3`), `source` (enum of the four); optional `avoid` (array of strings), `references` (array of strings).
  - `project`: required `name`; optional `about`, `audience`, `goals` (strings, may be empty), `platforms`, `commitments` (arrays of strings).
  - `candidates`: required `framing` {`mechanism`, `viewer_scene`, `cultural_home`, `must_prove`, `rut` {`default`, `opposite`}} and `candidates` (array, may be empty) of {`id` (slug pattern), `name`, `family` (enum), `why`, `how`, `literal` (boolean)}.
  - `hand`: required `cards` (array, `minItems: 2`) of {`id`, `kind` (enum `lead`, `challenger`, `pick`, `standard`), `source` (string: a world id or candidate id; `"standard"` for the standard card), `name`, `thesis`, `own_world`, `story`, `first_two_seconds`, `signature_move`, `honest_risk`; optional `verdict` (enum `wins`, `competitive`, `declined`), `kept` (string), `raises` (array of {`from`, `discipline`})}.
  - `direction`: required `name`, `thesis`, `own_world`, `story`, `first_two_seconds`, `signature_move`, `source` {`kind` (enum `world`, `candidate`, `pin`, `standard`), optional `id`}, `seed` (string pattern `^[0-9a-f]{16}$` or null), `pinned` (boolean); optional `world_path` (string).
  - `brief.mode`: optional, enum `stop`, `show`, `persuade`, `teach`, `tell`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

`BRIEF` is the same dict as in `tests/test_produce.py`. `CONTRACT` is a module constant in `tests/test_direction.py` holding the five contract fields (`thesis`, `own_world`, `story`, `first_two_seconds`, `signature_move`) as short strings.

- [ ] **Step 2: Run, expect FAIL** (`unknown document kind 'world'`): `python -m unittest discover -s tests -p test_direction.py`
- [ ] **Step 3: Write the five schemas, add `mode` to the brief schema, and register the kinds in `SCHEMA_FILES`.**
- [ ] **Step 4: Run, expect PASS; then run `test_produce.py` and `test_app_think.py` to confirm the brief change broke nothing.**

---

### Task 2: Frameflow's creative knowledge

**Files:**
- Create: `creative/INDEX.md`, `creative/modes.md`, `creative/calibration.md`, `creative/world-format.md`
- Test: `tests/test_direction.py` (class `TestKnowledge`)

**Interfaces:**
- Produces: `creative/modes.md` with one `## <Mode>` heading per mode (`## Stop`, `## Show`, `## Persuade`, `## Teach`, `## Tell`), which requests point at as `creative/modes.md#<mode>`; `creative/INDEX.md` with one line per other file.

Content, in Frameflow's own words, from the spec and the research doc (sections 3.1 to 3.5). Copy nothing from Impeccable or the playbook sources.
- **`modes.md`:** for each mode, what success is for the viewer, how far a world may reach, what the first two seconds must do, and two or three questions worth asking (never values, never style menus).
- **`calibration.md`:** the AI-video habits from the spec's list; the over-used caption and title faces (Montserrat, Bebas Neue, Anton, Poppins, Impact, Arial Black, Inter as a title face, the short-form apps' default caption faces); the test sentence verbatim: "If the edit could be guessed from the category alone, or from the category plus what it avoids, rework it."; and "Your first instinct for a grade and a caption style is the category's; treat it as spent."
- **`world-format.md`:** the file format, the JSON front matter fields and the seven sections; the six families with an example each; what makes a world a working system rather than a costume (a world gives disciplines, never filters); the care-label world from the research doc as a complete example file.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run, expect FAIL** (no `creative/INDEX.md`; `world_problems` arrives in Task 3, so the second test fails until then).
- [ ] **Step 3: Write the four files.**
- [ ] **Step 4: Run the first test, expect PASS.** The second passes after Task 3.

---

### Task 3: Projects: folders, worlds and checks

**Files:**
- Create: `project/projects.py`
- Modify: `.gitignore` (add `projects/` under a comment naming it the creator's own, like `brand/`)
- Test: `tests/test_projects.py`

**Interfaces:**
- Consumes: kinds `world`, `project` (Task 1).
- Produces:
  - `PROJECTS_DIR: Path` (`REPO_ROOT / "projects"`; tests patch it); `SECTIONS = ("Form", "Cut", "Camera", "Type", "Grade", "Sound", "Signature move")`
  - `class ProjectError(Exception)`
  - `@dataclass(frozen=True) class World: id: str; front: dict; sections: dict[str, str]; path: Path`
  - `new(slug: str, name: str) -> Path`: makes `projects/<slug>/worlds/` and `project.json` `{"name": name, "about": "", "audience": "", "goals": "", "platforms": [], "commitments": []}`. It refuses a slug not matching `^[a-z0-9][a-z0-9-]{0,62}$`, and a project that already exists.
  - `load(slug: str) -> dict`: the validated `project.json`. Raises `ProjectError(f"project {slug} is not in projects/")` when there's no folder.
  - `parse_world(text: str) -> tuple[dict, dict[str, str]]`: the JSON front matter between the first two `---` lines, and the `## ` sections by heading. Raises `ProjectError` with the JSON error on bad front matter.
  - `world_problems(file_id: str, text: str) -> list[str]`: everything wrong with one world file, each item naming `file_id`. Covers unparsable front matter, a schema failure, `id` not equal to `file_id`, and a missing or empty section.
  - `worlds(slug: str) -> list[World]`: valid worlds in `worlds/*.md` (not `dropped/`), sorted by id. It raises `ProjectError` listing every problem if any file has one.
  - `check(slug: str) -> list[str]`: `load` problems plus every `world_problems`, with no raise.
  - `index(slug: str) -> str`: one line per world, `` - `care-label` · Care label · print: <first sentence of Form, cut at 160 characters> ``, or `"(no worlds yet)"`.
  - `digest(slug: str | None) -> str`: SHA-256 over each world's id and file bytes, sorted by id; `""` for `None`.
  - `drop(slug: str, world_id: str) -> Path`: moves `worlds/<id>.md` to `worlds/dropped/<id>.md`. It refuses an unknown id, and when the target already exists it adds a numeric suffix rather than overwriting.
  - `brand_file(slug: str | None) -> Path | None`: `projects/<slug>/brand.json` when it exists.
  - `main()` subcommands `new <slug> --name`, `check <slug>` (prints problems or the index; exit 1 on problems), `drop <slug> <id>`. Task 4 adds three more.

- [ ] **Step 1: Write the failing tests**

```python
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

class TestProjects(unittest.TestCase):
    # setUp: a TemporaryDirectory patched in as projects.PROJECTS_DIR
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
```

- [ ] **Step 2: Run, expect FAIL** (no module `project.projects`): `python -m unittest discover -s tests -p test_projects.py`
- [ ] **Step 3: Implement `project/projects.py` with the interfaces above; add `projects/` to `.gitignore`.**
- [ ] **Step 4: Run `test_projects.py` and `test_direction.py`, expect PASS** (Task 2's second test now passes too).

---

### Task 4: Projects: proposing worlds, and worlds from a reel or a video

**Files:**
- Modify: `project/projects.py`
- Test: `tests/test_projects.py`

**Interfaces:**
- Consumes: `load`, `index`, `PROJECTS_DIR` (Task 3); `project.media._find_tool`; `project.beats.beats`, `beats.tempo`.
- Produces (each writes and returns `projects/<slug>/worlds_request.md`):
  - `propose(slug: str) -> Path`. The request holds `project.json` and the current index, and points at `creative/world-format.md` and `creative/calibration.md`. It asks for about seven worlds from the audience's culture: at least three families, at most one that takes the project's own subject literally, none built from the creator's own tools. Each world goes to `worlds/<id>.md` with `"source": "proposed"`, then `python -m project.projects check <slug>`.
  - `from_reel(slug: str, video: Path) -> Path`. It writes `projects/<slug>/reels/<video stem>/contact.jpg` with ffmpeg: 2 frames a second, 240 px wide, 10 across, each frame's time drawn with `drawtext` using `C:/Windows/Fonts/arial.ttf` or `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`, whichever exists, and no times when neither does. It writes `cuts.json`, `{"cuts": [seconds, ...]}`, from ffmpeg `select='gt(scene,0.3)',showinfo` parsed for `pts_time`. When the reel has sound it writes `tempo.json` from `beats`. The request points at those three files and asks for **one** world, `"source": "reel"`, with the reel's path in `references`.
  - `from_video(slug: str, folder: Path) -> Path`. It reads `<folder>/direction.json` and `<folder>/storyboard.json`, raising `ProjectError` if either is missing, and asks for one world written from what was built, `"source": "video"`.
  - `main()` gains `propose <slug>`, `from-reel <slug> <video>`, `from-video <slug> <folder>`.

- [ ] **Step 1: Write the failing tests**

```python
    def test_propose_asks_for_seven_worlds_across_three_families(self):
        projects.new("p", "P")
        request = projects.propose("p").read_text(encoding="utf-8")
        self.assertIn("creative/world-format.md", request)
        self.assertIn("at least three families", request)
        self.assertIn('"source": "proposed"', request)

    def test_a_reel_becomes_a_contact_sheet_cuts_and_a_request(self):
        projects.new("p", "P")
        reel = self.dir / "reel.mp4"           # 4 s: 2 s red then 2 s blue, with a 330 Hz tone
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y",
                        "-f", "lavfi", "-i", "color=red:s=180x320:d=2", "-f", "lavfi", "-i", "color=blue:s=180x320:d=2",
                        "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
                        "-filter_complex", "[0][1]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2", "-shortest", str(reel)],
                       check=True)
        request = projects.from_reel("p", reel).read_text(encoding="utf-8")
        study = self.dir / "p" / "reels" / "reel"
        self.assertTrue((study / "contact.jpg").stat().st_size > 0)
        cuts = json.loads((study / "cuts.json").read_text(encoding="utf-8"))["cuts"]
        self.assertTrue(any(abs(t - 2.0) < 0.2 for t in cuts))
        self.assertIn('"source": "reel"', request)

    def test_a_video_without_a_direction_cannot_become_a_world(self):
        projects.new("p", "P")
        with self.assertRaises(projects.ProjectError):
            projects.from_video("p", self.dir / "no-such-video")
```

- [ ] **Step 2: Run, expect FAIL** (`no attribute 'propose'`).
- [ ] **Step 3: Implement the three functions and subcommands.**
- [ ] **Step 4: Run `test_projects.py`, expect PASS.**

---

### Task 5: The roll

**Files:**
- Create: `project/direction.py` (the roll only)
- Test: `tests/test_direction.py` (class `TestRoll`)

**Interfaces:**
- Consumes: `projects.World` (Task 3).
- Produces:
  - `seed_key(brief: dict, catalog_digest: str, round_no: int, register: str) -> str`: SHA-256 hex of `json.dumps(brief, sort_keys=True)`, the digest, the round and the register, joined with `"\n"`.
  - `seed_reference(key: str) -> str`: `key[:16]`.
  - `catalog_leads(worlds: list[World], shown: set[str], register: str) -> bool`: True when any world id is not in `shown` and `register != "bolder"`.
  - `rank(items: list[dict], key: str, salt: str) -> list[dict]`: items ordered by SHA-256 of `key + salt + item["id"]`, descending, ties by id.
  - `roll(key: str, worlds: list[World], candidates: list[dict], shown: set[str], register: str) -> dict`. It returns `{"lead": {"kind": "world" | "candidate", "id": str}, "challengers": [world ids]}`.
    - **Catalog leads:** rank the unshown worlds (salt `"lead"`); the first leads, and up to **two** more challenge it.
    - **Otherwise:** rank the unshown candidates (salt `"lead"`); the first leads, and up to **three** unshown worlds (salt `"deal"`) challenge it.
    - **Challenger choice:** one per family before any family repeats, counting the lead's family as taken.
    - **Raises** `ValueError` when nothing unshown can lead.

- [ ] **Step 1: Write the failing tests**

```python
def _world(id, family):
    return projects.World(id=id, front={"id": id, "name": id, "family": family}, sections={}, path=Path(f"{id}.md"))

CANDIDATES = [{"id": f"c{n}", "name": f"C{n}", "family": f, "why": "w", "how": "h", "literal": False}
              for n, f in enumerate(["print", "screen", "music", "ritual", "print", "screen", "music"])]

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
```

- [ ] **Step 2: Run, expect FAIL** (no module `project.direction`).
- [ ] **Step 3: Implement the five functions.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 6: The direction step

**Files:**
- Modify: `project/direction.py`
- Test: `tests/test_direction.py` (class `TestDirectionStep`)

**Interfaces:**
- Consumes: Task 5's roll; `projects.load`, `worlds`, `index`, `digest` (Task 3); `validate`.
- Produces:
  - `class DirectionError(Exception)`; `DIRECTION_FILE = "direction.json"`, `WORK = "direction"`.
  - `state(folder: Path) -> dict`: `direction/state.json` or the default `{"round": 0, "register": "plain", "shown": [], "rerolls_in_a_row": 0}`.
  - `advance(folder: Path, brief: dict, inputs: dict) -> tuple[str, Path | None]`: does the next thing and returns `(message, path)`. The message is what the CLI prints; the path is the file written, if any.
    - **`direction.json` exists:** validate it; return `"Direction: <name>"`.
    - **No `direction/candidates.json`:** write `direction/request.md` and return its path. The request holds the brief, `project.json` (or "no project"), the paths `creative/INDEX.md` and `creative/modes.md#<brief mode or "choose one">`, the catalog index, the framing procedure, and the seven-candidates procedure **only when `catalog_leads` is false**. On a bolder round, "foreign forms only, at full commitment". On a safer round, "the most conventional rendition, measured against named competitors". After two re-rolls in a row, a line telling the agent to ask the creator what quality is missing.
    - **No `direction/roll.json`:** validate `candidates.json`, then `check_candidates`; on problems raise `DirectionError` listing them. Roll, write `roll.json` `{"seed": <reference>, "round": n, "register": r, "lead": ..., "challengers": [...], "shown_before": [...]}`, write `direction/hand_request.md` and return it. The hand request holds the lead (its world file path, or the candidate as JSON), each challenger's world file path, and the rules from the spec's step 2, verbatim in substance.
    - **No `direction/hand.json`:** return a message telling the agent to write it.
    - **Hand written:** validate, then `check_hand(hand, roll)`; return `hand_text(hand)`.
  - `check_candidates(doc: dict, asked: bool) -> list[str]`. When `asked`: exactly 7, distinct ids, at least 3 families, at most 1 `literal`. Otherwise the list must be empty.
  - `check_hand(hand: dict, roll: dict) -> list[str]`:
    - exactly one `lead` card, whose `source` equals `roll["lead"]["id"]`;
    - at most one `pick`, whose `source` is not the lead's;
    - exactly one `standard`;
    - every `challenger` card's `source` in `roll["challengers"]`, with a `verdict`;
    - at most 3 challengers with `wins` or `competitive`;
    - every `declined` challenger has `kept`, and its `source` appears as a `from` in the lead card's `raises`.
  - `hand_text(hand: dict) -> str`: the lead with its raises; then full challengers; the pick, marked "Frameflow's pick"; declined challengers as one line each, `Declined: <name> (kept: <kept>)`; the standard last; then `Choose one (--choose <card id>), re-roll (--reroll plain|safer|bolder), or pin your own (--pin "<words>").`
  - `choose(folder: Path, card_id: str) -> Path`: writes `direction.json` from the card. `source.kind` is `world` when the card's source is a world id in `roll.json`, `standard` for the standard card, `candidate` otherwise; `seed` comes from `roll.json`, `pinned` is false, and `world_path` is the world file's path for a world. It refuses an unknown card id.
  - `reroll(folder: Path, register: str) -> Path`:
    - moves `request.md`, `candidates.json`, `roll.json`, `hand_request.md`, `hand.json` and any `direction.json` into `direction/round-<n>/`;
    - adds the round's lead and challengers to `shown`, increments `round` and `rerolls_in_a_row`, and sets `register`;
    - returns the new `request.md` (via `advance`).
  - `pin(folder: Path, words: str, brief: dict) -> Path`: writes `direction/request.md` asking the agent to write `direction.json` from the words, with `pinned: true`, `seed: null` and `source.kind` `pin`.
  - `storyboard_section(folder: Path) -> str`: `""` with no `direction.json`. Otherwise `"## Direction\n\n"` plus the contract fields, labelled, then `world_path` when present, then four rules:
    1. the storyboard follows the contract;
    2. its first two seconds are as written;
    3. "anything the storyboard cannot say yet is left out, not imitated, and listed after the script for the creator";
    4. the brand kit's font and colours bind titles, cards and captions and the direction works within them; only when the kit names no font does the direction's face come in, through an overlay composition with its font file copied beside it.

- [ ] **Step 1: Write the failing tests** (a temporary video folder with `inputs.json` and the confirmed `BRIEF`; `projects.PROJECTS_DIR` patched to a temporary folder)

```python
class TestDirectionStep(unittest.TestCase):
    def test_a_project_s_request_asks_for_framing_only_and_carries_the_index_not_bodies(self):
        # project "p" with care-label and 29 more worlds; inputs.json names it
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
        # advance to the hand, then write a new world file into the catalog, then check the same hand
        ...
        self.assertEqual(direction.check_hand(hand, json.loads((self.video / "direction" / "roll.json").read_text())), [])

    def test_choose_writes_the_contract_and_reroll_moves_it_aside(self):          # Review Focus 3
        # advance through candidates and hand, choose the lead
        path = direction.choose(self.video, "lead")
        chosen = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(chosen["source"]["kind"], "world")
        self.assertRegex(chosen["seed"], "^[0-9a-f]{16}$")
        direction.reroll(self.video, "bolder")
        self.assertFalse((self.video / "direction.json").exists())
        self.assertTrue((self.video / "direction" / "round-0" / "direction.json").exists())
        self.assertIn("foreign forms only", (self.video / "direction" / "request.md").read_text(encoding="utf-8"))

    def test_two_rerolls_in_a_row_ask_what_is_missing(self):
        ...
        self.assertIn("ask the creator what quality is missing", request)

    def test_the_storyboard_section_is_empty_without_a_direction(self):
        self.assertEqual(direction.storyboard_section(self.video), "")
```

`FRAMING` is a module constant with every framing field filled. `card(kind, source, **extra)` builds a card with every contract field set to `"x"`, `id` equal to `kind` for lead and standard and to `source` otherwise, and `name` equal to `source`. The bodies marked `...` follow the comment above them: drive `advance` by writing the agent's files the same way.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement the interfaces above.**
- [ ] **Step 4: Run `test_direction.py`, expect PASS.**

---

### Task 7: Produce: projects, mode, the Direction section, the brand kit and the CLI

**Files:**
- Modify: `project/produce.py` (`prepare`, `brief_request`, `storyboard_request`, `build`, `main`), `project/hyperframes.py` (add `kit_file`)
- Test: `tests/test_produce.py` (class `TestRequests` and a new `TestDirectionInProduce`)

**Interfaces:**
- Consumes: `projects.load`, `projects.brand_file` (Task 3); `direction.advance`, `choose`, `reroll`, `pin`, `storyboard_section` (Task 6).
- Produces:
  - `hyperframes.kit_file(path: Path | None)`: a context manager that sets `BRAND_FILE` to `path` for its block when `path` is not None, and restores it.
  - `prepare(..., project: str | None = None)`: calls `projects.load(project)` first, so an unknown project is refused before any transcription, and records `inputs["project"] = project` (or omits the key when `None`).
  - `brief_request` gains one line under "How": "- Set `mode` to what success is for the viewer: one of stop, show, persuade, teach, tell, as `creative/modes.md` describes them."
  - `storyboard_request` appends `direction.storyboard_section(folder)` as its own part before the `## How` part. It and `build` run inside `with hyperframes.kit_file(projects.brand_file(inputs.get("project"))):`, and a missing project raises `ProduceError(f"project {slug} is not in projects/")`.
  - CLI:
    - `--project SLUG` (with `--prepare`);
    - stages `--direction`, `--choose CARD`, `--reroll [plain|safer|bolder]` (`nargs="?"`, `const="plain"`), and `--pin WORDS`, each reading the confirmed brief through `_confirmed_brief`;
    - every stage prints its message and `Next: read <path>` when a path came back;
    - `main`'s `except` clause also catches `projects.ProjectError` and `direction.DirectionError`, so they end as a message, not a traceback.

- [ ] **Step 1: Write the failing tests**

```python
class TestDirectionInProduce(unittest.TestCase):
    def test_an_unknown_project_is_refused_at_prepare(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(projects, "PROJECTS_DIR", Path(tmp) / "projects"):
            with self.assertRaises(projects.ProjectError):
                produce.prepare(Path(tmp) / "v", "p", None, [], [], [], project="nobody")

    def test_a_known_project_is_recorded(self):
        ...  # projects.new("p", "P"); prepare(..., project="p"); inputs["project"] == "p"

    def test_the_brief_request_asks_for_a_mode(self):
        inputs = {"prompt": "p", "script": None, "footage": [], "assets": [], "music": []}
        self.assertIn("creative/modes.md", produce.brief_request(Path("C:/v"), inputs))

    def test_the_storyboard_request_carries_a_chosen_direction_and_nothing_without_one(self):
        ...  # write inputs.json and brief.json; request without direction.json has no "## Direction";
             # write a valid direction.json; request now contains "## Direction" and the thesis

    def test_direction_is_refused_before_the_brief_is_confirmed(self):              # Review Focus 2
        ...  # brief with open_questions; run main(["<folder>", "--direction"]) and expect SystemExit naming the question

    def test_a_deleted_project_is_named_not_a_traceback(self):                       # Review Focus 4
        ...  # inputs.json names "gone"; storyboard_request raises ProduceError "project gone is not in projects/"

    def test_the_project_s_brand_kit_is_used(self):
        ...  # project with brand.json {"accent": "#FF3366"}; the storyboard request contains "#FF3366"
```

Bodies marked `...` follow their comment. Test `main` by patching `sys.argv` and catching `SystemExit`, as the module's other CLI tests do, or call the stage function directly where `main` adds nothing.

- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run `test_produce.py`, `test_direction.py`, `test_projects.py` and `test_app_think.py`, expect PASS.** The existing request tests must pass unchanged: that is the "unchanged without a direction" check.

---

### Task 8: The skills, and a check on a real reel

**Files:**
- Modify: `.claude/skills/produce/SKILL.md`
- Create: `.claude/skills/project/SKILL.md`
- Modify: `docs/roadmap.md`, keeping its line endings: one entry for the creative engine (piece 1 of 6) and its status

**Interfaces:**
- Consumes: every CLI from Tasks 3, 4, 6 and 7.

**The `produce` skill:**
- **Prepare** gains: pass `--project <slug>` when the user works in a project.
- **The brief** gains: set `mode`.
- A new step 3, **Direction**, between Brief and Storyboard:
  1. Run `--direction`, read `direction/request.md` in full, and write `direction/candidates.json`.
  2. Run `--direction` again, read `direction/hand_request.md` in full, read the files it names, and write `direction/hand.json`.
  3. Run `--direction` again and show the user the hand it prints. **Wait for them to choose, re-roll or pin.** Run `--choose`, `--reroll` or `--pin` accordingly.
  4. Skip the step when the user pinned a reel through `--reference`, or asked for the plain standard (then `--choose standard` from a hand).
- **Storyboard** gains: follow the Direction section.
- The line "The user approves twice" becomes three times.

**The new `project` skill:**
- **Frontmatter:** name `project`. Description: "Make or change a Frameflow project - a creator's channel, page or series with its own catalog of video worlds - acting as the editor yourself. Use when the user wants a project for their channel or page, new worlds proposed for it, a world added from a reel or from a video they liked, or a world dropped."
- **Steps:** `new`, then fill in `project.json` with the user; `propose`, then write the worlds, `check`, and show them so the user keeps or drops each; `from-reel`; `from-video`; `drop`.
- **Rules:** worlds in Frameflow's own words, references as links or paths, never copied media.

- [ ] **Step 1: Write both skills and the roadmap entry.**
- [ ] **Step 2: Run the whole engine suite, expect every test to pass:** `python -m unittest discover -s tests`
- [ ] **Step 3: A check on a real reel, acting as the editor, on scratch copies.**
  - **Setup:** make a scratch project (`projects/scratch-check`) by hand with two world files, then a scratch video folder prepared from the four outfit clips and NOBLE with `--project scratch-check`.
  - **Run:** go through `--direction` to a hand, `--choose`, `--storyboard` and `--build`.
  - **Expect:** the hand prints a catalog world as the lead, with challengers. `storyboard_request.md` carries the Direction section. The build succeeds.
  - **Report and clean up:** report the hand and a contact sheet of the preview to Satwik, then delete only the scratch project and scratch video this step made.
