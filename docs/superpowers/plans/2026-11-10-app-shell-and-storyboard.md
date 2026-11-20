# App Shell and Storyboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A desktop app that opens a video Frameflow already has a storyboard for, shows it as the confirmed Swiss storyboard screen, builds it with the engine's steps shown live, and puts the build's checks on the scenes they concern.

**Architecture:** The Python package in `project/` stays the engine. A new module, `project/app_api.py`, answers the app in JSON (list videos, describe one, make a thumbnail), and a build now leaves a `build_report.json`. The app is a new `app/` folder: Electron's main process starts the engine as a child process and passes results to a React renderer over a typed preload bridge; the renderer never touches files or processes itself.

**Tech Stack:** Python 3.13 with `unittest` (engine). Node 22, Electron, electron-vite, React, TypeScript, Tailwind CSS v4, shadcn/ui, lucide-react, Vitest with React Testing Library (app).

**Spec:** `.impeccable/surfaces/app.md` (the confirmed brief and direction contract) and `PRODUCT.md`. The storyboard sketch the screen must match is `.impeccable/mocks/decision/swiss-v4.html`.

## This is plan 1 of 4

The brief covers four pieces that can each ship as working software. This plan is the first; the others get their own plans when this one is done.

1. **App shell and storyboard (this plan):** open a video made from the command line, read its storyboard on the Swiss screen, build it, see the checks. No editing, no AI.
2. **Editing the storyboard:** words, order, add, delete, picture, what pops up; undo; drag; the keyboard map and Ctrl K.
3. **The video screen:** a preview, the checks with Listen, Open in OpenShot, back to the storyboard.
4. **Prompt and plan, with the editor behind them:** the prompt screen, the plan card, changes asked in words, chapters written by the editor.

## Global Constraints

- Dark only. Text contrast at least WCAG AA (4.5:1 body, 3:1 large). Full keyboard use with a visible focus ring.
- Colours, exactly: ground `#0e0e0e`, ink `#f2f2f0`, secondary `#8a8a88`, lines `#262626`, signal red `#e30613`. Red has two jobs only: the selected scene and something to check (and a running time over the target). Nothing else is red.
- One grotesque for everything. This plan uses Schibsted Grotesk, self-hosted with the app (my call; one token, `--font-sans`, swaps it). Tabular figures only on times, never on body text (in this face they widen punctuation).
- Corners: continuous and concentric. `corner-shape: squircle` with `border-radius` from this scale only: 6 px tags, 8 to 10 px controls and scene frames, 12 px the main action, 14 to 16 px toasts and the large frame. Rules, dividers and the grid stay straight.
- Hit targets at least 32 px; the main action 40 px tall; spacing on an 8 px grid.
- Solid surfaces: no `backdrop-filter`, no translucency, no gradients on UI.
- Controls are shadcn/ui components; icons are lucide-react; no emoji.
- Motion 150 to 250 ms, only for a change of state; `prefers-reduced-motion` swaps it for a fade.
- Never copy the direction contract's text into `app/` source or anything the app ships.
- The engine's tests run on GitHub's Ubuntu and Windows runners with FFmpeg but without OpenShot, Piper or the recordings: a test that needs one of those skips itself, as `tests/test_produce.py` does.
- The working tree mixes CRLF and LF: edit existing files in place and keep each file's line endings.
- Commit steps run only if Satwik has asked for commits in this run. Commit your own files by path (`git commit -- <paths>`), never `git add -A`, with no `Co-Authored-By` or other AI-credit line. Never commit `.agents/`, `.gitignore` or `.claude/settings.local.json`.
- Nothing is spent: a build is started without `--budget`.

## Review Focus

Failure modes the brief implies and no screen's happy path exercises, most likely first. Each has its test in the task named.

1. **A folder path with spaces** (`E:\my projects\frameflow\output\...`): the engine is started with an argument array, never a shell string, and the video opens. (Task 5)
2. **A video with no storyboard yet, or a storyboard that is not valid JSON:** the video is listed as "No storyboard yet" or shows the engine's message, and the app does not crash. (Tasks 3 and 7)
3. **Python or the engine fails to start:** the screen shows what was run and what it said, with a Try again button, never a blank window. (Tasks 5 and 7)
4. **Build pressed twice, or the window closed mid-build:** one build per video at a time; the button is disabled while it runs; quitting stops the child process. (Tasks 5 and 8)
5. **A recording that has moved, or 100 scenes:** a missing thumbnail shows the scene's number on a plain frame, and thumbnails are asked for only as scenes scroll into view. (Tasks 3 and 7)

---

### Task 1: A build leaves a report

**Files:**
- Modify: `project/produce.py` (`build_ir` near line 444, `build` near line 635)
- Modify: `project/look.py` (`report`, near line 150)
- Test: `tests/test_produce.py`, `tests/test_look.py`

**Interfaces:**
- Produces: `build_ir(folder, board, brief, inputs, spans: list | None = None) -> dict`. When `spans` is a list, it is filled with one `{"start": float, "end": float}` per scene, in seconds on the timeline.
- Produces: `look.report(project, ir) -> dict`: `{"looked": int, "problems": [str]}` or `{"skipped": str}`. It still prints what it prints today.
- Produces: `produce.REPORT_FILE = "build_report.json"`, written by `build()` into the video's folder:

```json
{
  "seconds": 20.1,
  "target_seconds": 20,
  "scenes": [{"start": 0.0, "end": 1.467}],
  "joins": {"checked": 8, "suspect": [{"at": 11.43, "before": "editing work", "after": "create a", "heard": "editing or create"}]},
  "picture": {"looked": 11, "problems": [{"at": 7.0, "what": "the graphic \"Tip 1\" covers 30% of a face"}]}
}
```

`joins` is `null` when no footage is heard, and `{"skipped": "<why>"}` when the check could not run. `picture` is `{"skipped": "<why>"}` when OpenShot is not there. A picture problem's `at` is parsed from its leading `m:ss` clock, and is `null` when the text has none.

- [ ] **Step 1: Write the failing tests**

In `tests/test_produce.py`, in `TestBuildingTheProject` (its `setUp` already reads every narration line as one second of tone; `BRIEF` is the module's constant):

```python
def test_build_ir_fills_each_scenes_span(self):
    board = {"script": "s", "scenes": [
        {"visual": {"type": "title", "text": "Hook"}, "duration": 2.0, "reason": "r"},
        {"visual": {"type": "title", "text": "Next"}, "narration": "Meet it", "reason": "r"}]}
    spans = []
    produce.build_ir(self.folder, board, BRIEF, {"footage": [], "assets": [], "music": []}, spans)
    self.assertEqual([s["start"] for s in spans], [0, 2.0])
    self.assertEqual(spans[0]["end"], 2.0)
    self.assertAlmostEqual(spans[1]["end"], 3.0, places=1)

def test_report_gives_a_picture_problem_its_second(self):
    self.assertEqual(produce._picture_problem('0:07.00: the graphic "Tip 1" covers 30% of a face'),
                     {"at": 7.0, "what": 'the graphic "Tip 1" covers 30% of a face'})
    self.assertEqual(produce._picture_problem("something without a clock"),
                     {"at": None, "what": "something without a clock"})
```

In `tests/test_look.py`: `report` returns `{"skipped": ...}` when `look.check` raises `LookError` (mock `look.check`), and `{"looked": 3, "problems": ["0:01.00: black"]}` when it returns `(["0:01.00: black"], 3)`.

- [ ] **Step 2: Run them and see them fail**

Run: `python -m unittest tests.test_produce tests.test_look -v`
Expected: FAIL (`build_ir` takes 4 arguments; `_picture_problem` not defined; `report` returns `None`).

- [ ] **Step 3: Implement**

`build_ir`: replace the local `spans = []` with the passed list when one is given. `_picture_problem(text: str) -> dict`: one regular expression, `^(\d+):(\d+(?:\.\d+)?): (.*)$`. `look.report`: return the dict beside each existing print. `build`: collect the spans, the join checks (from `JoinCheck.timeline_seconds`, `expected_before`, `expected_after`, `heard`) and `look.report`'s return, and write `REPORT_FILE` with `first_cut._write_json` before `editor.open`.

- [ ] **Step 4: Run the whole suite**

Run: `python -m unittest discover -s tests`
Expected: OK, the same skips as before.

- [ ] **Step 5: Commit** (if asked) `project/produce.py project/look.py tests/test_produce.py tests/test_look.py`, message "Leave a report after a build, for an app to read".

---

### Task 2: A storyboard can name its chapters

**Files:**
- Modify: `project/schema/storyboard.schema.json`
- Modify: `project/produce.py` (`check_storyboard`, near line 332; the storyboard request text near line 258)
- Test: `tests/test_produce.py` (`TestStoryboardChecks`)

**Interfaces:**
- Produces: an optional board-level `sections`: `[{"title": str, "from": int}]`, where `from` is the 1-based number of the section's first scene. The build ignores it.

- [ ] **Step 1: Write the failing tests** in `TestStoryboardChecks`:

```python
def test_sections_must_start_at_scene_one_and_rise(self):
    title = {"visual": {"type": "title", "text": "Hi"}, "duration": 2, "reason": "r"}
    def problems(sections):
        board = self.board(title, title, title, sections=sections)
        validate(board, "storyboard")
        return produce.check_storyboard(board, self.INPUTS)
    self.assertEqual(problems([{"title": "Problem", "from": 1}, {"title": "Answer", "from": 3}]), [])
    self.assertIn("sections: the first starts at scene 1", problems([{"title": "Problem", "from": 2}]))
    self.assertIn("sections: each starts after the one before",
                  problems([{"title": "A", "from": 1}, {"title": "B", "from": 1}]))
    self.assertIn("sections: B starts at scene 9, but there are 3",
                  problems([{"title": "A", "from": 1}, {"title": "B", "from": 9}]))
```

- [ ] **Step 2: Run:** `python -m unittest tests.test_produce.TestStoryboardChecks -v`. Expected: FAIL on schema (`sections` not allowed).

- [ ] **Step 3: Implement.** Schema: `sections`, array of objects with required `title` (string, min 1) and `from` (integer, min 1), `additionalProperties: false`, described as "Optional: the video's chapters, for long videos, each with the number of its first scene." Add the three messages to `check_storyboard`. Add one bullet to the storyboard request: for a video of more than about 12 scenes, group the scenes into `sections`.

- [ ] **Step 4: Run** `python -m unittest discover -s tests`. Expected: OK.

- [ ] **Step 5: Commit** (if asked) the three files, message "Let a storyboard name its chapters".

---

### Task 3: The engine answers an app in JSON

**Files:**
- Create: `project/app_api.py`
- Test: `tests/test_app_api.py`

**Interfaces:**
- Consumes: `produce.REPORT_FILE`, `produce.STORYBOARD_FILE`, `produce.BRIEF_FILE`, `produce.INPUTS_FILE`, `first_cut.TIMING_FILE`, `verify_cuts.words_in_clip`, `media._find_tool`.
- Produces: `videos(root: Path) -> list[dict]`: one per folder under `root` that has `inputs.json`, newest first: `{"folder": str, "title": str, "has_storyboard": bool, "built": bool}`. `title` is the brief's, or the folder's name.
- Produces: `describe(folder: Path) -> dict`:

```json
{
  "title": "Editing tier list", "aspect": "9:16", "target_seconds": 20,
  "built": true,
  "sections": [{"title": "Problem", "from": 1}],
  "scenes": [{"number": 1, "kind": "footage", "says": "Main problem with video editing",
              "seconds": 1.467, "start": 0.0, "source": "Your recording 0:45–0:47", "over": ["Card: Tip 1"]}],
  "report": {}
}
```

  `kind` is the visual's `type`. `says` is the narration, else the recording's words inside the span, else the title's text, else `""`. `seconds` and `start` come from the report when `built`; otherwise `seconds` is the span's length or the scene's `duration`, else `null`, and `start` is `null`. `built` is true only when the report is at least as new as `storyboard.json`. `over` lists the scene's caption, cards and B-roll, one short line each. `report` is the report file's content, or `null`. A folder without a storyboard gives `{"title": ..., "scenes": [], "no_storyboard": true}`.
- Produces: `thumbnail(folder: Path, number: int) -> Path | None`: a JPEG 176 px wide, cached under `<folder>/app_cache/thumbs/<number>-<digest>.jpg` where the digest is of the scene's visual. A footage or clip scene gives the frame 0.3 s into its span; an image scene the image; any other kind, or a source that is not there, `None`.
- Produces: the command line: `python -m project.app_api videos ROOT`, `describe FOLDER`, `thumbnail FOLDER NUMBER`. Each prints one JSON value on stdout (the thumbnail's path as a string, or `null`). A failure prints `{"error": "<message>"}` and exits 1; a traceback never reaches stdout.

- [ ] **Step 1: Write the failing tests** in `tests/test_app_api.py`, each in a `tempfile.TemporaryDirectory`, writing the JSON files by hand (no build needed):

  - `test_videos_lists_folders_with_inputs_newest_first`
  - `test_describe_a_footage_scene_says_the_words_in_its_span` (a `timing.json` with words at 1.0, 1.5 and 9.0 s; a span of 0.8 to 2.0 says the first two)
  - `test_describe_uses_the_report_only_when_it_is_newer_than_the_storyboard`
  - `test_describe_without_a_storyboard_says_so` (expects `no_storyboard`)
  - `test_a_broken_storyboard_is_an_error_not_a_traceback` (run the command line with `subprocess`; expects exit 1 and stdout that parses as JSON with `error`)
  - `test_thumbnail_of_a_missing_recording_is_none`
  - `test_thumbnail_of_a_clip_is_a_jpeg` (make a 2 s test clip with FFmpeg as `tests/test_produce.py`'s `_tone` does for sound; skip when FFmpeg is not found)

- [ ] **Step 2: Run:** `python -m unittest tests.test_app_api -v`. Expected: FAIL (no module `project.app_api`).

- [ ] **Step 3: Implement `project/app_api.py`** with the three functions and `main()`. One `try` in `main` turns any `Exception` into the `{"error": ...}` line.

- [ ] **Step 4: Run** `python -m unittest discover -s tests`. Expected: OK. Then by hand, where the folder exists: `python -m project.app_api describe output/reference-swap` prints nine scenes.

- [ ] **Step 5: Commit** (if asked) the two files, message "Answer an app in JSON: videos, a storyboard, a thumbnail".

---

### Task 4: The app's shell

**Files:**
- Create: `app/` (scaffold), `app/src/renderer/src/styles/tokens.css`, `app/src/renderer/src/App.tsx`, `app/src/renderer/src/App.test.tsx`, `app/vitest.config.ts`
- Modify: `.github/workflows/ci.yml` (a step that runs the app's tests on both runners)

**Interfaces:**
- Produces: `npm run dev` (the app in a window), `npm test` (Vitest, jsdom), `npm run build`, all inside `app/`.
- Produces: the tokens in `tokens.css` as CSS custom properties, mapped to Tailwind and shadcn's theme: `--ground`, `--ink`, `--secondary`, `--line`, `--signal` with the Global Constraints' values; `--font-sans`; `--radius-tag: 6px`, `--radius-control: 10px`, `--radius-action: 12px`, `--radius-surface: 16px`; and `* { corner-shape: squircle; }`.

- [ ] **Step 1: Scaffold.** From the repo root: `npm create @quick-start/electron@latest app -- --template react-ts`, then in `app/`: add Tailwind v4 and run `npx shadcn@latest init` (base colour neutral, CSS variables on), pointing its aliases at `src/renderer/src`. Add `lucide-react`, `@fontsource-variable/schibsted-grotesk`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`. Add `app/node_modules/`, `app/out/` and `app/dist/` to `app/.gitignore` (not the repo's `.gitignore`).

- [ ] **Step 2: Write the failing test** `App.test.tsx`:

```tsx
it("shows an empty state that says how to start when there are no videos", async () => {
  window.frameflow = { videos: async () => [] } as never;
  render(<App />);
  expect(await screen.findByText("No videos yet")).toBeInTheDocument();
  expect(screen.getByText(/python -m project.produce/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run:** `npm test` in `app/`. Expected: FAIL.

- [ ] **Step 4: Implement** `tokens.css` and an `App` that lists videos from `window.frameflow.videos()` in the slim rail and shows the empty state: "No videos yet", and under it how to make one for now (`python -m project.produce output/<name> --prepare "..."`), since the prompt screen is plan 4.

- [ ] **Step 5: Run** `npm test` (PASS) and `npm run dev`: a black window with the rail and the empty state, in Schibsted Grotesk.

- [ ] **Step 6: CI.** In `ci.yml`, after the Python tests: a step named "Run the app's tests", `working-directory: app`, `run: npm ci && npm test`.

- [ ] **Step 7: Commit** (if asked) `app/` and `ci.yml`, message "Start the desktop app: Electron, React, shadcn, the tokens".

---

### Task 5: The bridge to the engine

**Files:**
- Create: `app/src/main/engine.ts`, `app/src/main/engine.test.ts`, `app/src/main/ipc.ts`, `app/src/shared/types.ts`
- Modify: `app/src/main/index.ts`, `app/src/preload/index.ts`

**Interfaces:**
- Consumes: Task 3's command line; `python -m project.produce FOLDER --build`, whose steps are stdout lines starting `==> ` and whose details are lines starting four spaces.
- Produces, in `shared/types.ts`: `Video`, `Scene`, `Section`, `Report`, `Described` matching Task 3's JSON exactly, and

```ts
export type BuildEvent =
  | { type: "step"; text: string }
  | { type: "detail"; text: string }
  | { type: "done"; ok: boolean; message?: string };

export interface FrameflowApi {
  videos(): Promise<Video[]>;
  describe(folder: string): Promise<Described>;
  thumbnail(folder: string, number: number): Promise<string | null>;  // a file:// URL
  build(folder: string, onEvent: (e: BuildEvent) => void): Promise<void>;
  onBuildFinished(cb: (folder: string, ok: boolean) => void): void;
}
```

- Produces, in `engine.ts`: `createEngine({ python, root }): Engine` with `json<T>(args: string[]): Promise<T>` (rejects with the engine's `error` text, or with "Could not start `<python>`: <reason>") and `build(folder, onEvent): Promise<void>` (rejects if that folder is already building) and `stopAll(): void`. `python` comes from the `FRAMEFLOW_PYTHON` environment variable, else `python`; `root` is the repo root (the app's parent folder in development). Videos are listed from `<root>/output`.

- [ ] **Step 1: Write the failing tests** `engine.test.ts`, with a fake engine: a small Node script the test writes to a temp folder and passes as `python` with the script as its first argument.

  - `json resolves with the parsed line`
  - `json rejects with the engine's error text when it prints {"error"}`
  - `json rejects with "Could not start" when the program does not exist`
  - `a folder path with spaces arrives as one argument` (the fake echoes `process.argv`)
  - `build turns "==> " lines into steps and indented lines into details, then done`
  - `a second build of the same folder is refused while the first runs`
  - `stopAll ends a running build`

- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.

- [ ] **Step 3: Implement** `engine.ts` with `child_process.spawn(python, args, { cwd: root })`, never `shell: true`. `ipc.ts` registers one handler per `FrameflowApi` method and sends `BuildEvent`s on a per-build channel; the preload exposes `window.frameflow` with `contextBridge`. In `index.ts`: `engine.stopAll()` on `before-quit`; when a build ends while the window is not focused, show an Electron `Notification` ("<title> is built" or "<title> could not be built") and send `onBuildFinished`.

- [ ] **Step 4: Run** `npm test`. Expected: PASS.

- [ ] **Step 5: Commit** (if asked) the files, message "Start the engine from the app and pass its answers to the screen".

---

### Task 6: The storyboard's numbers

**Files:**
- Create: `app/src/renderer/src/storyboard/model.ts`, `app/src/renderer/src/storyboard/model.test.ts`, `app/src/renderer/src/storyboard/fixture.ts`

**Interfaces:**
- Consumes: `Described`, `Scene`, `Section`, `Report` from `shared/types.ts`.
- Produces:

```ts
export interface SceneView extends Scene { rule: number; check: string | null; }   // rule: 0..1 of the longest scene
export interface SectionView { number: number; title: string | null; start: number | null; scenes: SceneView[]; }
export interface Figures { scenes: number; seconds: number | null; target: number; over: boolean; estimated: boolean; }
export function toView(d: Described): { sections: SectionView[]; figures: Figures };
export function clock(seconds: number): string;       // 68.4 -> "1:08"
```

  A board without `sections` gives one section with `title: null`. `figures.seconds` is the report's when built; otherwise the sum of the scenes' known `seconds`, with `estimated: true`, or `null` when none is known. `over` is true when `seconds` exceeds `target` by more than 10%. A scene's `check` is the first that falls on it: a suspect join whose `at` is within 0.05 s of the scene's end (`May clip "<last word of before>"`), or a picture problem whose `at` is inside the scene (its `what`, first letter capitalised). An unbuilt video has no checks.
- Produces: `fixture.ts`: the tier-list reel as a `Described`, written by hand from `python -m project.app_api describe output/reference-swap` (that folder is git-ignored and has neither sections nor a report yet): its nine scenes with starts 0, 1.467, 3.267, 4.467, 6.933, 8.7, 11.433, 16.233, 18.133 and lengths 1.467, 1.8, 1.2, 2.467, 1.767, 2.733, 4.8, 1.9, 1.967; `sections` Problem from 1, Turn from 6, Answer from 7; `built: true`; and a report of 20.1 s against 20 with eight joins checked, one suspect at 11.433 (`before` "editing work", `heard` "editing or create") and a clean picture check of 11 frames.

- [ ] **Step 1: Write the failing tests:** the fixture gives three sections of 5, 1 and 3 scenes; scene 7's `rule` is 1 and scene 3's is 0.25 (1.2 of 4.8); scene 6's `check` is `May clip "work"` and no other scene has one; `figures` is `{scenes: 9, seconds: 20.1, target: 20, over: false, estimated: false}`; the same data without a report gives `estimated: true` and no checks; 23 s against 20 is `over`; `clock(68.4)` is `"1:08"`.

- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement `model.ts`.**
- [ ] **Step 4: Run:** `npm test`. Expected: PASS.
- [ ] **Step 5: Commit** (if asked), message "Work out a storyboard's sections, lengths and checks for the screen".

---

### Task 7: The storyboard screen

**Files:**
- Create, under `app/src/renderer/src/storyboard/`: `Storyboard.tsx`, `SceneModule.tsx`, `SectionIndex.tsx`, `FiguresLine.tsx`, `DetailsPanel.tsx`, `Thumbnail.tsx`, `Storyboard.test.tsx`
- Create: `app/src/renderer/src/shell/TopBar.tsx`, `app/src/renderer/src/shell/VideoRail.tsx`
- Modify: `app/src/renderer/src/App.tsx`

**Interfaces:**
- Consumes: `toView`, `clock`, `fixture`; `window.frameflow.describe` and `.thumbnail`.
- Produces: `<Storyboard folder={string} />`, which owns the selected scene and renders the layout of `.impeccable/mocks/decision/swiss-v4.html` at 1440 x 900: slim video rail (56 px), top bar (video's name; Prompt, Storyboard, Video with Storyboard current and the other two disabled until their plans), section index (176 px), the figures line, each section's heading and its scenes three to a row, the details panel (340 px), and a footer that Task 8 fills.

Sizes and type, from the sketch: figures 40 px, weight 700, tracking -0.03em; section heading 20 px, 700, -0.015em; scene number 15 px, 700; scene words 15 px, line height 1.32; small labels 11 to 12 px, tracking 0.01em, in `--secondary`; details panel number 56 px, -0.035em. Scene frame 88 x 156 for 9:16 (the same height, width from the aspect, for 16:9 and 1:1), radius 10 px; details frame 160 px wide, radius 16 px. The rule over a scene is 3 px, its width the scene's `rule`, over a 1 px `--line` track; it is `--signal` on the selected scene, `--ink` otherwise.

Behaviour: clicking a scene selects it; Left and Right move the selection, Up and Down by a row; Home and End go to the first and last scene. Clicking a section in the index scrolls to it. A scene's check shows under its words in `--signal`. An estimated running time shows as "about 19 seconds"; an unbuilt video's start times are left out, not shown as 0:00. A chapter heading is shown only when the board has sections. The section index is hidden when there is one unnamed section.

States: loading is a skeleton of the layout (the rules and frame boxes, no spinner); `no_storyboard` says "No storyboard yet" with the command that writes one; an engine failure shows what was run and what it said with a "Try again" button; a scene whose thumbnail is `null` shows its number on a plain `#1a1a1a` frame. `Thumbnail` asks for its picture only once it is near the viewport (an `IntersectionObserver`).

- [ ] **Step 1: Write the failing tests** `Storyboard.test.tsx`, with `window.frameflow` stubbed to return the fixture:

  - `shows nine scenes in three chapters, with the count and running time` ("9", "20.1", "/20")
  - `the selected scene's rule is the only red one, and the details panel shows its words`
  - `Right moves the selection to the next scene, End to the last`
  - `scene 6 says May clip "work"; no other scene shows a check`
  - `an unbuilt video says "about" and shows no start times`
  - `a video without a storyboard says so, with the command`
  - `an engine failure shows its message and Try again asks again`
  - `a scene with no thumbnail shows its number on a plain frame`
  - `a thumbnail is not asked for until its scene is near the viewport` (stub `IntersectionObserver`)

- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement the components.** Read `.claude/skills/impeccable/reference/craft-floor.md` immediately before writing them.
- [ ] **Step 4: Run** `npm test` (PASS), then `npm run dev` with `output/reference-swap` present: compare the window at 1440 x 900 with the sketch, side by side. Fix what differs in layout, scale or colour before going on.
- [ ] **Step 5: Commit** (if asked), message "Show a storyboard on the Swiss screen".

---

### Task 8: Build, with its steps and its checks

**Files:**
- Create: `app/src/renderer/src/storyboard/BuildBar.tsx`, `app/src/renderer/src/storyboard/BuildBar.test.tsx`
- Modify: `app/src/renderer/src/storyboard/Storyboard.tsx`

**Interfaces:**
- Consumes: `window.frameflow.build`, `BuildEvent`, `window.frameflow.describe`.
- Produces: `<BuildBar folder title onBuilt={() => void} />` in the footer: the "Build video" button (40 px tall, radius 12 px, ink on ground inverted as in the sketch) at the right. While building, the button is disabled and the steps appear beside it as they arrive, growing from the button: finished steps in `--secondary` with a check icon, the current one in `--ink` with a spinner, each step's last detail under the bar in `--secondary`. When it ends well, the bar calls `onBuilt` and `Storyboard` describes the video again, so the running time, start times and checks appear. When it fails, the engine's message (its "needs fixing" list included) shows above the bar, the steps stay as they were, and the button reads "Build again".

- [ ] **Step 1: Write the failing tests:**

  - `Build video starts a build and is disabled while it runs`
  - `steps appear in order; the current one has the spinner, earlier ones a check`
  - `when the build ends, the storyboard is described again and scene 6 shows its check`
  - `a failed build shows the engine's message and offers Build again`
  - `a second click while building starts nothing`

- [ ] **Step 2: Run:** `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` (PASS). Then for real: `npm run dev`, open "Editing tier list", press Build video, watch the five steps, and see "20.1/20" and scene 6's check when it ends. Switch to another window during a second build and see the notification.
- [ ] **Step 5: Commit** (if asked), message "Build a video from the app and show what the build found".

---

### Task 9: Check it against the brief

**Files:** none new; fixes land in the files above.

- [ ] **Step 1:** Run Impeccable's detector over the screens: `.claude/skills/impeccable/scripts/impeccable detect --json app/src/renderer/src`. Fix every finding, or name the one you keep and why.
- [ ] **Step 2:** With the app running on `output/reference-swap`, check by eye at 1440 x 900 and at 1100 x 700: contrast of `--secondary` on `--ground` (at least 4.5:1), every focus ring visible with Tab, red used only on the selected scene and the check, every corner on the radius scale, every target at least 32 px.
- [ ] **Step 3:** Open `output/frameflow-pitch` (16:9, titles and a voiceover, no footage) and `output/ui-demo`: frames take the 16:9 shape, title scenes show their text, nothing overflows.
- [ ] **Step 4:** Show Satwik the running app and ask what to change before plan 2. The brief's FINISH line (the finish review, DESIGN.md) is discharged after plan 4, when all three screens exist; say so in the hand-over.
- [ ] **Step 5:** Update the vault's status note (`4 progress/status.md`) with what landed and the test counts, and end with a short progress note.
