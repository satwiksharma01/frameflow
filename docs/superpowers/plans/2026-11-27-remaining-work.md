# What is left, and how each piece is done

**Date:** 2026-11-27 · **State:** the eyes (stage 1) and the taste engine are built and committed on `taste-engine` (`ec841ba`, `8f8febe`, `c768449`), not pushed. This is the order of everything still open, each piece with the skills that carry it. Only the fix pass (phase 1) is specified enough to plan task by task now: `2026-11-27-fix-pass.md`. Every other piece starts with its own design, because each holds decisions only Satwik can make.

## How every piece is run

The same flow as the app's plans, the eyes and the taste engine:

1. **Design:** `superpowers:brainstorming` writes the spec in `docs/superpowers/specs/`, one question at a time, until Satwik approves it. For anything the creator sees in the app, `impeccable` shapes it first, and nothing is saved or built without his confirm.
2. **Plan:** `superpowers:writing-plans` turns the approved spec into tasks, each with its tests.
3. **Build:** Satwik picks the method. `superpowers:executing-plans` (one implementer in the session) or `superpowers:subagent-driven-development` (a fresh implementer and reviewer per task). Either way `superpowers:test-driven-development` governs each step and `superpowers:verification-before-completion` each claim.
4. **Review:** one review of the whole branch at the end, through `superpowers:requesting-code-review` (a fresh reviewer when Satwik asks for one; otherwise a self-review, said as such).
5. **Land:** `superpowers:finishing-a-development-branch`. Commit only at Satwik's word, by path, with no co-author line; push only at his word. Then the vault (status, the milestone, findings, runs) and a short progress note.

Rules that hold throughout: the repository is public, so no personal paths in commits; each file keeps its own line endings; tests run on CI without OpenShot, Piper voices, Pillow or the speech model; no real API key is ever typed or stored by an agent; the creator's own videos are only read, and checks run on scratch copies that are deleted afterwards.

---

## Phase 0: land what is built, and the open calls (Satwik)

| Step | What | Skill |
|---|---|---|
| 0.1 | Push `taste-engine` and open a pull request against `master`; CI runs every test on Ubuntu and Windows for the first time on the eyes and the taste engine. Merge when green, at Satwik's word | `superpowers:finishing-a-development-branch`; the app's pull-request tools for CI |
| 0.2 | Confirm: a world from a reel is written from the eyes' study of it, not Agent Video's analysis | — |
| 0.3 | Decide: does a clip's own sound play under the music? (vault: pending decision) | — |
| 0.4 | Place his own files: the staged `.agents/skills/edit` and `first-cut` deletions, `.claude/agents/`, `.claude/launch.json`, `.claude/skills/impeccable/` | — |
| 0.5 | Order phase 3's engine features, and share any playbooks beyond the four already given, for phase 4.2 | — |

## Phase 1: the fix pass (planned)

Every known defect with a clear fix, in one branch: `docs/superpowers/plans/2026-11-27-fix-pass.md`, 7 tasks.

- A speech-model error ends as a message in `produce`, `first_cut` and `shorts`, not a traceback.
- A study made before the speech model was installed is made again once it is.
- A recording's speech is measured once, not twice.
- Repeating `--footage`, `--asset`, `--music` or `--look` adds the files up.
- A clip stored on its side is listed at the size it plays.
- A direction round keeps what it asked for when the catalog changes mid-round.
- `--reroll` always names its register.

**Skills:** `superpowers:executing-plans` or `superpowers:subagent-driven-development`, with `superpowers:test-driven-development`. **Done when:** the whole suite passes, each fix with a test that failed first, and the vault's minor findings say "fixed".

## Phase 2: the app catches up

Each a spec of its own, designed step by step under Satwik's control.

| Step | What | Skills |
|---|---|---|
| 2.1 | **The material list:** each file shows its kind; a file can be moved between Recording and Pictures or clips, or taken out. A clip with no talking, measured by the speech model, is offered as a clip. The biggest pain of run 11 | `superpowers:brainstorming`, `impeccable` (shape, then craft), `superpowers:writing-plans`, `frontend-ui-engineering`, checks in the real window (`run`) |
| 2.2 | **The direction in the app** (creative engine piece 6, part 1): pick a project on the prompt step; the hand as cards; choose, re-roll or pin | as 2.1 |
| 2.3 | **The eyes in the app:** the describe step's progress, and the look's verdict and findings beside the preview, a fix applied only on the creator's OK | as 2.1 |
| 2.4 | **A thinker through a key that sees:** send the sheets as images to a vision-capable API, so describing and looking work without Claude Code | `claude-api`, `security-and-hardening` (the key never logged or shown), `superpowers:brainstorming` |
| 2.5 | **The live check the app still lacks:** thinking with OpenCode and with a real key. Satwik enters his own key in Settings; the agent never types it | `run`, the app's own live check |

## Phase 3: the engine backlog

Each its own spec and plan, in the order Satwik picks (step 0.5). The order suggested, by what it unblocks:

| Step | What | Skills |
|---|---|---|
| 3.1 | **Punctuation on word timings**, so `edit` and `publish` break phrases at sentences, not every 20 words | `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:test-driven-development` |
| 3.2 | **Cards that keep off faces:** a card or lower third moves clear of the face the picture check already finds | as 3.1 |
| 3.3 | **A limiter**, so speech reaches -14 LUFS (OpenShot's Compressor), with `edit` keeping that effect as it keeps a look's LUT | as 3.1, plus `source-driven-development` for the effect's parameters |
| 3.4 | **`edit` that keeps more:** reorder clips (`move`), remove or change a graphic or B-roll clip by instruction, keep filters, titles and crossfades instead of refusing | as 3.1, plus `superpowers:systematic-debugging` for the project round trips |

## Phase 4: the creative engine, pieces 2 to 5

Piece 1, the taste engine, is built. The rest, from `docs/superpowers/specs/2026-11-22-creative-engine-research.md`:

| Step | What | Skills |
|---|---|---|
| 4.1 | **Piece 2, new kinds of edit:** punch-ins and zooms, speed ramps, transitions and sound effects, as OpenShot keyframes and clips the creator can still change; and **type placement**, so a world's label can sit small in a corner (run 13's missing move). The storyboard gains them, the hand may use them, and `edit` keeps them | `source-driven-development` (OpenShot's keyframes, first), `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:subagent-driven-development` |
| 4.2 | **Piece 3, the craft playbooks:** from Satwik's four playbooks and the research list, written in Frameflow's own words into `creative/` as a technique library read on demand: how a hook works, cut rates by mode, safe zones, ducking music under speech. Nothing copied from the sources | `superpowers:brainstorming`, `anthropic-skills:deep-research` where a playbook needs checking |
| 4.3 | **Piece 4, checking the result against the direction:** three options of the key frames (the first, the signature moment, the last) approved before the build, then the built frames measured against them: title position and size, the grade sampled from the frame, text in the safe zones. A detector for spent moves (the same move on every cut, word captions over no speech, a default caption face) and for a look outside the project's catalog | `superpowers:brainstorming`, `superpowers:writing-plans`; builds on the eyes' look step |
| 4.4 | **Piece 5, refine commands:** punchier, calmer, tighten, retime, regrade, retype, resound, critique, polish, each scoped to what it names ("make scene 3 punchier" touches scene 3), through the `edit` skill | as 4.3 |

## Phase 5: the eyes, stage 2

When a creator's library grows past what an agent can describe clip by clip, or describing costs too much: a shot index across the library, with CLIP search and Florence-2 descriptions (about 600 MB of models, each pinned and hash-checked like the speech model). **Skills:** `superpowers:brainstorming`, `security-and-hardening` for the downloads, `superpowers:writing-plans`.

## Phase 6: later, and outside this repository

A packaged app, its first run, a brand kit and MP4 export in the app; the optional Higgsfield connector; plugging Frameflow into Produk. Each waits for Satwik to start it.

---

## The suggested order

0 → 1 → 2.1 → 4.1 → 2.2 and 2.3 → 4.3 → 4.2 (when the playbooks are in) → phase 3 in Satwik's order → 4.4 → 2.4 and 2.5 → 5 → 6.

Why: phase 0 gets CI onto two branches of unrun work before more is stacked on it. The fix pass is small and known. 2.1 removes the pain that stopped Satwik's own first reel. 4.1 gives the directions the moves they already ask for. The app then shows what the engine can do. Checking against the direction needs both. The playbooks wait on material, and phase 3's order is Satwik's.
