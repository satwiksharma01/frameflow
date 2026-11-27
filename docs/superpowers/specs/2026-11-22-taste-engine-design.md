# The taste engine: a direction step for every video

**Date:** 2026-11-22 · **Status:** design, for Satwik's approval · **Piece 1 of 6** of the creative engine (2: new edits in the engine; 3: the craft playbooks; 4: checking the result; 5: refine commands; 6: the app) · **Research:** [2026-11-22-creative-engine-research.md](2026-11-22-creative-engine-research.md)

## Intent

Frameflow's videos come out competent and generic: each lands on what its category always looks like. The outfit reel of 2026-11-22 was centred white text, a warm film grade and cuts on the beat, which could all be guessed from "outfit reel" alone. Impeccable solves the same problem for web pages by making the AI name the category default, dig for directions in the audience's culture, let a seeded roll choose instead of the AI's habit, commit to one direction, and write it down as a contract. This piece brings that engine to Frameflow, so every video gets a committed direction that is not the category default, and a creator's own taste lives in their projects.

## Goals

- Every video made through the produce flow can get a **direction**: a short contract the storyboard follows (thesis, own world, story, first two seconds, signature move).
- The direction comes from a **direction round**: the rut named, candidates dug from the audience's culture, a seeded roll, challengers from the creator's catalog, one hand for the creator to choose from.
- A creator can make a **project** (a channel, a page, a series) holding their own **catalog of worlds** and brand kit; videos made in it draw from that catalog.
- Worlds enter a catalog three ways: proposed by Frameflow when the project is made, written from a reel the creator points at, or written from a video they made and liked.
- The creator can always pin a direction in words or with a reel, take the plain standard, or re-roll safer or bolder.

## Non-goals

- New kinds of edit (zooms, ramps, transitions, sound effects): piece 2. A world here can change only what the storyboard can already say: which shots, in what order and length, cut to the beat or not, the grade, any type HyperFrames can set as titles, cards and an overlay, captions on or off, music level.
- The craft playbooks: piece 3. Measuring the build against the contract, a video detector, a fresh-eyes critic: piece 4. Refine commands: piece 5. Anything in the app: piece 6. The app keeps working exactly as today.
- A catalog of worlds shipped with Frameflow. Catalogs belong to creators.
- Tracking trends.

## Anti-goals

- A menu of styles ("minimal, bold or playful?"). Directions are derived, rolled and argued, never picked from a list of adjectives.
- The AI silently choosing its own favourite. The roll is done by Frameflow's code, from a recorded seed.
- Worlds as costumes: a VHS filter on everything, a copied reference. A world is a working system; a challenger gives the lead a discipline, never its clothes.
- A creator's taste in the public repository.
- A nine-second reel that takes longer to choose than to make: one round, one hand, one choice.

## Constraints

- The repository is public. Projects live in a git-ignored folder, as the brand kit already does.
- Thinking works with Claude Code, OpenCode or an API key. The engine writes requests and checks answers; it never calls a model itself (as the brief and storyboard stages already work).
- Token budget: requests carry indexes and paths, never whole knowledge files or catalogs. The agent reads what it needs.
- CI runs every test on Ubuntu and Windows without OpenShot, Piper or Pillow; nothing here may need them.
- Each file keeps its own line endings.
- Worlds describe styles in Frameflow's own words; references are links or local paths, never copied media.

## Approaches considered

1. **A direction step between brief and storyboard, the roll in Frameflow's code (chosen by Satwik, 2026-11-22).** Two thinker answers with the engine's roll between them: candidates, then the hand. Works with every thinker, is truly random and testable, and a re-roll does not redo the brief. Costs one more step per video.
2. **Inside the plan (brief).** One fewer step, but the look and what the video is are approved together, and changing the look reworks the plan.
3. **Only in the storyboard request, no roll.** Cheapest; the AI picks its own favourite every time, which is the convergence this exists to break, and the creator gets no choice.

## The design

### Words

| Word | Meaning |
|---|---|
| **Mode** | What success is for the viewer: **Stop** (scroll shorts), **Show** (outfit, mood, product looks), **Persuade** (pitch, ad), **Teach** (explainer, demo), **Tell** (vlog, story). The brief records it. |
| **World** | An editing style treated as a working system: how it cuts, frames, sets type, grades, sounds, and its one signature move, with where it comes from. |
| **Project** | A creator's channel, page or series: who they are, their brand kit, their catalog of worlds. Optional. |
| **Rut** | What this kind of video always looks like, and its predictable opposite. Both are excluded. |
| **Framing** | What the AI writes first for every video: its mechanism, the viewer's scene, the audience's cultural home, what the first two seconds must prove, and the rut. |
| **Candidates** | Seven directions the AI digs from the audience's culture, when no catalog leads: a one-off video, an empty or used-up catalog, or a bolder re-roll. |
| **Roll** | Frameflow's seeded choice of what leads and what challenges it: inside a project, worlds from its catalog; otherwise, the candidates. |
| **Hand** | What the creator sees: the lead, challengers with verdicts, the AI's own pick, the plain standard. |
| **Direction** | The chosen card, as a contract the storyboard follows. |
| **Pin** | A direction the creator gives in words or with a reel; it skips the roll. |

### Where things live

**Frameflow's knowledge, in the repository:** a new `creative/` folder at the root.

| File | Holds |
|---|---|
| `creative/INDEX.md` | One line per file below, read first |
| `creative/modes.md` | The five modes: what success is, how far a world may go, what the first two seconds must do, the questions worth asking |
| `creative/calibration.md` | The AI-video habits to treat as spent (centred captions with a yellow word on everything, a push-in on every still, a whoosh on every cut, a teal-and-orange or warm-film grade by default, stock B-roll under corporate music, neon title cards, letterbox plus slow motion as "cinematic"); the over-used caption and title faces; the test: if the edit could be guessed from the category alone, or from the category plus what it avoids, rework it |
| `creative/world-format.md` | How to write a world, its families, and one worked example |

**A creator's projects, git-ignored:** `projects/<slug>/`.

| File | Holds |
|---|---|
| `project.json` | name, about (who the creator is and what they make), audience, platforms, goals, commitments (standing rules such as "never a voiceover") |
| `brand.json` and its font and logo files | optional; the same schema as today's `brand/brand.json`, used for this project's videos instead of it |
| `worlds/<id>.md` | one world per file |
| `worlds/dropped/` | worlds the creator dropped, kept so a drop can be undone |

### A world file

Front matter, checked against a new `world` schema:

- `id` (the file name), `name`;
- `family`, one of: `print` (magazines, zines, lookbooks, catalogues, labels), `screen` (film, television, title sequences), `music` (music videos, performance, record culture), `broadcast` (sport, news, live graphics), `interface` (devices, apps, signage), `ritual` (places and ceremonies: a fitting room, a drop queue, a runway);
- `lineage`: where it comes from, in a sentence;
- `tags` (three or more), `avoid` (what it must never become);
- `source`: `proposed`, `reel`, `video` or `creator`;
- `references`: links or local paths, optional.

Then seven sections, each a few lines: **Form** (how it works, one or two sentences), **Cut** (shot lengths, rhythm, what a cut lands on), **Camera** (framing and stillness; moves wait for piece 2), **Type** (faces, where text sits, how it behaves), **Grade** (a strategy, then a look), **Sound** (the music's role, silence), **Signature move**. The check refuses a world missing a section.

### The brief

The brief schema gains an optional `mode` (`stop`, `show`, `persuade`, `teach`, `tell`). The brief request asks for it, with a pointer to `creative/modes.md`. A video made in a project has its project slug in `inputs.json`, set by `--prepare ... --project <slug>`.

### The direction step

`python -m project.produce <folder> --direction`, run after the brief is confirmed, does the next thing each time it is run:

1. **Nothing written yet:** writes `direction_request.md`. It holds the brief, the project's `project.json`, the paths of `creative/INDEX.md` and the mode's section, the project's **catalog index** (one line per world: id, name, family, the first sentence of its Form), and the procedure:
   - **framing**, always: name the video's mechanism in a sentence, the viewer's real scene, the audience's cultural home, and what the first two seconds must prove; name the rut, what this kind of video always looks like and its predictable opposite;
   - **candidates**, only when no catalog leads this round (no project, an empty or used-up catalog, or a bolder re-roll): seven from the audience's culture, each with a name, family, why it resonates and can carry this video, and how it looks, moves and sounds; at least three families; at most one that takes the brief's own picture literally; none built from the creator's own tools of the trade;
   - write both to `candidates.json` (an empty candidate list when the catalog leads).
2. **Framing written, not yet rolled:** checks it (every framing field filled; when candidates were asked for, exactly seven, distinct ids, three or more families, at most one marked literal, every field filled), then **rolls** (below), writes `roll.json`, and writes `hand_request.md`. That request names the lead (a world's file path, or a candidate), the challenger worlds' file paths to read, and the rules:
   - render the lead for this video: the world supplies form and grammar, the video supplies every fact, and the rut stays out;
   - fuse each challenger the same way;
   - judge each on two axes only, whether the audience recognises itself and whether the video's point is clear;
   - verdict: **wins** (beats the lead on both), **competitive** (holds one), **declined** (loses both);
   - a declined challenger gives the lead one named discipline, written as a raise line; never a surface trick;
   - add **one** pick card for the AI's own first choice when the roll did not assign it: the catalog world it would have chosen for this video, or its top candidate;
   - add the **standard card**: the category default played straight, never recommended;
   - every card is a full contract: thesis (and the default it refuses), own world (grade, type voice, caption system, cut rhythm, sound; recognisable with the content removed), story, first two seconds, signature move, honest risk;
   - apply the calibration test to the lead before writing;
   - write `hand.json`.
3. **Hand written:** checks it (one assigned card, at most one pick, one standard card, at most three full challenger cards, every contract field filled) and prints it for the creator: the lead with its raises, the full challengers, the pick, declined challengers as one line each, the standard last, then the choices.

Then:

- `--choose <card>` writes `direction.json`: the chosen card's contract, its source (a candidate or a world id), the seed reference, and whether it was pinned.
- `--reroll [plain|safer|bolder]` starts the next round. Every card already shown is out. **Plain** rolls again over what is left: the catalog's unshown worlds in a project, the unshown candidates otherwise, and seven new candidates when nothing is left. **Safer** asks for the most conventional rendition of what is left, and the standard, measured against named competitors. **Bolder** asks for seven fresh candidates of foreign forms only, at full commitment; in a project they lead, and the catalog's worlds challenge them. After two re-rolls in a row, the request tells the agent to ask the creator what quality is missing.
- `--pin "<words>"` skips the roll: `direction_request.md` asks the agent to write `direction.json` from the creator's words, marked pinned. The existing `--reference` path is already a pin and needs no direction.

### The roll

All in Frameflow's code, reproducible:

- `seed_key` = SHA-256 of the brief's contents, the project's catalog (the sorted ids and contents of its world files), the round number and the register. The **seed reference** is its first 16 hex characters, recorded in `roll.json` and `direction.json`.
- **Rank** a pool by SHA-256 of `seed_key` and each item's id, highest first.
- **Inside a project whose catalog has unshown worlds (the catalog leads, Satwik, 2026-11-22):** rank the catalog's unshown worlds; the first leads, and up to two more challenge it, one per family before any family repeats. A catalog of one world gives a lead and no challengers.
- **Otherwise** (no project, an empty or used-up catalog, or a bolder re-roll): rank the unshown candidates; the first leads. In a project, up to three of its worlds challenge it, chosen the same way; with no project there are no challengers.
- The same inputs always give the same roll.

### The storyboard with a direction

When `direction.json` exists, `storyboard_request.md` adds a **Direction** section: the contract as written, the path of its world file when it came from a catalog, and three rules. The storyboard follows the contract; its first two seconds are as written; and anything the storyboard cannot say yet is left out rather than imitated, listed under the storyboard's script for the creator. That last rule covers moves that wait for piece 2. Without `direction.json`, the request is exactly today's, so the app and older folders are unchanged.

**The brand kit wins where it speaks.** A project's brand kit (or `brand/`) is a commitment the creator made: its font and colours bind titles, cards and captions, and a direction translates its type voice into them (placement, size, case, behaviour) rather than replacing them. Where the kit says nothing, the face is the direction's own, set through an overlay composition with its font file copied into the composition's folder, as the storyboard request already allows. *(Frameflow's call, following Impeccable's rule that pinned brand commitments beat the roll.)*

### Projects

`python -m project.projects`:

- `new <slug> --name "<name>"` makes the folder and a `project.json` to fill in with the creator.
- `propose <slug>` writes `worlds_request.md`, asking the agent to dig about seven worlds from the project's audience and culture with the same rules as candidates. It writes each as a world file, `source: proposed`. The creator keeps or drops them.
- `from-reel <slug> <video>` runs the existing reference analysis on the reel. Then `worlds_request.md` asks for one world file from what the analysis found, `source: reel`, with the reel in `references`.
- `from-video <slug> <folder>` asks for one world file from a finished video's `direction.json` and storyboard, `source: video`.
- `drop <slug> <id>` moves a world to `worlds/dropped/`.
- `check <slug>` validates everything and prints the catalog index.

`--prepare --project <slug>` checks that the project exists and records it, and the build then uses the project's brand kit when it has one.

### The skills

- **`produce`:** a new step 3, **Direction**, between Brief and Storyboard. It runs the round, shows the hand, and writes the creator's choice, re-roll or pin. It skips the round when the creator pinned a reel or asked for the plain standard.
- **A new `project` skill:** make a project with the creator, propose its first worlds, add a world from a reel or from a video they liked, drop one.

### What the creator sees

In chat, one hand:

```
Lead (rolled): Care label  ·  thesis: the reel reads like the garment's own label, not a caption over a bedroom
  own world: true colour; small condensed label type where a tag sits; cuts land on downbeats; song plus fabric sounds
  first two seconds: collar and placket, a label line stamped on the first downbeat
  signature move: the label lines change with each cut, like flipping a tag
  raised by Skate tape: commit to one rhythm for the whole reel
Challenger, competitive: Contact sheet  ·  ...
Frameflow's pick: Lookbook page  ·  ...  (risk: where most outfit reels land)
Declined: Skate tape (kept: one rhythm)
The standard: centred title, warm grade, cuts on the beat
Choose one, re-roll (safer / bolder), or tell me the direction yourself.
```

## Tests

- **The roll:** the same inputs give the same roll; a different round gives a different one; in a project the lead is a catalog world, and no candidates are asked for; a bolder re-roll asks for candidates, which then lead with catalog challengers; an empty or used-up catalog falls back to candidates; challengers span families before repeating; no project gives no challengers; shown cards never return after a re-roll.
- **The checks:** framing refused with a field missing; candidates, when asked for, refused with six, with duplicate ids, with two families, or with two literal candidates; a hand refused with two pick cards, with no standard card, or with a card missing a contract field; a world file refused with a missing section, an unknown family or fewer than three tags.
- **Token budget:** requests carry the catalog index and paths, not world bodies or knowledge files; a project of 30 worlds keeps `direction_request.md` under a fixed size.
- **Unchanged without a direction:** `storyboard_request.md` with no `direction.json` is byte-for-byte today's; with one, it carries the contract.
- **Projects:** `new`, `check`, `drop` and the index on a temporary folder; `--prepare --project` refuses an unknown project and records a known one; the build uses the project's brand kit.

## Left to the builder

File and function names beyond those given here, the exact wording of the requests, how `roll.json` and `hand.json` are laid out within the fields named, and how the printed hand wraps.

## Decided with Satwik

- **Inside a project, the catalog leads** (2026-11-22): the roll deals the lead from the project's own worlds, so a channel stays recognisably itself; fresh candidates from the audience's culture lead only on a bolder re-roll, or when the catalog is empty or used up. This departs from Impeccable, where fresh candidates always lead and the catalog only challenges.
- The direction step, not the plan, carries the look (2026-11-22).
- Projects are optional, each with its own catalog; worlds come from Frameflow's proposals when a project is made and from reels the creator adds (2026-11-22).

## Frameflow's calls, for Satwik to check

- The five modes and their names: Stop, Show, Persuade, Teach, Tell.
- Seven candidates, at least three families, at most three challengers, one pick card, the standard card always shown: Impeccable's numbers.
- Projects in a git-ignored `projects/` folder at the repository root, like `brand/`; Frameflow's own knowledge in `creative/`.
- The brand kit wins where it speaks (above).
- Six world families: print, screen, music, broadcast, interface, ritual.
- A dropped world is moved aside, not deleted, so a drop can be undone.
