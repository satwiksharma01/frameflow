# Scene Length and the Video Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- A long video's storyboard reads in one pass: Frameflow writes fewer, longer scenes for it (about 30 at most), and the build cuts the pauses inside each scene so the pace holds.
- The creator watches what they built: every build leaves a small preview. Space plays the selected scene, and Listen plays a check. The video screen shows the whole video with its scenes and checks, and opens the project in OpenShot.

**Architecture:**
- **Scene length is the editor's choice, guided by the engine.** The storyboard request tells the editor the average scene length for this video. At build time `build_ir` splits a heard footage scene into one clip per stretch between its long pauses (`cutpoints.kept_pieces`), so captions, cards, B-roll and the cut checks all follow the trimmed timeline. The report still has one span per storyboard scene.
- **The preview is rendered by OpenShot's own engine**, the way the build already renders the project's sound: `openshot_render.py --video` writes `<title>-preview.mp4` at 540 px on its shorter side.
- **The app plays it over its own `ff-media` scheme**, answering range requests itself so the video can seek. One small player component serves Space, Listen and the video screen.
- **Opening in OpenShot is an engine job like a build:** `python -m project.app_api open FOLDER` uses the editor's existing `open`.

**Tech Stack:**
- Engine: Python 3.13, `unittest`; OpenShot's engine through `openshot_build.run_script`; FFmpeg's `ffprobe` in tests.
- App: Electron 44, React 19, TypeScript, Tailwind v4, shadcn/ui, lucide-react, Vitest with React Testing Library.

**Spec:**
- `.impeccable/surfaces/app.md`, the confirmed brief. On 2026-11-12 Satwik replaced "3 to about 100 scenes" with "3 to about 30 scenes: a long video gets fewer, longer scenes, the build cuts the pauses inside each". Its Interaction section asks for "Space plays the scene", the check's Listen button, and steps that move left and right.
- `PRODUCT.md`.
- Plans 1 and 2 (`docs/superpowers/plans/2026-11-10-app-shell-and-storyboard.md`, `docs/superpowers/plans/2026-11-11-editing-the-storyboard.md`), built and uncommitted in this checkout. Plan 1 listed this plan as "the video screen: a preview, the checks with Listen, Open in OpenShot, back to the storyboard".
- Sources for the scheme work: Electron's `protocol` docs ("supports fetch API, streaming video/audio" with the `stream` privilege) and electron/electron#38749. That issue says media seeking over a custom scheme needs `stream`, a `standard` scheme (Chromium checks that every range answer comes from the first one's origin), and a handler that answers `Range` with 206 itself.

## This is plan 3 of 4

- **In this plan:**
  - scenes sized to the video's length;
  - pauses cut inside a scene;
  - a preview with every build;
  - Space and Listen on the storyboard;
  - the video screen;
  - Open in OpenShot;
  - the step bar moving between Storyboard and Video.
- **A design gate (Task 6).** The video screen has no confirmed sketch yet. Its layout is designed with Impeccable inside the confirmed direction and shown to Satwik, and nothing of it is built until he confirms. Tasks 1 to 5 do not depend on it.
- **Not in this plan:**
  - the prompt screen, the editor writing chapters, and changes asked for in words: plan 4;
  - exporting an MP4 for posting (the brief keeps it out); the preview is for watching in the app;
  - a Ctrl K palette on the video screen;
  - the brief's motion for the details panel ("enters and leaves on the right") and for Build's progress ("grows from the Build button"): no plan has built them yet, and this one does not either;
  - plans 1 and 2's deferred minors, unless Satwik asks.

## Global Constraints

- Everything in plans 1 and 2's Global Constraints still holds:
  - the colours and their jobs; red is only the current scene, something to check, and a running time over the target;
  - WCAG AA contrast, the radius scale and continuous corners, targets of at least 32 px and the main action 40 px;
  - solid surfaces, shadcn controls and lucide icons, motion of 150 to 250 ms for a change of state, reduced motion;
  - CI without OpenShot, Piper or the recordings;
  - the line endings;
  - commits only if asked, by path, with no `Co-Authored-By` line;
  - every storyboard change undoable, no confirm dialogs, the engine the only writer of `storyboard.json` and `inputs.json`.
- **Scene length:**
  - `MAX_SCENES = 30`; a video asks for longer scenes only when `target_seconds / 30` is more than `QUICK_SCENE_SECONDS = 3.0`, so a short video keeps its quick cuts;
  - inside a heard footage scene, a pause longer than `LONG_PAUSE_SECONDS = 0.75` is cut down to the breath either side of it, `PAD_SECONDS` (0.25 s) each, as first-cut leaves;
  - a scene under narration is not trimmed (the narration sets its length).
- **The preview:**
  - 540 px on its shorter side, both sides even, H.264 video and AAC sound, named `<project stem>-preview.mp4` beside the project;
  - written whole or not at all;
  - offered only while the build report is of the storyboard as it is now;
  - made after the build's report (Satwik, 2026-11-12, after the first real preview took about 1.5 times the video's length to render). A build is finished for the creator once its report and checks are written. The preview follows in the same run, and Build while it renders stops it and builds again.
- **Listen** plays from 1.5 s before the check's moment to 1.0 s after it, picture and sound.
- **Copy is plain**, as before, for example "Build the video to play its scenes."

## Review Focus

Failure modes the brief implies and no screen's happy path exercises, most likely first. Each has its test in the task named.

1. **A video changed since its build:** Space, Listen and the video screen never play the old preview against the new scenes. They say the video needs building and offer Build video. (Tasks 3, 5 and 7)
2. **A build that fails or is stopped while it renders the preview,** and a preview asked for while a build rewrites it: no half-written file is ever served. The old preview is removed when a build starts, and the new one appears only when it is whole. (Task 3)
3. **Seeking anywhere in a long preview** (a 15-minute video): ranges from the middle, to the end and the last bytes (`bytes=-500`) are answered with the right bytes and a 206; a range past the end gets 416; no range gets the whole file. (Task 4)
4. **Pauses at a scene's edges or close together:**
   - a pause that starts before the span or ends after it is left to the span's own cut;
   - two long pauses a word apart give three pieces with the word kept;
   - no piece is ever empty. (Task 2)
5. **Opening in OpenShot when it cannot be done** (never built, OpenShot not found): it says why and ends; it never hangs on a call's timeout. (Task 4)

---

### Task 1: Fewer, longer scenes for a long video

**Files:**
- Modify: `project/produce.py` (`storyboard_request`'s "How" list; new constants and `scene_seconds`)
- Test: `tests/test_produce.py` (`TestRequests`)

**Interfaces:**
- Produces:
  - `produce.MAX_SCENES = 30`, `produce.QUICK_SCENE_SECONDS = 3.0`;
  - `produce.scene_seconds(target_seconds: float) -> float | None`: `target_seconds / MAX_SCENES` when that is more than `QUICK_SCENE_SECONDS`, else `None`.

- [ ] **Step 1: Write the failing tests** in `TestRequests`, building the request the way its neighbours do:
  - `test_a_long_video_asks_for_about_30_longer_scenes`: a brief of `target_seconds` 900 gives a request containing `"about 30 scenes at most, about 30s each"`.
  - `test_a_five_minute_video_asks_for_ten_second_scenes`: 300 gives `"about 10s each"`.
  - `test_a_short_video_keeps_its_quick_cuts`: 20 and 90 give no `"scenes at most"`.
  - `test_scene_seconds`: `[scene_seconds(t) for t in (20, 90, 300, 900)] == [None, None, 10.0, 30.0]`.
- [ ] **Step 2: Run** `python -m pytest tests/test_produce.py -k "scenes or quick_cuts or scene_seconds" -q`. Expected: FAIL (`scene_seconds` is not defined).
- [ ] **Step 3: Implement.** When `scene_seconds` gives a length, the "How" list gains, after "Keep the total near the brief's …" and with that exact copy:

  `- This video is long, so aim for about {MAX_SCENES} scenes at most, about {seconds:.0f}s each on average: a scene is a whole point, one stretch of a recording that may hold several sentences, not a single cut. Start and end it in pauses as usual; the build cuts the pauses inside it.`
- [ ] **Step 4: Run** the same command. Expected: PASS. Then `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5: Commit** (if asked), message "Ask for fewer, longer scenes when the video is long".

---

### Task 2: The build cuts the pauses inside a scene

**Files:**
- Modify: `project/cutpoints.py` (`LONG_PAUSE_SECONDS`, `kept_pieces`)
- Modify: `project/produce.py` (`build_ir`'s footage branch, from about line 489)
- Modify: `project/app_api.py` (`describe`'s length for a scene not yet built)
- Modify: `app/src/renderer/src/storyboard/model.ts` (`check`, `SceneView.checkAt`)
- Test: `tests/test_cutpoints.py`, `tests/test_produce.py` (`TestBuildingTheProject`), `tests/test_app_api.py`, `app/src/renderer/src/storyboard/model.test.ts`

**Interfaces:**
- Produces:
  - `cutpoints.LONG_PAUSE_SECONDS = 0.75`;
  - `cutpoints.kept_pieces(start: float, end: float, pauses: list[dict], fps: float) -> list[tuple[float, float]]`: the stretches of `[start, end]` that play. Each pause with `start < pause.start` and `pause.end < end` that lasts more than `LONG_PAUSE_SECONDS` is cut from `place_in_pause(p, "keep", "remove", fps)` to `place_in_pause(p, "remove", "keep", fps)`. With none, `[(start, end)]`.
  - `SceneView.checkAt: number | null`: the timeline second of the scene's check (the join's `at`, or the picture problem's `at`), for Listen.
- Consumes: `cutpoints.place_in_pause`, `PAD_SECONDS`, `frame_align`.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_cutpoints.py`, class `TestKeptPieces`, at 20 fps so quarter-seconds fall on frames:
    - `test_a_span_with_no_long_pause_is_one_piece`: `kept_pieces(1.0, 7.0, [{"start": 3.0, "end": 3.6}], 20) == [(1.0, 7.0)]`
    - `test_a_long_pause_inside_is_cut_to_the_breath_either_side`: `kept_pieces(1.0, 7.0, [{"start": 3.0, "end": 5.0}], 20) == [(1.0, 3.25), (4.75, 7.0)]`
    - `test_a_pause_over_the_span_s_edge_is_left_to_the_span`: `kept_pieces(1.0, 7.0, [{"start": 0.5, "end": 2.0}, {"start": 6.0, "end": 8.0}], 20) == [(1.0, 7.0)]`
    - `test_two_long_pauses_a_word_apart_keep_the_word`: `kept_pieces(0.0, 6.0, [{"start": 1.0, "end": 2.5}, {"start": 2.8, "end": 4.0}], 20) == [(0.0, 1.25), (2.25, 3.05), (3.75, 6.0)]`. Every piece is longer than zero.
  - `tests/test_produce.py`, `TestBuildingTheProject`, with the `_spans` helper (they skip without the test recording, as their neighbours do):
    - `test_a_long_pause_inside_a_heard_scene_is_cut`: `self._spans([{"start": 3.0, "end": 5.0}], (1.0, 7.0))` has two clips. The first runs from 1.0 into the pause, ending within a frame of 3.25. The second starts within a frame of 4.75 and runs to 7.0. They sit back to back on the timeline.
    - `test_a_trimmed_scene_keeps_one_span_and_its_words_on_the_new_timeline`: a recording whose words are `("one", 1.2, 1.6)` and `("two", 5.2, 5.6)`, the same pause, the scene `(1.0, 7.0)` with `spoken_captions` and a card `when: "two"`. The scene's one span is as long as both pieces together. The card comes up at the timeline second "two" is heard (5.2 minus the cut's length, from 1.0). Spoken captions get two runs for the scene, one per piece.
  - `tests/test_app_api.py`: `test_an_unbuilt_scene_is_estimated_without_its_long_pauses`: a footage scene `(1.0, 7.0)` over a recording with the pause `3.0–5.0` and no report has `seconds` within a frame of 4.5.
  - `model.test.ts`: `a cut inside a scene that may clip a word is that scene's check`: a report whose suspect join is at a time inside scene 6 (not at its end) puts `May clip “…”` and `checkAt` on scene 6 and on no other scene. A join at a scene's end still belongs to that scene, as before.
- [ ] **Step 2: Run** `python -m pytest tests/test_cutpoints.py tests/test_produce.py tests/test_app_api.py -q -k "pieces or pause or trimmed or estimated"` and `npx vitest run src/renderer/src/storyboard/model.test.ts` in `app/`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `kept_pieces` as its Interfaces line says.
  - In `build_ir`, a heard footage scene (one with no narration) gets `pieces = kept_pieces(start, end, pauses, fps)` after `_heard_end`, with the recording's timing read once for the scene. Then one main-track clip per piece, back to back from `cursor`, each with its own crop offset (`reframe.clip_offset(keys, a, b)`), volume, fill and look, as the single clip has today. The scene's `length` is the pieces' sum.
  - With `cut_to_beat`, `_to_beat` moves only the last piece's out point. It gets the trimmed length; `room` = the earlier pieces' sum + `f["duration"] - last_in`; the words; and the last piece's offset, `last_in - (cursor + earlier pieces' sum)`.
  - `heard` is one `captions.run` per piece, at each piece's place on the timeline. `said` (spoken captions) gets the runs one by one, so no line crosses a cut. Cards, B-roll and the overlay's moments use the runs' words joined.
  - `spans` stays one entry per storyboard scene.
  - In `app_api.describe`, a scene not yet built that is heard footage has `seconds` = the sum of `kept_pieces(start, end, pauses, 30)`. Each recording's pauses are read once per `describe`.
  - In `model.ts`, a suspect join belongs to the scene where `start < at <= start + seconds + 0.05` (the first one, when two match). `SceneView.checkAt` is that join's `at`, or the picture problem's `at`.
- [ ] **Step 4: Run** the same commands. Expected: PASS. Then `python -m unittest discover -s tests` and `npm test` in `app/`. Expected: OK and PASS. A test of an existing build that assumed one clip per footage scene and now meets a long pause inside one is a finding: fix the fixture only if its pause was not meant to be heard, and ledger it.
- [ ] **Step 5: Commit** (if asked), message "Cut the long pauses inside a scene when building".

---

### Task 3: A preview with every build

**Files:**
- Modify: `project/openshot_render.py` (`--video WIDTH HEIGHT`)
- Create: `project/preview.py`, `tests/test_preview.py`
- Modify: `project/produce.py` (`project_path`, `preview_path`, the build's last step, the report)
- Modify: `project/app_api.py` (`describe`'s `preview`)
- Test: `tests/test_produce.py`, `tests/test_app_api.py`

**Interfaces:**
- Produces:
  - `preview.SHORT_SIDE = 540`;
  - `preview.size(width: int, height: int) -> tuple[int, int]`: the shorter side 540, the other scaled, both rounded to even;
  - `preview.PreviewError(Exception)`;
  - `preview.render(project: Path, out: Path, width: int, height: int) -> Path`. It renders through `openshot_build.run_script(openshot_render.py, project, <part file>, "--video", w, h)` into `out` with `.part` before `.mp4`, then `os.replace`s it onto `out`. It raises `PreviewError("OpenShot is not installed")` when `openshot_build.install_dir()` is `None`, and `PreviewError` with the last 2000 characters of OpenShot's stderr when the render fails, leaving no part file;
  - `produce.project_path(folder: Path, brief: dict) -> Path` (the stem logic now inline in `build`) and `produce.preview_path(folder, brief) -> Path` (`<stem>-preview.mp4`);
  - the report's `"preview"`: the preview's file name, or `{"skipped": "<why>"}`;
  - `describe(...)["preview"]: str | None`: the preview's absolute path, only when the report is current (`built` is true) and the file is there.
- Consumes: `openshot_build.run_script`, `openshot_build.install_dir`, `look.report`'s place in `build`.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_preview.py`:
    - `test_a_preview_is_540_on_its_shorter_side`: `size(1080, 1920) == (540, 960)`, `size(1920, 1080) == (960, 540)`, `size(1080, 1080) == (540, 540)`.
    - `test_a_failed_render_leaves_nothing`: with `run_script` faked to return code 1 and stderr `"boom"`, `render` raises `PreviewError` containing `boom`, and neither `out` nor its part file exists.
    - `test_without_openshot_there_is_no_preview`: with `install_dir` faked to `None`, `PreviewError("OpenShot is not installed")`.
    - `test_a_real_project_previews_with_its_length_picture_and_sound` (skips unless `openshot_build.is_built()` and `ffprobe` is found): compile a 2-second IR whose one clip is a 1080×1920 test clip made with FFmpeg's `testsrc2` and a sine tone. `render` it at `size(1080, 1920)`. `ffprobe` finds a 540×960 H.264 stream, an AAC stream, and a duration within 0.1 s of 2.0.
  - `tests/test_produce.py`:
    - `test_a_build_records_its_preview`: through `_built` with `preview.render` faked to write the file, the report's `preview` is `"<stem>-preview.mp4"`, and the build printed `==> Making a preview to watch in the app`.
    - `test_a_build_without_openshot_says_the_preview_was_skipped`: `preview` is `{"skipped": "OpenShot is not installed"}`.
    - `test_a_new_build_removes_the_old_preview_first`: a preview file present before a build that fails before its last step is gone afterwards.
  - `tests/test_app_api.py`, `test_describe_names_the_preview_only_while_its_report_is_current`: a current report with the file gives its path; after a storyboard change, or without the file, `None`.
- [ ] **Step 2: Run** `python -m pytest tests/test_preview.py tests/test_produce.py tests/test_app_api.py -q -k preview`. Expected: FAIL (no module `project.preview`).
- [ ] **Step 3: Implement.**
  - `openshot_render.py --video W H` sets the project's `width` and `height` to W and H before `SetJson`, so clips are laid out at that size. It renders picture and sound with:
    - `SetVideoOptions(True, "libx264", fps, W, H, openshot.Fraction(1, 1), False, False, 2000000)`;
    - `SetAudioOptions(True, "aac", sample_rate, channels, channel_layout, 128000)`.

    Without `--video` it renders sound as today. The script stays Python 3.8 with nothing from Frameflow, as its docstring says.
  - In `build`: unlink the old preview beside the old report at the start. After `look.report`, print `==> Making a preview to watch in the app`, render at `preview.size` of the project's width and height, and record `preview` in the report. A `PreviewError` prints `    skipped: <why>` and records it, and the build still ends well.
- [ ] **Step 4: Run** the same command. Expected: PASS (the real render passes on this PC, where Frameflow's OpenShot is built). Then `python -m unittest discover -s tests`. Expected: OK.
- [ ] **Step 5: Commit** (if asked), message "Leave a preview to watch with every build".

---

### Task 4: The preview reaches the window, and Open in OpenShot

**Files:**
- Modify: `app/src/main/media.ts` (`previewAt`, `rangeOf`), `app/src/main/media.test.ts`
- Modify: `app/src/main/ipc.ts` (the scheme's handler; `ff:describe` maps `preview` to a URL; `ff:open`)
- Modify: `app/src/main/index.ts` (the scheme's privileges)
- Modify: `app/src/main/engine.ts` (`build` becomes one `job` for builds and opens), `app/src/main/engine.test.ts`
- Modify: `app/src/preload/index.ts`, `app/src/shared/types.ts`
- Modify: `project/app_api.py` (`open_project`, the `open` command line), `project/editors.py` (`Editor.open` returns whether it did open)
- Test: `tests/test_app_api.py`

**Interfaces:**
- Produces:
  - `previewAt(videos: string, url: string): string | null`: the resolved path, only if it is a file directly inside a video's folder (its folder's parent is `videos`) and its name ends with `-preview.mp4`;
  - `rangeOf(header: string | null, size: number): { start: number; end: number } | 'unsatisfiable' | null`, for `bytes=a-b`, `bytes=a-` and `bytes=-n`; `null` means no usable range, so the whole file;
  - the URL form `ff-media://preview/?p=<encoded path>`;
  - `Described.preview: string | null` in the renderer is that URL;
  - `FrameflowApi.open(folder: string, onEvent: (e: BuildEvent) => void): Promise<void>`, events as a build's;
  - `Engine.open(folder: string, onEvent: (e: BuildEvent) => void): Promise<void>`;
  - `app_api.open_project(folder: Path) -> None`. It prints `==> Opening it in OpenShot` and calls `EDITORS[DEFAULT].open(project_path(...))`. It raises `SystemExit("Build the video first: there is no OpenShot project yet.")` when the project file is not there, and `SystemExit("OpenShot was not found. Open <path> yourself.")` when `open` returns `False`;
  - `Editor.open(project) -> bool`: `True` when shown in an open window or launched.

- [ ] **Step 1: Write the failing tests.**
  - `media.test.ts`:
    - `a video's preview is served, and nothing else in its folder`: `previewAt` gives a `reel/Editing-tier-list-preview.mp4` path. It refuses `reel/storyboard.json`, `reel/app_cache/x-preview.mp4`, a climb out with `..`, and a path outside the videos.
    - `ranges are read as Chromium sends them`: `rangeOf('bytes=0-', 1000)` is `{start: 0, end: 999}`. `rangeOf('bytes=500-599', 1000)` is `{start: 500, end: 599}`. `rangeOf('bytes=-100', 1000)` is `{start: 900, end: 999}`. `rangeOf('bytes=990-2000', 1000)` is `{start: 990, end: 999}`. `rangeOf('bytes=1000-', 1000)` is `'unsatisfiable'`. `rangeOf(null, 1000)` and `rangeOf('items=1-2', 1000)` are `null`.
  - `engine.test.ts`: `open streams its steps like a build, and a failure says why`. The fake engine answers `-m project.app_api open <folder>` with a step and exits 1 with "Build the video first: there is no OpenShot project yet."; the events end `{type: 'done', ok: false, message: …}`.
  - `tests/test_app_api.py`:
    - `test_open_asks_the_editor_to_open_the_built_project`: with the editor's `open` faked to return `True`, it is called with `project_path(folder, brief)`.
    - `test_open_before_any_build_says_to_build_first`: `SystemExit` with that message.
    - `test_open_when_openshot_is_missing_says_so`: `open` faked to `False` gives the not-found message.
- [ ] **Step 2: Run** `npx vitest run src/main` in `app/` and `python -m pytest tests/test_app_api.py -q -k open`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The scheme is registered with `{ standard: true, secure: true, supportFetchAPI: true, stream: true }`.
  - Thumbnails are served as now. For a preview, the handler `stat`s the file and answers from `rangeOf(request.headers.get('range'), size)`:
    - a range: 206 with `Content-Range: bytes a-b/size`, `Content-Length`, `Accept-Ranges: bytes` and `Content-Type: video/mp4`, and a body read with `fs.createReadStream(path, {start, end})` through `Readable.toWeb`;
    - `null`: 200 with the whole file and `Accept-Ranges`;
    - `'unsatisfiable'`: 416 with `Content-Range: bytes */size`.
  - `engine.build`'s spawning, line parsing and tree kill move into one `job(folder, args, onEvent)`. A folder may have one build and one open at a time, each refused while its own is running. `stopAll` ends both.
  - `Editor.open` returns `True` after `live_show` or `Popen`, and `False` where it printed "not found". Its callers are unchanged.
- [ ] **Step 4: Run** the same commands. Expected: PASS. Then `npm test`, `npm run typecheck` and `python -m unittest discover -s tests`. Expected: PASS, clean, OK. **In the real window** (the dev app restarted, since the main process does not reload):
  - thumbnails still load;
  - on the tier-list reel, after a build, a `<video>` pointed at the preview URL can have `currentTime` set to 15 and plays from there;
  - `ff:open` shows the project in Frameflow's OpenShot window.
- [ ] **Step 5: Commit** (if asked), message "Serve the preview to the window, and open the project in OpenShot".

---

### Task 4b: The preview renders after the build

Added on 2026-11-12. Satwik chose this after Task 3's first real preview of the 20-second reel took 31 s to render: at that rate a 15-minute video would add over 20 minutes to every build.

**Files:**
- Modify: `project/produce.py` (`build`'s last steps), `tests/test_produce.py`
- Modify: `app/src/main/engine.ts` (the build job's `built` event and its preview phase), `app/src/main/engine.test.ts`
- Modify: `app/src/shared/types.ts` (`BuildEvent`), `app/src/renderer/src/storyboard/builds.ts` (`Build.state`), `app/src/renderer/src/storyboard/BuildBar.tsx`, `BuildBar.test.tsx`

**Interfaces:**
- Consumes: `preview.render`, `preview_path`, and the report's `preview` field (Task 3); `job()` (Task 4).
- Produces:
  - the build writes `build_report.json` with every check and no `preview` key. It prints `==> Making a preview to watch in the app`, renders, then writes the report again with `preview` (the file name, or `{"skipped": …}`);
  - `BuildEvent` gains `{ type: 'built' }`. The build job sends it when that line arrives, and then `done` when the run ends;
  - `Build.state` gains `'previewing'`. `built` rises on `built` (so the storyboard reloads and shows the checks) and again on `done` (so it picks up the preview);
  - `engine.build(folder)` while that folder's run is in its preview phase stops the run (tree kill) and starts a new build. A replaced run sends no `done`, and its promise resolves.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_produce.py`:
    - `test_the_report_is_written_before_the_preview_is_made`: with `preview.render` faked to read the report when it is called, the report is there, has its `joins` and `picture`, and has no `preview`. After the build it names the preview.
    - `test_a_preview_that_fails_leaves_the_report_and_says_it_was_skipped`.
  - `engine.test.ts`:
    - `a build says it is built when its preview starts, and done when the run ends`;
    - `building again while the preview renders stops that run and starts a new build`: one `ff:build` start, the first run tree-killed, no `done` from it.
  - `BuildBar.test.tsx`:
    - `the storyboard reloads when the build is built, before its preview is made`;
    - `while the preview is made the footer says "Making the preview…" and Build video is offered`.
- [ ] **Step 2: Run** `python -m pytest tests/test_produce.py -q -k preview` and `npm test` in `app/`. Expected: FAIL.
- [ ] **Step 3: Implement.** The footer while previewing shows the report's summary as when idle, and "Making the preview…" as its detail. A run whose preview is skipped still ends well.
- [ ] **Step 4: Run** `python -m unittest discover -s tests`, `npm test` and `npm run typecheck`. Expected: OK, PASS, clean.
- [ ] **Step 5: Commit** (if asked), message "Make the preview after the build, so its checks come first".

---

### Task 5: Space plays a scene, Listen plays a check

**Files:**
- Create: `app/src/renderer/src/player/ScenePlayer.tsx`, `app/src/renderer/src/player/ScenePlayer.test.tsx`
- Modify: `app/src/renderer/src/storyboard/keys.ts`, `keys.test.ts` (Space is `play`)
- Modify: `app/src/renderer/src/storyboard/DetailsPanel.tsx` (`play`, `stop`, the Listen button), `DetailsPanel.test.tsx`
- Modify: `app/src/renderer/src/storyboard/Storyboard.tsx` (`perform('play')`), `Storyboard.test.tsx`
- Modify: `app/src/renderer/src/shell/CommandPalette.tsx` ("Play it", "Listen to its check")
- Modify: `app/src/renderer/src/test-setup.ts` (jsdom has no media playback: `HTMLMediaElement.prototype.play` resolves and `pause` sets `paused`)

**Interfaces:**
- Consumes: `Described.preview` (Task 4), `SceneView.checkAt` (Task 2), `say()` (`shell/Toasts.tsx`).
- Produces:
  - `ScenePlayer({ src, from, to, onEnd, className }: { src: string; from: number; to: number; onEnd(): void; className?: string })`: a `<video>` that seeks to `from`, plays with sound, and at `to` pauses and calls `onEnd` once, checking on `timeupdate` and, where the browser has it, `requestVideoFrameCallback`;
  - `Action` gains `'play'`; `actionFor` maps `' '` (Space) to it outside text fields;
  - `DetailsPanelHandle.play(from: number, to: number): void` and `DetailsPanelHandle.stop(): void`. While playing, the 160×284 frame shows the `ScenePlayer` instead of the picture; it ends by itself, or on Space or Esc;
  - `LISTEN_BEFORE = 1.5`, `LISTEN_AFTER = 1.0` in `player/ScenePlayer.tsx`.

- [ ] **Step 1: Write the failing tests.**
  - `keys.test.ts`: `Space plays outside a field and types a space in one` (`press(' ')` is `'play'`; with `inField`, `null`). Replace the old "Space … maps to nothing" assertion.
  - `ScenePlayer.test.tsx`:
    - `it starts at from and stops at to, once`: after mount the video's `currentTime` is `from`. A `timeupdate` with `currentTime = to` pauses it and calls `onEnd` once, and a second one does not call it again.
    - `a new from seeks again`.
  - `Storyboard.test.tsx`:
    - `Space plays the selected scene from its start and stops at its end`: `tierList` with `preview: 'ff-media://preview/?p=x'`. Select scene 6 and press Space: a video with that `src` is at 8.7. A `timeupdate` at 11.433 ends it, and scene 6's picture is back.
    - `Space on a video changed since its build says to build it, and plays nothing`: with `preview: null`, the toast reads "Build the video to play its scenes." and there is no video element.
  - `DetailsPanel.test.tsx`: `Listen plays from a second and a half before the check to one after`: scene 6 with `checkAt` 11.433 has a Listen button, 32 px tall. It plays from 9.933 and stops at 12.433. With no preview, there is no Listen button.
- [ ] **Step 2: Run** `npm test` in `app/`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `perform('play')` toggles: it plays the selected scene's `start` to `start + seconds` when `described.preview` is set and the scene has a `start`. Otherwise it says "Build the video to play its scenes."
  - The Check row is `May clip “work”` followed by a ghost Listen button with a lucide `Headphones` icon (the sketch's "· Listen").
  - The palette's "This scene" group gains "Play it" (shortcut `Space`) and, when the scene has a check, "Listen to its check"; both are disabled without a preview.
  - Under reduced motion nothing changes: playing is not motion.
- [ ] **Step 4: Run** `npm test` and `npm run typecheck`. Expected: PASS, clean. In the real window, on the built tier-list reel, Space on scene 6 plays it in the frame and stops at its end, and Listen on "May clip “work”" lets you hear the cut.
- [ ] **Step 5: Commit** (if asked), message "Play a scene with Space, and listen to a check".

---

### Task 6: Design the video screen with Satwik (a gate)

**Files:**
- Create: `.impeccable/mocks/decision/video-v1.html` (and later versions as he asks)
- Modify: `.impeccable/surfaces/app.md` (a "Video step" section once he confirms)

This task builds nothing. It ends only when Satwik has confirmed a sketch; Task 7 starts after that, never before.

- [ ] **Step 1: Sketch the screen with Impeccable**, one step at a time as Satwik asked, in the confirmed direction: the storyboard sketch's world, its tokens, type and corners, and the thesis's refusal of "a dark panel with a thumbnail strip under a big preview". What the screen holds is decided; how it is laid out is the sketch's job:
  - the preview in the video's shape, with play and pause;
  - the scenes' rules end to end under it, each as wide as the scene is long: the storyboard's signature move as the way through the video. The current scene's rule is red, a playhead, and a click jumps to a scene;
  - the running time against the target;
  - the checks, each with its time, its wording ("May clip “work”"), its scene, Listen, and "Go to scene 06";
  - Open in OpenShot as the main action, 40 px;
  - the step bar for going back to the storyboard;
  - its states: built and current; the preview still being made (the checks are there, the picture is not yet); not built, or changed since its build (with Build video); building (Build's steps, as the storyboard's footer shows them); a failed build; OpenShot not found.

  Use the tier-list reel (9:16) and the pitch (16:9) as the content, at 1440 × 900 and 1100 × 700.
- [ ] **Step 2: Show Satwik the sketch and ask what to change.** Change it as he asks. **Stop until he confirms.** Do not start Task 7 on a guess.
- [ ] **Step 3: Save what he confirmed** as a "Video step" section in `.impeccable/surfaces/app.md`: the layout, the sizes and the states, in the brief's own form. Name the confirmed sketch's file there.

---

### Task 7: The video screen

**Files:**
- Create: `app/src/renderer/src/video/VideoScreen.tsx`, `app/src/renderer/src/video/SceneRules.tsx`, `app/src/renderer/src/video/Checks.tsx`, `app/src/renderer/src/video/VideoScreen.test.tsx`
- Modify: `app/src/renderer/src/shell/TopBar.tsx` (the steps navigate), `app/src/renderer/src/App.tsx` (the step per video, the motion between steps), `app/src/renderer/src/App.test.tsx`
- Modify: `app/src/renderer/src/player/ScenePlayer.tsx` only if the confirmed sketch's player needs controls the storyboard's does not

**Interfaces:**
- Consumes:
  - `ScenePlayer` (Task 5);
  - `Described.preview` and `FrameflowApi.open` (Task 4);
  - `toView` and `SceneView.checkAt` (Task 2);
  - `useBuild` and `startBuild` (plan 1);
  - the confirmed "Video step" section (Task 6).
- Produces:
  - `type Step = 'storyboard' | 'video'`;
  - `TopBar({ title, step, onStep }: { title: string; step: Step; onStep(step: Step): void })`. Prompt stays disabled with its "not built yet" title until plan 4;
  - `VideoScreen({ folder, described, onGoTo }: { folder: string; described: Described; onGoTo(scene: number): void })`;
  - `Storyboard` gains `initialSelected?: number`, so "Go to scene 06" opens it on that scene.

- [ ] **Step 1: Write the failing tests.**
  - `App.test.tsx`: `the Video step opens the video screen, and Storyboard comes back with the same scene selected`.
  - `VideoScreen.test.tsx`:
    - `a built video shows its preview and one rule per scene, each as wide as the scene is long`;
    - `clicking a scene's rule plays from that scene's start`;
    - `Space plays and pauses, and the arrows jump to the previous and next scene`;
    - `each check is listed with its time, and Listen plays around it` (9.933 to 12.433 for the reel's 11.433);
    - `Go to scene 06 opens the storyboard with scene 6 selected`;
    - `a video changed since its build says so and offers Build video`;
    - `while the preview is being made the screen says so and already lists the checks`;
    - `Open in OpenShot starts opening it and shows its step; a failure says why and stays`.
  - Add the confirmed sketch's own states and sizes as further tests, by their names in the "Video step" section.
- [ ] **Step 2: Run** `npm test` in `app/`. Expected: FAIL.
- [ ] **Step 3: Implement to the confirmed sketch.**
  - Moving from Storyboard to Video slides the screen left and back slides it right, 200 ms on the house easing; reduced motion swaps it for a 150 ms fade.
  - The step bar's buttons are real buttons with `aria-current="step"`.
  - Red keeps its two jobs: the current scene's rule, and the checks' wording.
  - Every control is at least 32 px, and Open in OpenShot is 40 px.
- [ ] **Step 4: Run** `npm test` and `npm run typecheck`. Expected: PASS, clean.
- [ ] **Step 5: Commit** (if asked), message "Watch the video, its scenes and its checks, and open it in OpenShot".

---

### Task 8: Check it against the brief

**Files:** none new; fixes land in the files above, each with a test that fails first.

- [ ] **Step 1:** Run Impeccable's detector: `.claude/skills/impeccable/scripts/impeccable detect --json app/src/renderer/src`. Fix every finding, or name the one you keep and why.
- [ ] **Step 2: A long video.**
  - Write a brief of 600 s for a copy of the tier-list recording in `output/scene-length-check/` (git-ignored). Its storyboard request asks for scenes of about 20 s.
  - Write a storyboard of 30 s scenes over the recording's own pauses and build it. The main track has more clips than there are scenes, every long pause inside a scene is gone, the cut checks include the new cuts, and the storyboard shows about 20 cards with their lengths.
- [ ] **Step 3: The video screen, in the real window** at 1440 × 900 and 1100 × 700, on the tier-list reel and the pitch:
  - build; open the Video step; play and pause with Space; jump with the arrows and the rules; seek late into the preview;
  - Listen on "May clip “work”"; Go to scene 06; Open in OpenShot (Frameflow's OpenShot window shows the project); back to the storyboard;
  - change a scene: the Video step now says it needs building, and Space on the storyboard says so too.

  Check red's two jobs, 32 px targets and the radius scale, and that focus is visible with Tab. Make sure the window is in front: a hidden window draws no frames, so nothing loads as it scrolls.
- [ ] **Step 4:** Show Satwik the running app and ask what to change before plan 4.
- [ ] **Step 5:** Update the vault's status note with what landed and the test counts, and end with a short progress note.
