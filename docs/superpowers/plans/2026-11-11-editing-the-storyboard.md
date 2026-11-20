# Editing the Storyboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The creator changes their storyboard by hand in the app, with every change undoable:
- a scene's words, its order, adding and deleting scenes;
- a scene's picture and what pops up over it;
- the chapters and the whole-video settings;
- by mouse, by dragging, by keyboard, or from a Ctrl K palette.

**Architecture:**
- **The engine makes every change.** It is a long-running process (`python -m project.app_api serve`) answering one JSON line per request. Each change is an operation applied to `storyboard.json` by `project/storyboard_edit.py`, which checks it, keeps the chapters attached to their scenes, writes the file atomically, and keeps an undo history beside it.
- **The app sends operations and shows the engine's answer.** It never writes a file itself. Only a move is shown before the answer, so a drop does not jump back.

**Tech Stack:**
- Engine: Python 3.13, `unittest`.
- App: Electron, React, TypeScript, Tailwind v4, shadcn/ui (`command`, `dialog`, `dropdown-menu`, `input`, `textarea`, `switch`, `select`, `sonner`), `@dnd-kit/core` with `@dnd-kit/sortable`, lucide-react, Vitest with React Testing Library.

**Spec:**
- `.impeccable/surfaces/app.md` (the confirmed brief; its Interaction section is this plan's scope) and `PRODUCT.md`.
- Plan 1, `docs/superpowers/plans/2026-11-10-app-shell-and-storyboard.md`, built the screen this plan makes editable. Its uncommitted work is in this checkout.

## This is plan 2 of 4

- **In this plan:** everything the brief's Interaction section asks of the storyboard:
  - the scene's words, order, add, delete, picture and what is over it;
  - undo;
  - drag;
  - arrows, Enter and Ctrl+Z;
  - the Ctrl K palette.
- **Also in this plan:**
  - renaming, keeping or removing a suggested chapter (from the approved Apple and Rams review: "chapters the editor made up are marked as suggestions you can rename or remove");
  - the footer's whole-video switches from the confirmed sketch.
- **Not in this plan:**
  - Space to play a scene, and Listen on a check. Both need the player plan 3 builds, so Space does nothing until then.
  - The prompt screen, the editor writing chapters, and changes asked for in words: plan 4.
  - Choosing music or a voice, editing the overlay, and adding a chapter: the brief does not ask for them.
  - Keeping the board's `script` in step with edited scenes: no screen shows it, and plan 4's editor rewrites it.
- **Plan 1's deferred minors** stay deferred unless Satwik asks. Where a task here rewrites code a minor touches, that behaviour must not get worse.

## Global Constraints

- Everything in plan 1's Global Constraints still holds:
  - the colours and their jobs, WCAG AA contrast, the radius scale and continuous corners;
  - targets of at least 32 px, solid surfaces, shadcn controls and lucide icons;
  - motion of 150 to 250 ms for a change of state, reduced motion;
  - CI without OpenShot, Piper or the recordings;
  - the line endings;
  - commits only if asked, by path, with no `Co-Authored-By` line.
- Every change to the storyboard can be undone. No confirm dialog anywhere: a delete shows a toast with Undo instead.
- The engine is the only writer of `storyboard.json` and `inputs.json` from the app.
- A path the creator did not pick in the app's file dialog never reaches `inputs.json`.
- Edits are applied in the order they were made, each against the version the one before it produced.
- **Drag:**
  - The dragged scene follows the pointer from the point where it was grabbed.
  - The other scenes move aside on a critically damped spring (no overshoot), about 350 ms.
  - Feedback is on press. With reduced motion, nothing slides.
- **Copy is plain:** "scene", "chapter", "your recording", "a file of yours".
  - A refusal says what happened and what stays, such as "Not said in your recording. The words stay as they were."
- Tabular figures on times only, never on body text (plan 1's ruling).

## Review Focus

Failure modes the brief implies and no screen's happy path exercises, most likely first. Each has its test in the task named.

1. **Two changes in quick succession** (Ctrl+Z pressed three times, a drag straight after an edit): each waits for the one before and uses its version. None is refused as "changed outside the app", and none is lost. (Task 6)
2. **The storyboard changed outside the app** (the command line or an editor wrote it) before an edit or an undo: the change is refused, the screen reloads, and the creator is told their last change was not made. (Tasks 3 and 6)
3. **Typed words a recording does not hold as written:**
   - words not said: refused, and the words stay;
   - words said more than once: the occurrence nearest the scene's place is used;
   - different case and punctuation: ignored;
   - no letters Frameflow can search (empty, punctuation only, or a script other than English's): refused with that reason, never matched everywhere. (Task 1)
4. **A card's or B-roll's words that the scene no longer says** after its words change: the card stays, shows from the start of the scene, and the creator is told. (Task 2)
5. **Deleting or removing the last of something:**
   - the only scene: refused, saying why;
   - a chapter's last scene: that chapter goes away;
   - the only chapter: the scenes are left with no chapters. (Task 2)

---

### Task 1: Finding words in a recording

**Files:**
- Modify: `project/cutpoints.py`
- Test: `tests/test_cutpoints.py`

**Interfaces:**
- Consumes: `find_pause`, `place_in_pause`, `frame_align` in `project/cutpoints.py`; `tokenize` in `project/verify_cuts.py`.
- Produces: `span_of(words: list[dict], pauses: list[dict], phrase: str, fps: float, near: float | None = None, length: float | None = None) -> tuple[float, float] | None`.
  - `words` and `pauses` are a `timing.json`'s.
  - It returns where `phrase` is said, as a span whose edges sit in the pauses around it, or `None` when the phrase is not said.
  - It raises `ValueError("…has no words Frameflow can search for yet")` when `tokenize(phrase)` is empty.
  - `length` is the recording's duration, which caps the end.

How the edges are placed (the steps below rely on this):
- **The words:** match `tokenize(phrase)` as a contiguous run of the tokens of `words`.
- **Several runs:** take the run whose first word starts nearest `near`, or the first run when `near` is `None`.
- **Start:** in the pause that ends where the run's first word begins (the last pause ending at or before it, and after the word before), at `place_in_pause(pause, "remove", "keep", fps)`. Without such a pause, use the frame-aligned midpoint between the word before and the first word, or 0 at the recording's start.
- **End:** in the pause that begins where the run's last word ends, at `place_in_pause(pause, "keep", "remove", fps)`. Without one, use the midpoint to the next word, or the last word's end plus 0.25 s, capped at `length`.

- [ ] **Step 1: Write the failing tests** in a new `class TestSpanOf` in `tests/test_cutpoints.py`:

```python
WORDS = [{"start": 1.0, "end": 1.3, "text": " Hello"}, {"start": 1.5, "end": 1.9, "text": " there."},
         {"start": 2.6, "end": 2.7, "text": " The"}, {"start": 2.7, "end": 3.0, "text": " goal"},
         {"start": 3.0, "end": 3.2, "text": " is"}, {"start": 10.0, "end": 10.1, "text": " the"},
         {"start": 10.1, "end": 10.4, "text": " goal"}]
PAUSES = [{"start": 0.0, "end": 1.0}, {"start": 1.9, "end": 2.6}, {"start": 3.2, "end": 3.9},
          {"start": 9.4, "end": 10.0}, {"start": 10.4, "end": 11.0}]

def test_a_phrase_is_cut_in_the_pauses_around_it(self):
    start, end = cutpoints.span_of(WORDS, PAUSES, "The goal, is", 30)
    self.assertTrue(2.3 <= start <= 2.4)          # breathing in, a quarter second before "The"
    self.assertTrue(3.4 <= end <= 3.5)            # a quarter second after "is"

def test_case_and_punctuation_are_ignored(self):
    self.assertEqual(cutpoints.span_of(WORDS, PAUSES, "the GOAL is!", 30),
                     cutpoints.span_of(WORDS, PAUSES, "The goal, is", 30))

def test_of_two_places_the_one_nearest_the_scene_wins(self):
    self.assertTrue(2.3 <= cutpoints.span_of(WORDS, PAUSES, "the goal", 30)[0] <= 2.4)
    start, end = cutpoints.span_of(WORDS, PAUSES, "the goal", 30, near=9.0)
    self.assertTrue(9.7 <= start <= 9.8 and 10.6 <= end <= 10.7)

def test_words_not_said_give_none(self):
    self.assertIsNone(cutpoints.span_of(WORDS, PAUSES, "goodbye", 30))
    self.assertIsNone(cutpoints.span_of(WORDS, PAUSES, "goal the", 30))      # said, but not in that order

def test_a_phrase_with_nothing_to_search_for_is_refused_not_found_everywhere(self):
    for phrase in ("", "  ...  ", "नमस्ते"):
        with self.assertRaises(ValueError):
            cutpoints.span_of(WORDS, PAUSES, phrase, 30)

def test_without_a_pause_the_cut_falls_between_the_words(self):
    start, end = cutpoints.span_of(WORDS, [], "goal", 30)
    self.assertAlmostEqual(start, 2.7, places=1)      # "The" ends where "goal" begins
    self.assertAlmostEqual(end, 3.0, places=1)
```

- [ ] **Step 2: Run:** `python -m unittest tests.test_cutpoints -v`. Expected: FAIL (`span_of` not defined).
- [ ] **Step 3: Implement `span_of`** in `project/cutpoints.py`, as the Interfaces block says.
- [ ] **Step 4: Run** `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5: Commit** (if asked) the two files, message "Find where words are said in a recording, cut in the pauses around them".

---

### Task 2: Changing a storyboard, one operation at a time

**Files:**
- Create: `project/storyboard_edit.py`
- Modify:
  - `project/produce.py`: extract `asset_entry` from `prepare`'s asset loop (near line 112) and call it there.
  - `project/schema/storyboard.schema.json`: a section item gains optional `"confirmed": {"type": "boolean"}`, described as "true once the creator has renamed or kept a chapter the editor suggested".
- Test: `tests/test_storyboard_edit.py`

**Interfaces:**
- Consumes:
  - `span_of` (Task 1);
  - `produce.check_storyboard`, `produce._match`, `produce._looks`, `produce.INPUTS_FILE`, `produce.STORYBOARD_FILE`, `produce.BRIEF_FILE`;
  - `first_cut.TIMING_FILE`;
  - `validate`;
  - `verify_cuts.words_in_clip`, `verify_cuts.tokenize`;
  - `media.analyze` (for a recording's fps when the brief gives none).
- Produces:
  - `produce.asset_entry(path: Path) -> dict`: `{"path", "kind": "image"}`, or `{"path", "kind": "clip", "duration", "size"}`. It raises `MediaError` for a file that is neither.
  - `class EditError(Exception)`, with `.changed: bool` (Task 3 sets it).
  - `apply(folder: Path, op: dict, chosen: list[str] = ()) -> list[str]`. It applies one operation, writes `storyboard.json` (and `inputs.json` when a file is added) atomically, and returns notes for the creator. It raises `EditError(message)` and writes nothing when the change cannot be made.
  - `said(scene: dict, folder: Path, inputs: dict) -> str`: the words a scene says (narration, else its recording's words in its span). `app_api._says` moves here.

The operations, with scene and chapter numbers counted from 1:

| `op` | fields | what it does |
|---|---|---|
| `move` | `from`, `to` | the scene numbered `from` becomes number `to` |
| `delete` | `number` | refused for the only scene: "A video needs at least one scene." |
| `add` | `after` (0 = first), `scene` | `scene` is `{"kind": "title", "text"}`, `{"kind": "file", "path"}` or `{"kind": "recording", "words"}` |
| `words` | `number`, `words` | see below |
| `title` | `number`, `text` | a title scene's words on screen; refused for any other kind |
| `over` | `number`, and any of `caption` (string or null), `cards`, `broll` | replaces those fields as given; an empty caption, list or null removes the key |
| `picture` | `number`, `path` | footage: `broll` becomes one entry covering the scene, `{"path", "duration": end - start}`, and the recording keeps playing. Any other kind: `visual` becomes `{"type": "asset", "path"}`, keeping the narration, with a duration of 3 when one is needed and none is set |
| `rename_chapter` | `number`, `title` | also sets `confirmed: true` |
| `keep_chapter` | `number` | sets `confirmed: true` |
| `remove_chapter` | `number` | its scenes join the chapter before, or the next one when it is the first |
| `video` | any of `spoken_captions`, `cut_to_beat`, `look` (a LUT's file name, or null for as shot) | `cut_to_beat` is refused when the board has no `music`; `look` must be one of `produce._looks(inputs)` by name |

Rules every operation follows:
- **`words`:**
  - On a footage scene without narration, the scene's span becomes `span_of` over its recording, with `near` the scene's current start. Not said: `EditError("Not said in your recording. The words stay as they were.")`.
  - On any other scene, `narration` becomes the words. Empty words remove it. If the scene then needs a duration it lacks, it gets 3, with the note "It now lasts 3 seconds."
- **Added scenes** get `"reason": "Added by the creator in the app"`:
  - A title gets `"duration": 2.0`.
  - A file is added to `inputs.json` with `asset_entry` when it is not there already, and an image gets `"duration": 3.0`.
  - A recording scene searches the recording of the scene at `after` first, then the others in order.
- **Paths:** a `path` not already among `inputs["assets"]` (matched as `produce._match` does) is accepted only if it is in `chosen`. Otherwise: `EditError("<name> is not one of your files.")`. A file `asset_entry` cannot read gives `EditError("Frameflow can't read <name> as a picture or a clip.")`.
- **Chapters stay attached:** before the change, each scene knows its chapter, and afterwards each chapter's `from` is its first scene's new number.
  - A moved scene joins the chapter of the scene now before it, or of the scene after it when it goes first.
  - An added scene joins the chapter of the scene at `after`.
  - A chapter left with no scenes goes away; when none are left, `sections` is removed.
- **Words a scene no longer says:** after any change, a card or B-roll whose `when` the scene no longer says (`tokenize(when)` is not a contiguous run of `tokenize(said(...))`) loses its `when` and gets the note: `Card “Nomad” now shows from the start of the scene: “Nomad” is not said in it any more.` B-roll is named by its file's name.
- **Checks:** the result must pass `validate(board, "storyboard")` and `produce.check_storyboard(board, inputs)`. Otherwise: `EditError("That change can't be made: " + "; ".join(problems))`.
- **Writing:** with `json.dumps(board, indent=2, ensure_ascii=False) + "\n"` to a temporary file in the same folder, then `os.replace`.

- [ ] **Step 1: Write the failing tests** in `tests/test_storyboard_edit.py`.
  - **The fixture:**
    - a temporary video folder with `inputs.json`: one recording `talk.mp4`, 20 s, whose `timing.json` holds Task 1's `WORDS` and `PAUSES`; one image asset; and one look, a small `.cube` file the test writes (`check_storyboard` wants the file to exist);
    - a brief with `fps: 30`;
    - a four-scene storyboard: footage 0.8–2.0, footage 2.3–3.4, a title with narration "Meet it" and no duration, footage 9.7–10.6;
    - `sections` A from 1 and B from 3.
  - **The tests:**
    - `test_a_move_renumbers_and_the_moved_scene_joins_the_chapter_it_lands_in`: move 4 to 1 gives the old order 4, 1, 2, 3, with A from 1 and B from 4.
    - `test_moving_a_chapters_first_scene_away_starts_it_at_the_next`: move 3 to 1 gives A from 1 holding the old 3, 1, 2, and B from 4 holding the old 4.
    - `test_deleting_a_chapters_last_scene_removes_the_chapter`: delete 4, then 3, and `sections` is A from 1 alone.
    - `test_the_only_scene_cannot_be_deleted`: the message is "A video needs at least one scene.", and the file is unchanged byte for byte.
    - `test_new_words_pick_the_span_where_they_are_said`: words "the goal is" on scene 1 give a span within 2.3–2.4 to 3.4–3.5, and `said()` is "The goal is".
    - `test_words_not_said_are_refused_and_nothing_changes`
    - `test_words_on_a_title_are_its_narration_and_empty_words_give_it_a_duration`: the note is "It now lasts 3 seconds."
    - `test_a_card_whose_words_leave_the_scene_shows_from_its_start`: the scene had a card with `when: "Hello"`. New words "there" drop the `when`, and the notes carry `Card “…” now shows from the start of the scene`.
    - `test_a_picture_on_footage_covers_it_with_b_roll_and_keeps_the_recording`: the visual is unchanged, and `broll == [{"path": IMAGE, "duration": 1.2}]`.
    - `test_a_picture_on_a_title_replaces_it`
    - `test_a_file_not_chosen_is_refused_and_inputs_are_unchanged`
    - `test_a_chosen_clip_is_added_to_inputs_once`: make a 2 s clip with FFmpeg; skip without FFmpeg.
    - `test_adding_from_the_recording_finds_the_words`
    - `test_adding_a_title_after_scene_2_joins_chapter_a`
    - `test_removing_the_first_chapter_gives_its_scenes_to_the_next_which_starts_at_1`
    - `test_removing_the_only_chapter_leaves_no_sections`
    - `test_renaming_a_chapter_confirms_it`
    - `test_cut_to_the_beat_without_music_is_refused`
    - `test_a_look_must_be_one_the_video_can_use`: the fixture's look is accepted by its file name; an unknown name is refused.
    - `test_a_change_that_breaks_the_storyboard_says_why_and_writes_nothing`: B-roll on the title scene through `over`.
- [ ] **Step 2: Run:** `python -m unittest tests.test_storyboard_edit -v`. Expected: FAIL (no module `project.storyboard_edit`).
- [ ] **Step 3: Implement.**
  - `asset_entry` first, and run `python -m unittest tests.test_produce` to show `prepare` is unchanged.
  - Then `storyboard_edit.py` and the schema field.
  - Move `app_api._says` into `said()`, and have `app_api` import it.
- [ ] **Step 4: Run** `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5: Commit** (if asked), message "Change a storyboard one operation at a time, keeping chapters attached".

---

### Task 3: Versions and undo

**Files:**
- Modify: `project/storyboard_edit.py`
- Test: `tests/test_storyboard_edit.py`

**Interfaces:**
- Produces:
  - `version(folder: Path) -> str`: the first 16 hex digits of the sha256 of `storyboard.json`'s bytes.
  - `edit(folder: Path, op: dict, expect: str, chosen: list[str] = ()) -> list[str]`: `apply` guarded by `expect`.
  - `undo(folder: Path, expect: str) -> None` and `redo(folder: Path, expect: str) -> None`.
  - `history(folder: Path) -> tuple[bool, bool]`: whether there is anything to undo and to redo.

How it behaves:
- When `expect != version(folder)`, these raise `EditError("The storyboard changed outside the app, so it was reloaded. Your last change was not made.", changed=True)`.
- Before `edit` writes, the bytes it replaces are pushed to `<folder>/app_cache/undo/NNNN.json`, and `app_cache/redo/` is emptied.
- `undo` pushes the current bytes to `redo/` and writes the last undo entry back. `redo` mirrors it.
- Each stack keeps its newest 200 entries.
- Nothing to undo: `EditError("Nothing to undo.")`. Nothing to redo: `EditError("Nothing to redo.")`.

- [ ] **Step 1: Write the failing tests:**
  - `test_an_edit_against_an_old_version_is_refused_as_changed`: `changed` is True, and the file is untouched.
  - `test_undo_and_redo_walk_the_history`: three edits, then undo three times, return the first bytes; redo twice returns the second edit's bytes.
  - `test_a_new_edit_after_undo_clears_redo`
  - `test_undo_past_the_beginning_says_so`
  - `test_undo_is_refused_when_the_file_changed_outside_the_app`
  - `test_the_history_survives_a_new_process`: an edit through `subprocess` running `python -c "…storyboard_edit.edit(…)"`, then `undo` in this process.
  - `test_history_keeps_the_newest_200`
- [ ] **Step 2: Run:** `python -m unittest tests.test_storyboard_edit -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5: Commit** (if asked), message "Undo and redo a storyboard's changes, and refuse one made against an old version".

---

### Task 4: A long-running engine for the app

**Files:**
- Modify: `project/app_api.py`
- Test: `tests/test_app_api.py`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces, in `describe` (Task 6 relies on these names):
  - `"version": str`, `"can_undo": bool`, `"can_redo": bool`;
  - `"video": {"spoken_captions": bool, "has_music": bool, "cut_to_beat": bool, "look": str | null}`, where `look` is the LUT's file name;
  - each section's `"confirmed": bool` (false when absent);
  - each scene's `"key"`: the first 12 hex digits of the sha256 of `json.dumps(scene["visual"], sort_keys=True)`, plus `-k` where k counts earlier scenes with the same visual;
  - each scene's `"narration": str | null`, `"caption": str | null`, `"cards": list` and `"broll": list`, as in the storyboard.
- Produces, in `videos`: each video's `"cover": str | null`, the key of its first scene.
- `thumbnail(folder: Path, key: str) -> Path | None` finds the scene by key. It replaces the scene number.
- `looks(folder: Path) -> list[str]`: the names of `produce._looks(inputs)`.
- `serve()` runs on `python -m project.app_api serve`:
  - It reads one JSON object per line from stdin, `{"id": int, "method": str, "params": {...}}`, and writes one line per request, `{"id", "result"}` or `{"id", "error"}`, flushed.
  - **Methods:**
    - `videos` `{root}`, `describe` `{folder}`, `thumbnail` `{folder, key}`, `looks` `{folder}`;
    - `edit` `{folder, op, version, chosen}`, `undo` `{folder, version}`, `redo` `{folder, version}`.
  - `edit`, `undo` and `redo` answer `{"described": describe(folder), "notes": [...]}` when the change is made, and `{"refused": message, "changed": bool}` on an `EditError`.
  - `thumbnail` runs on a `ThreadPoolExecutor(max_workers=2)`, so pictures never hold up an edit; everything else runs in order on the reading thread. Writes to stdout share one lock.
  - Any other exception answers `{"id", "error": str(e)}`, and its traceback goes to stderr only. The server keeps reading, and it exits 0 at the end of stdin.

- [ ] **Step 1: Write the failing tests** in `tests/test_app_api.py`:
  - `test_describe_gives_a_version_keys_and_the_fields_an_editor_changes`
  - `test_two_scenes_with_the_same_picture_get_different_keys`
  - `test_a_thumbnail_is_found_by_key_after_the_scenes_move`
  - `test_videos_name_their_cover`
  - **`class TestServe`** (start `python -m project.app_api serve` with `subprocess.Popen`, `text=True`, `encoding="utf-8"`):
    - `test_each_request_is_answered_by_its_id`: `describe`, `videos` and an unknown method; three lines, one an error; the process is still running.
    - `test_an_edit_answers_with_the_new_storyboard`
    - `test_a_refused_edit_says_why_and_the_server_carries_on`
    - `test_a_failing_request_does_not_stop_the_server`: `describe` on a broken folder, then `videos`.
    - `test_the_server_ends_with_its_input`: closing stdin gives exit 0 within 5 s.
- [ ] **Step 2: Run:** `python -m unittest tests.test_app_api -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Keep the `videos`, `describe` and `thumbnail` command lines working, with `thumbnail FOLDER KEY`.
- [ ] **Step 4: Run** `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5: Commit** (if asked), message "Keep the engine running for the app, answering edits as they come".

---

### Task 5: The app talks to the long-running engine

**Files:**
- Create: `app/src/main/chosen.ts`, `app/src/main/chosen.test.ts`
- Modify:
  - `app/src/main/engine.ts`, `app/src/main/engine.test.ts`;
  - `app/src/main/ipc.ts`, `app/src/preload/index.ts`;
  - `app/src/shared/types.ts`;
  - `app/src/renderer/src/storyboard/Thumbnail.tsx` and its callers.

**Interfaces:**
- Consumes: Task 4's methods and shapes.
- Produces, in `shared/types.ts`:
  - `Scene` gains `key`, `narration`, `caption`, `cards: Card[]` and `broll: Broll[]`.
  - `Section` gains `confirmed`.
  - `Described` gains `version`, `can_undo`, `can_redo` and `video: VideoSettings`.
  - `Video` gains `cover`.
  - New types:

```ts
export interface Card { kind: 'product' | 'lower_third'; text: string; subtitle?: string; price?: string; when?: string; duration?: number }
export interface Broll { path: string; when?: string; duration?: number; start?: number }
export interface VideoSettings { spoken_captions: boolean; has_music: boolean; cut_to_beat: boolean; look: string | null }
export type NewScene = { kind: 'title'; text: string } | { kind: 'file'; path: string } | { kind: 'recording'; words: string }
export type EditOp =
  | { op: 'move'; from: number; to: number } | { op: 'delete'; number: number }
  | { op: 'add'; after: number; scene: NewScene } | { op: 'words'; number: number; words: string }
  | { op: 'title'; number: number; text: string }
  | { op: 'over'; number: number; caption?: string | null; cards?: Card[]; broll?: Broll[] }
  | { op: 'picture'; number: number; path: string }
  | { op: 'rename_chapter'; number: number; title: string } | { op: 'keep_chapter'; number: number }
  | { op: 'remove_chapter'; number: number }
  | { op: 'video'; spoken_captions?: boolean; cut_to_beat?: boolean; look?: string | null }
export type EditAnswer = { described: Described; notes: string[] } | { refused: string; changed: boolean }
```

- `FrameflowApi` becomes:
  - `videos`, `describe`, `build`, `onBuildFinished` as before;
  - `thumbnail(folder, key: string)`;
  - `edit(folder, op: EditOp, version: string): Promise<EditAnswer>`;
  - `undo(folder, version): Promise<EditAnswer>`, `redo(folder, version): Promise<EditAnswer>`;
  - `looks(folder): Promise<string[]>`;
  - `chooseFile(): Promise<string | null>`.
- `Engine.json` is replaced by `call<T>(method: string, params: Record<string, unknown>): Promise<T>`:
  - It starts `serve` on the first call and again after the server exits.
  - It matches answers by `id` and rejects a call unanswered after 60 s with "The engine did not answer <method>."
  - When the server exits, every pending call is rejected with "The engine stopped: <the last 2000 characters of its stderr>".
  - `stopAll` ends the server's process tree too.
- `chosen.ts` exports:
  - `createChosen(): { add(path: string): void; list(): string[] }`;
  - `pathsIn(op: EditOp): string[]`: the `path`s an op names, from `picture`, `add` with a file, and `over` B-roll.
- `ff:choose-file` opens `dialog.showOpenDialog` with the filters Pictures (jpg, jpeg, png, webp) and Clips (mp4, mov, webm, mkv), adds the pick to `chosen`, and returns it.
- `ff:edit` passes `chosen.list()` as `chosen`; the engine refuses any other new path (Task 2).
- `Thumbnail` takes `pictureKey: string | null` instead of fetching by `number`. It caches by `${folder}|${pictureKey}`, still shows `plain ?? number` when there is no picture, and the rail passes `video.cover`.

- [ ] **Step 1: Write the failing tests.**
  - **`engine.test.ts`:** the fake engine now speaks the `serve` protocol on stdin and stdout.
    - `call resolves with the answer to its own id`
    - `two calls answered out of order each get their own answer`
    - `an error answer rejects with the engine's words`
    - `a server that dies rejects what was pending, and the next call starts a new one`
    - `a character split across two chunks of an answer arrives whole`
    - `a folder path with spaces arrives as one value`
    - `stopAll ends the server and the programs a build started` (keep plan 1's tree test)
    - plan 1's build tests, kept as they are
  - **`chosen.test.ts`:**
    - `pathsIn names a picture, a file added and each B-roll, and nothing else`
    - `a chosen path is listed once however often it is picked`
- [ ] **Step 2: Run:** `npm test` in `app/`. Expected: FAIL.
- [ ] **Step 3: Implement.** Update `ipc.ts` and the preload for every method, and route every engine request through `call`.
- [ ] **Step 4: Run** `npm test` and `npm run typecheck`. Expected: PASS and clean. Then `npm run dev`: the tier-list reel opens with its thumbnails, and the rail shows each video's cover.
- [ ] **Step 5: Commit** (if asked), message "Talk to a long-running engine, and let only files the creator picked into a video".

---

### Task 6: Changes from the screen, in order, with undo

**Files:**
- Create: `app/src/renderer/src/storyboard/useStoryboard.ts`, `app/src/renderer/src/storyboard/useStoryboard.test.tsx`
- Modify:
  - `app/src/renderer/src/storyboard/Storyboard.tsx`, which uses the hook in place of its own `load`;
  - `app/src/renderer/src/App.tsx`, which mounts shadcn's `<Toaster />` (`npx shadcn@latest add sonner`), styled to the tokens with a 16 px radius, bottom right above the footer.

**Interfaces:**
- Consumes: Task 5's API and types.
- Produces:

```ts
export interface StoryboardState {
  status: 'loading' | 'failed' | 'ready'
  described: Described | null
  message: string | null
  busy: boolean                                   // a change is on its way
  edit(op: EditOp, toast?: string): Promise<EditResult>
  undo(): Promise<void>
  redo(): Promise<void>
  reload(): void
}
export type EditResult = { ok: true; notes: string[] } | { ok: false; refused: string }
export function useStoryboard(folder: string): StoryboardState
export function selectAfter(op: EditOp, selected: number, count: number): number
```

How it behaves:
- **Order:** changes go one at a time through a promise chain. Each is sent with the version the previous answer gave.
- **Moves:** a `move` reorders `described.scenes` and renumbers them at once, so the drop holds; the engine's answer then replaces everything. Every other change waits for its answer.
- **Refused changes:**
  - With `changed`, the hook reloads and toasts the refusal.
  - Otherwise it returns `{ ok: false, refused }` for the caller to show by its field. A refused move puts the order back.
- **Toasts:** a change made with `toast` ("Scene 3 deleted", "Scene 3 moved", "Scene added", "Picture replaced", "Chapter removed") shows a sonner toast with id `edit`, so one replaces the other, with an Undo action. Notes become the toast's description, or a toast of their own when there is no `toast`.
- **`selectAfter`:**
  - move: the moved scene's new number;
  - delete: the same number, or the last scene when it was the last;
  - add: `after + 1`;
  - anything else: `selected`.
- **Undo and redo** do nothing while the matching `can_undo` or `can_redo` is false.

- [ ] **Step 1: Write the failing tests** with a fake `window.frameflow`:
  - `a change waits for the one before and is sent with that one's version` (two edits; the second call's `version` is the first answer's)
  - `three quick undos run one after another and none is refused`
  - `a move shows the new order before the engine answers`
  - `a refused move puts the order back and says why`
  - `a change refused as changed outside the app reloads and says the last change was not made`
  - `a delete with a toast offers Undo, and Undo undoes it`
  - `notes from the engine are shown`
  - `selectAfter follows a moved scene, stays put on a delete and lands on an added scene`
- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test`. Expected: PASS, with plan 1's Storyboard tests still green.
- [ ] **Step 5: Commit** (if asked), message "Make the creator's changes one at a time, each undoable".

---

### Task 7: Drag to reorder

**Files:**
- Create: `app/src/renderer/src/lib/motion.ts`, `app/src/renderer/src/lib/motion.test.ts`, `app/src/renderer/src/storyboard/reorder.ts`, `app/src/renderer/src/storyboard/reorder.test.ts`
- Modify: `app/src/renderer/src/storyboard/Storyboard.tsx`, `app/src/renderer/src/storyboard/SceneModule.tsx`

**Interfaces:**
- Consumes: `StoryboardState.edit` (Task 6).
- Produces:
  - `springEasing(response = 0.3, samples = 20): string`: a CSS `linear()` easing that samples a critically damped spring, `x(t) = 1 - (1 + ωt)e^(-ωt)` with `ω = 2π / response`, from t = 0 to the 350 ms duration, with the last value set to exactly 1.
  - `SPRING_MS = 350`.
  - `moveOp(keys: string[], active: string, over: string): EditOp | null`: `{op: 'move', from, to}` from the scenes' order, or null when nothing moves.

How it behaves:
- One `DndContext` wraps all the chapter grids, with a `SortableContext` over every scene's `key` using `rectSortingStrategy`.
- It uses a `PointerSensor` with `activationConstraint: { distance: 8 }`, and no `KeyboardSensor`: Task 10 moves scenes by keyboard.
- `SceneModule` calls `useSortable({ id: scene.key, transition: { duration: SPRING_MS, easing: springEasing() } })`, with `transition: null` under reduced motion.
  - It spreads `listeners` and dnd-kit's `aria-roledescription` and `aria-describedby`, but not its `role` or `tabIndex`: the scene stays an `option` of the listbox.
- **Feedback:**
  - On press, the scene shrinks to 98% in 100 ms.
  - While dragged, it sits on top at 102% with a 1 px `--ink` outline, and keeps its own picture.
- `autoScroll` stays on, so a drag reaches scene 100.
- **Announcements:**
  - "Picked up scene N."
  - "Scene N moved to number M."
  - "Scene N stays where it was."

- [ ] **Step 1: Write the failing tests:**
  - `springEasing starts at 0, ends at exactly 1, never goes back, and has samples + 1 points`
  - `springEasing settles: its last but one value is above 0.99`
  - `moveOp gives the numbers of the scene moved and where it lands, and null for a drop on itself`
- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement.** `npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities` in `app/`.
- [ ] **Step 4: Run** `npm test` (PASS). Then in the real window with the tier-list reel:
  - drag scene 2 to after scene 5, and see it follow the pointer from where it was grabbed while the others slide aside without overshoot;
  - drop it, and see that it holds;
  - press Ctrl+Z and see it go back;
  - drag scene 6 into chapter 1, and see "Turn" go away and the index update.
- [ ] **Step 5: Commit** (if asked), message "Drag scenes into a new order".

---

### Task 8: Changing a scene in its details panel

**Files:**
- Create: `app/src/renderer/src/storyboard/WordsField.tsx`, `app/src/renderer/src/storyboard/OverEditor.tsx`, `app/src/renderer/src/storyboard/DetailsPanel.test.tsx`
- Modify: `app/src/renderer/src/storyboard/DetailsPanel.tsx`

**Interfaces:**
- Consumes: `StoryboardState.edit`, `window.frameflow.chooseFile`, `Scene` (Task 5).
- Produces: `<DetailsPanel scene folder aspect edit />`, where `edit` is `StoryboardState['edit']`, and an imperative `focusWords()` the keyboard map calls (a `ref`).

What the panel shows and does:
- **Words:**
  - The label is "What is said" on a footage scene without narration, with the hint "Change the words to use another part of your recording". Otherwise it is "What the voice says".
  - Click or Enter opens a textarea holding the words. Enter commits (op `words`), Shift+Enter is ignored, and Esc cancels.
  - While the engine looks, the hint reads "Finding it in your recording…".
  - A refusal shows under the field in `--signal-ink`, and the words go back.
- **On screen** (title scenes only): one input, Enter or blur commits (op `title`).
- **Over it:**
  - a caption input (empty removes it);
  - a list of cards, each with a Product / Name on screen select, its text, a second line, a price (products only) and "Pops up on" (words in this scene), plus Remove;
  - "Add a card", which adds `{kind: 'product', text: 'New card'}`;
  - on footage, a list of B-roll, each with its file's name, "Pops up on", seconds and Remove, plus "Add B-roll…" through `chooseFile`.
  - Every commit sends one `over` op with the whole list.
- **Picture:**
  - footage: "Cover with a picture or clip…";
  - other scenes: "Replace the picture…";
  - both go through `chooseFile`, then send op `picture` with the toast "Picture replaced".
- **Delete scene:** a lucide `Trash2` icon button labelled "Delete scene", sending op `delete` with the toast "Scene N deleted". No dialog.

- [ ] **Step 1: Write the failing tests:**
  - `Enter on the words opens them for editing and Esc puts them back`
  - `new words are sent as a words change, and "Finding it in your recording…" shows while it looks`
  - `words not said are shown under the field and the old words come back`
  - `a title's words on screen are changed with a title change`
  - `adding a card sends the whole list with the new card`
  - `removing a card sends the list without it`
  - `the picture is replaced with the file the creator picks, and nothing is sent when they cancel`
  - `B-roll is offered on footage only`
  - `Delete scene sends a delete with an Undo toast and asks nothing`
- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** with shadcn `input`, `textarea`, `select` and `button` (`npx shadcn@latest add input textarea select`).
- [ ] **Step 4: Run** `npm test`. Expected: PASS. Then in the real window:
  - change scene 6 of the reel to "remove all the repetitive editing work", see its frame change and its rule shorten, and undo it;
  - type words not said, and see the refusal.
- [ ] **Step 5: Commit** (if asked), message "Change a scene's words, picture and what pops up over it".

---

### Task 9: Adding scenes, and the suggested chapters

**Files:**
- Create: `app/src/renderer/src/storyboard/AddScene.tsx`, `app/src/renderer/src/storyboard/ChapterHeading.tsx`, `app/src/renderer/src/storyboard/AddAndChapters.test.tsx`
- Modify: `app/src/renderer/src/storyboard/Storyboard.tsx`, `app/src/renderer/src/storyboard/SectionIndex.tsx`

**Interfaces:**
- Consumes: `StoryboardState.edit`, `chooseFile`, `Section.confirmed`.
- Produces:
  - `<AddScene after={number} edit />`;
  - `<ChapterHeading section edit />`.

**Adding scenes:**
- An "Add a scene" tile ends each chapter's grid: a button at least 32 px tall, with a `Plus` icon, on the scene grid's hairline.
- It opens a shadcn `dropdown-menu` with "A title", "A file of yours…" and "From your recording…".
  - **A title** adds `{kind: 'title', text: 'New title'}` after the chapter's last scene, selects it, and focuses its On screen field.
  - **A file** goes through `chooseFile`.
  - **From your recording** opens a small shadcn `dialog` with one input, "Words you say in it", and an Add button. A refusal shows in the dialog, which stays open.

**Chapters:**
- A chapter that is not `confirmed` shows a "Suggested" tag (6 px radius, `--quiet` on `--plain`) beside its title, in the heading and in the index.
- Clicking the title turns it into an input: Enter commits (op `rename_chapter`), Esc cancels.
- An `Ellipsis` icon button labelled "Chapter options" opens Rename, "Keep this chapter" (when suggested) and "Remove chapter".
  - Remove sends op `remove_chapter` with the toast "Chapter removed".

- [ ] **Step 1: Write the failing tests:**
  - `a title added at the end of a chapter is selected, with its words on screen ready to type`
  - `a file of yours is added after the chapter's last scene, and nothing is sent on cancel`
  - `words not said in the recording keep the dialog open with the reason`
  - `a suggested chapter shows the tag until it is renamed or kept`
  - `renaming a chapter sends the new name, and Esc leaves it`
  - `removing a chapter asks nothing and offers Undo`
- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** (`npx shadcn@latest add dropdown-menu dialog`).
- [ ] **Step 4: Run** `npm test`. Expected: PASS.
- [ ] **Step 5: Commit** (if asked), message "Add scenes, and rename, keep or remove a suggested chapter".

---

### Task 10: The keyboard map and the Ctrl K palette

**Files:**
- Create: `app/src/renderer/src/storyboard/keys.ts`, `app/src/renderer/src/storyboard/keys.test.ts`, `app/src/renderer/src/shell/CommandPalette.tsx`, `app/src/renderer/src/shell/CommandPalette.test.tsx`
- Modify: `app/src/renderer/src/storyboard/Storyboard.tsx`, `app/src/renderer/src/App.tsx`

**Interfaces:**
- Consumes: `StoryboardState`, `DetailsPanel.focusWords`, `startBuild` (plan 1).
- Produces:

```ts
export type Action = 'next' | 'previous' | 'down' | 'up' | 'first' | 'last' | 'move-earlier' | 'move-later'
  | 'delete' | 'edit-words' | 'undo' | 'redo' | 'palette'
export function actionFor(e: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'altKey'>,
                          inField: boolean): Action | null
```

**The map:**

| Keys | Action |
|---|---|
| ArrowRight / ArrowLeft / ArrowDown / ArrowUp | next / previous / down / up |
| Home / End | first / last |
| Alt+ArrowLeft / Alt+ArrowRight | move-earlier / move-later |
| Delete, Backspace | delete |
| Enter | edit-words |
| Ctrl or Cmd+Z | undo |
| Ctrl or Cmd+Shift+Z, Ctrl+Y | redo |
| Ctrl or Cmd+K | palette |

- In a text field only `palette` maps; the field keeps every other key, its own Ctrl+Z included.
- Space maps to nothing until plan 3.
- Up and Down keep plan 1's behaviour (its deferred minor about chapters stays deferred).
- Undo, redo and the palette listen on `window`, so they work wherever the focus is. The rest stay on the scene list.

**The palette:** shadcn `command` in a `CommandDialog`.
- **This scene:** Change its words, Move it earlier, Move it later, Delete it, Add a title after it, Add a file after it…, Add from your recording after it…
- **Video:** Build video, Undo, Redo, Word-by-word captions (on or off as it is)
- **Go to:** each scene as "Scene 06 · <its first words>", and each chapter as "Chapter 02 · Turn"
- Each item shows its keys with shadcn's `CommandShortcut`. Choosing one runs it and closes the palette.

- [ ] **Step 1: Write the failing tests:**
  - `keys.test.ts`: one assertion per row of the map; `inField` passes only Ctrl+K; Space maps to null.
  - `CommandPalette.test.tsx`:
    - `Ctrl K opens the palette and Escape closes it`
    - `typing "turn" offers the chapter, and choosing it selects its first scene`
    - `Delete it sends a delete for the selected scene`
    - `Undo is greyed out when there is nothing to undo`
  - `Storyboard.test.tsx`:
    - `Alt+Right moves the selected scene later and keeps it selected`
    - `Delete removes the selected scene and offers Undo`
    - `Ctrl+Z in the words field undoes the typing, not the storyboard`
- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** (`npx shadcn@latest add command`).
- [ ] **Step 4: Run** `npm test`. Expected: PASS.
- [ ] **Step 5: Commit** (if asked), message "Edit from the keyboard, and from a Ctrl K palette".

---

### Task 11: The whole-video settings in the footer

**Files:**
- Create: `app/src/renderer/src/storyboard/VideoSettings.tsx`, `app/src/renderer/src/storyboard/VideoSettings.test.tsx`
- Modify: `app/src/renderer/src/App.tsx` (the footer passed to `Storyboard`)

**Interfaces:**
- Consumes: `Described.video`, `window.frameflow.looks`, `StoryboardState.edit`.
- Produces: `<VideoSettings folder video edit />`, at the footer's left, before plan 1's summary:
  - a shadcn `switch` "Word-by-word captions";
  - a `switch` "Cut to the beat", shown only when `has_music`;
  - a `select` "Look" with "As shot" first, then `looks(folder)`'s names.
  - Each change sends one `video` op.
  - At 1100 px the footer still fits on one line, and the summary truncates first.

- [ ] **Step 1: Write the failing tests:**
  - `the captions switch shows the video's setting and sends the change`
  - `cut to the beat is offered only when the video has music`
  - `the look lists As shot first, then the video's looks, and As shot sends null`
- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** (`npx shadcn@latest add switch`).
- [ ] **Step 4: Run** `npm test`. Expected: PASS.
- [ ] **Step 5: Commit** (if asked), message "Change the whole video's captions, beat and look from the footer".

---

### Task 12: Check it against the brief

**Files:** none new; fixes land in the files above.

- [ ] **Step 1:** Run Impeccable's detector: `.claude/skills/impeccable/scripts/impeccable detect --json app/src/renderer/src`. Fix every finding, or name the one you keep and why.
- [ ] **Step 2:** In the real window, at 1440 x 900 and 1100 x 700, on the tier-list reel, do each of these:
  - change a scene's words;
  - replace a picture;
  - add a card;
  - add a title;
  - drag a scene across chapters;
  - rename and remove a chapter;
  - switch captions;
  - run five changes through the palette;
  - undo all of it.

  Check that red still has its two jobs only, that every new control is at least 32 px and on the radius scale, and that focus is visible with Tab.
- [ ] **Step 3:** Make a 100-scene copy of the reel's storyboard (one scene repeated with different spans) in `output/edit-check/`, open it, and check:
  - dragging scene 3 to number 95 scrolls and holds;
  - Ctrl+Z is instant;
  - thumbnails load as they scroll.
- [ ] **Step 4:** Edit `storyboard.json` by hand while the app shows it, then make a change in the app. The app refuses it, reloads, and says so.
- [ ] **Step 5:** Close the app and open it again. Ctrl+Z still undoes the last change.
- [ ] **Step 6:** Show Satwik the running app and ask what to change before plan 3.
- [ ] **Step 7:** Update the vault's status note with what landed and the test counts, and end with a short progress note.
