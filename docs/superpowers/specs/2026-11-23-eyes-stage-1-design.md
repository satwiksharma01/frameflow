# The agent's eyes, stage 1: studying clips, a shot list, and a look at the result

**Date:** 2026-11-23 · **Status:** design, for Satwik's approval · **Research:** [2026-11-22-cardboard-research.md](2026-11-22-cardboard-research.md) (section 7), [2026-11-22-eyes-open-source-research.md](2026-11-22-eyes-open-source-research.md) · **Comes before** the taste engine ([2026-11-22-taste-engine-design.md](2026-11-22-taste-engine-design.md)), whose direction step will read the shot list this produces.

## Intent

Frameflow's agent cannot see inside the creator's clips, and never looks at what it built. Run 11 (the outfit reel, 2026-11-22) needed frame sheets made by hand to find its shots. Its first build drew an album cover over the whole video, and the picture check passed it, because the check tests three faults and judges nothing else. Cardboard's agent studies the footage, edits, then looks at its own frames. This stage gives Frameflow's agent the same machinery, with free tools, and leaves the local models (CLIP search, Florence-2 descriptions) to stage 2 (Satwik, 2026-11-23: "Stage it").

## Goals

- **Every video clip gets a study at prepare:** shot cuts, a frame sheet with each frame's time on it, quality measures per frame, and where someone is actually speaking. Both recordings and picture-or-clip assets get one; still images don't.
- **The agent writes the clip's moments from its sheet:** what is seen, from when to when, how it is framed. Requests then carry a **shot list**, one line per moment, so the brief and the storyboard choose real moments by time.
- **The agent can ask for a closer look** at any stretch of a clip.
- **After a build, a look step:** a frame sheet of the finished preview, judged by the agent against the plan; its findings go to the creator.
- **Speech means speech:** the speech check counts where someone talks, not where there is sound. A music-only clip added as a recording gets a message saying so, and transcript segments over no speech at all are dropped.
- **The app's start job runs the describe step** when its thinker can see images, with no new screens.

## Non-goals

- CLIP search by meaning, Florence-2 descriptions, a library-wide index across videos: stage 2.
- Cutting the subject out (rembg) or full-body tracking (MediaPipe): with piece 2's edits, where text first needs to sit behind someone.
- The look step in the app, which needs a place on screen: piece 6.
- Fixing what the look finds without the creator.
- Changes to the storyboard's schema: scenes already name a clip and a start time.

## Anti-goals

- Sending whole videos or every frame to the agent: one sheet per clip, closer looks only on request.
- An agent that trusts its plan over its eyes: the look step judges the real render.
- Silently changing what was said: only segments entirely outside speech are dropped, and the count is reported.

## Constraints

- No PyTorch. Speech detection uses Silero VAD (MIT, about 2 MB) through ONNX Runtime, which is already installed with Piper.
- Everything else is ffmpeg, OpenCV and NumPy, all already dependencies.
- The model downloads on first use into the git-ignored `models/` folder, as the whisper model does.
- CI has no Silero model. Its logic is tested with a stand-in, and the one test on the real model skips without it.
- The engine never calls a model itself; it writes requests and checks answers.
- The repository is public; a study is written into the video's folder under `output/`, which is git-ignored.
- Each file keeps its own line endings.

## Approaches considered

1. **Local models build a full shot index now** (CLIP, Florence-2, plus everything below). This is the cheapest per video and gives search across a library. It's also the most code, about 600 MB of downloads, and slower prepares.
2. **Only the agent's own eyes:** sheets, and the agent describes every clip. It's the least code, but it costs agent time per clip and has no vector search.
3. **Staged (chosen, 2026-11-23).** This stage is the deterministic eyes (cuts, sheets, quality, speech), the agent's moments, and the look step. Stage 2 adds CLIP and Florence-2 where libraries grow or agent time costs too much.

## The design

### A clip's study

`python -m project.eyes study <clip> <out dir>`, called by prepare for each video clip, writes `<video>/eyes/<clip stem>/`:

| File | Holds |
|---|---|
| `study.json` | `source`, `stamp` (path, bytes, modified time: the cache key), `duration`, `size`, `fps`, `cuts` (seconds), `step`, `samples` (per sampled frame: `t`, `sharp`, `bright`, `motion`), `speech` (regions in seconds), `speech_seconds`, `sheets` (paths) |
| `sheet.jpg` | the sampled frames tiled 10 across, each stamped with its time |

- **Cuts:** ffmpeg's scene score above 0.3, a named constant. Many phone clips are one long take and have none; their moments come from the agent, not from cuts.
- **Sampling:** one frame every `step` seconds, where `step` is the larger of 0.5 s and the clip's length divided by 60. So a sheet never holds more than 60 frames: a 9 s clip gets 18 frames, a 10-minute recording one every 10 s.
- **Quality, per sample:**
  - `sharp`: the variance of the Laplacian of the grey frame;
  - `bright`: mean luma, 0 to 255;
  - `motion`: the mean absolute difference from the previous sample.
  - **Flags** come from these: `soft` when `sharp` is under 40% of the clip's own median, `dark` under 40, `blown` over 220, `shaky` when `motion` is over a named constant.
- **Speech:** Silero VAD over the clip's audio at 16 kHz mono gives speech regions. A clip with no audio has none.
- **Cache:** a study whose stamp matches its clip is reused, so a re-prepare or Try again doesn't redo it.

### A closer look

`python -m project.eyes sheet <clip> --from S --to E [--per-second N]` writes a sheet of just that stretch, 4 frames a second unless told otherwise. It prints the path. The agent uses it when the clip's sheet is too coarse, as run 11's shots were found at 4 frames a second.

### The describe step, and the shot list

When a video has clips, prepare writes `eyes/shots_request.md` instead of pointing straight at the brief:
- **It holds:** each clip's name, length, cuts, speech summary, quality flags and sheet path.
- **The task:** open each sheet and write `eyes/<stem>/moments.json`, a list of moments, each with:
  - `start` and `end`, in seconds;
  - `what` (what is seen, in a sentence);
  - `framing`: `close`, `medium` or `wide`;
  - `subject` (who or what is in focus);
  - `notes` (optional, such as "turns to camera", "holds the tote up").

  Moments split at cuts and at visible changes: a turn, a gesture, something held up to the camera.
- **Then:** run `python -m project.produce <folder> --shots`. That checks every `moments.json` (inside the clip, in order, no overlaps, fields filled, framing from the list) and then writes the brief request.
- **Moments are cached** with the study, so a clip is described once.

**The shot list** is the moments, one line each, built from `moments.json` and `study.json`:

```
- VID-20260830-WA0023.mp4 8.3–9.7 s · medium · turns from side-on to face the camera, smiles · sharp
- VID-20260830-WA0021.mp4 11.9–13.2 s · medium · fixes the henley's shoulder · sharp
```

- **Who gets it:** the brief request and the storyboard request carry it under "What the creator provided", in place of the bare clip line. A clip without moments (a thinker that can't see, or none written) gets one line from its study alone: length, cuts, speech, flags.
- **Token budget:** lines only, never sheets or sample tables.

### Speech means speech

For recordings, in `first_cut.prepare`, once the Silero model is installed:
- **The transcript gains `speech`:** an optional list of regions in seconds, added to `transcript.schema.json`. Every later step reads it from there.
- **What the speech check counts:** `ensure_speech` counts the VAD's speech seconds instead of all non-silent time.
- **Its message names the likely cause:** "no usable speech: 0.4 s of speech in the 13.7 s recording. If this clip has no talking, add it as a picture or clip, not as a recording."
- **Dropped segments:** transcript segments with no overlap at all with any speech region are dropped before the timing map is built (whisper invents words over music). The number dropped is printed with the transcript's counts.

Without the model, everything works as today.

### The look step

`python -m project.produce <folder> --look`, after a build:
1. **Makes `look/sheet.jpg` from the built preview:**
   - frames every max(0.5 s, length ÷ 40);
   - plus 0, 0.5, 1.0, 1.5 and 2.0 s for the hook, and the first frame of every scene;
   - each stamped with its time and scene number.
2. **Writes `look/request.md`.** It holds the brief, the storyboard's scenes with their built times (from `build_report.json`), the direction contract when `direction.json` exists, and the picture check's and the check by ear's findings. It asks the agent to open the sheet and judge:
   - (1) each scene shows what the storyboard says;
   - (2) the first two seconds deliver the hook;
   - (3) text is readable, inside the frame and the platform's safe area, and off faces. For a vertical frame the request names the area: clear of the top 14% and the bottom 35%, and of 6% at each side (Meta's guide for Reels; Shorts and TikTok keep more clear on the right);
   - (4) nothing is on screen that shouldn't be (a stray picture, black, a wrong crop);
   - (5) the rhythm of the cuts;
   - (6) the direction, when there is one.

   The answer goes in `look/look.json`: `verdict` (`good` or `fix`) and `findings`, each with `at` (seconds), `scene` (optional), `what` and `fix` (in words).
3. **Run again,** `--look` checks `look.json` against its schema and prints the verdict and findings.

The skill shows the creator the findings. With their OK it makes the fixes, as storyboard changes, and rebuilds, for at most two rounds before the creator decides. Nothing is fixed without the creator.

### The app

- **`app_think.start` runs the describe step between prepare and the plan** when its thinker can see images. The step shows as "Looking at your clips with <thinker>". Checks and fix rounds work as for the plan.
- **Thinkers gain `can_see`:** Claude Code is true. OpenCode and an API key are false in this stage. Their shot list is the study alone.
- **No new screens,** and the look step stays out of the app (piece 6).

### The skills

- **`produce`:**
  - after Prepare, a **Describe** step (read the shots request, open each sheet, write moments, run `--shots`);
  - the Storyboard step points at the shot list;
  - after Build, a **Look** step (run `--look`, open the sheet, write `look.json`, show the creator, fix with their OK).
- **`first-cut`:** its "no usable speech" line mentions the new message.

### Files

| File | Change |
|---|---|
| `project/eyes.py` (new) | `study`, `sheet`, quality measures, the shot list, the CLI |
| `project/vad.py` (new) | Silero VAD through ONNX Runtime: install, speech regions |
| `project/schema/study.schema.json`, `moments.schema.json`, `look.schema.json` (new) | the three documents |
| `project/produce.py` | studies at prepare; `--shots`; `--look`; the shot list in the brief and storyboard requests |
| `project/first_cut.py`, `project/editor_agent.py` | speech seconds from the VAD; segments outside speech dropped; the new message |
| `project/app_think.py`, `project/thinkers.py` | the describe step; `can_see` |
| `.claude/skills/produce/SKILL.md`, `.claude/skills/first-cut/SKILL.md` | the steps |

## Tests

- **A study of a generated clip:**
  - 2 s red, then 2 s blue: one cut near 2.0 s, a sheet with 8 frames, a study that passes its schema;
  - a blurred half scores lower `sharp` and is flagged `soft`;
  - a black clip is flagged `dark`;
  - a matching stamp reuses the study.
- **A closer look:** a sheet for 1–2 s at 4 per second holds 4 frames.
- **Speech, with a stand-in VAD:**
  - `ensure_speech` refuses a transcript whose speech regions sum under the minimum and names "picture or clip";
  - a segment with no overlap with speech is dropped and counted;
  - one that overlaps partly is kept;
  - without the model, the old measure is used.
  - **The real model (skipped without it):** a tone has no speech.
- **Moments:** refused past the clip's end, out of order, overlapping, or with an unknown framing.
- **The shot list:** one line per moment with its flags; a clip without moments gets its study line; no sheet path or sample in a brief or storyboard request.
- **The look step:**
  - the request carries every scene with its time, the hook frames, and the direction when there is one;
  - `look.json` is refused without a verdict, or with a finding outside the video's length.
- **The app:** a stand-in thinker with `can_see` true gets the shots request before the plan; one with false goes straight to the plan.

## Left to the builder

Exact constants (the scene threshold, the shaky threshold), the sheet's tile size and font, how timestamps are drawn when no system font is found, the wording of the requests, and how findings print. Two clips with the same file name in different folders get distinct `eyes/` folders (a numeric suffix). When a build made no preview, `--look` refuses with a message that says so.

## Frameflow's calls, for Satwik to check

- **The look reports and the creator decides.** That's Frameflow's existing rule ("Only what is wrong is reported; the creator decides") and Cardboard's "you're always in control". No automatic fix rounds.
- **The app gets the describe step now,** but the look step waits for the app's own piece, because it needs a place on screen.
- **Only Claude Code counts as able to see** in this stage.
- **Segments entirely outside speech are dropped**; ones that overlap speech even slightly are kept.
- **One sheet per clip, at most 60 frames;** closer looks on request.
- **Studies live in `<video>/eyes/`,** one folder per clip. A library-wide cache waits for stage 2.
