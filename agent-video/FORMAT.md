# Project format, version 1

This original format is JSON. Time is in seconds; clips play sequentially in array order. Audio and captions use absolute times in the resulting video. Unknown properties are errors, so misspellings do not silently change a production.

```json
{
  "version": 1,
  "title": "My video",
  "canvas": { "width": 720, "height": 1280, "fps": 30 },
  "clips": [
    { "id": "intro", "kind": "color", "color": "#142036", "duration": 2 },
    { "id": "footage", "kind": "video", "src": "assets/shot.mp4", "in": 0, "duration": 3, "volume": 1 }
  ],
  "captions": [
    { "text": "Your opening line", "start": 0, "end": 2, "position": "center", "fontSize": 56, "color": "#ffffff" }
  ],
  "audio": [
    { "src": "assets/music.wav", "start": 0, "in": 0, "duration": 5, "volume": 0.3 }
  ]
}
```

## Validation and defaults

- `version` must equal `1`. `title` is a nonempty string of at most 200 characters.
- `canvas` requires even integer `width` and `height` from 64 through 3840, and integer `fps` from 1 through 60.
- `clips` contains 1–100 items with unique IDs matching `[A-Za-z][A-Za-z0-9_-]{0,63}`. The combined duration cannot exceed 600 seconds.
- Every clip has `id`, `kind`, and either positive `duration` (at least one frame, at most 600 seconds) or `untilWord` as described below. `kind` is `color`, `image`, or `video`. Rendering rounds cumulative clip boundaries to the nearest frame to avoid accumulating timing drift; the reported output duration reflects those frame boundaries.
- Color clips require a six-digit hexadecimal `color` beginning with `#`. They have no `src`, `in`, or `volume`.
- Image clips require `src`; video clips require `src` and optionally `in` (default `0`) and `volume` (default `1`, `0` mutes). Image clips have no `in` or `volume`.
- Local asset `src` paths (at most 4096 characters) must be relative to the project's directory and remain inside that directory after resolving symlinks. Protocols, absolute paths, backslashes, control characters, and parent traversal are rejected. Assets must exist as regular files. Copy your chosen media into the project, then reference it with forward slashes. Project JSON is limited to 2 MiB; text must not contain NUL bytes.
- `captions` defaults to `[]`, with at most 200 entries. Each requires nonempty `text` (at most 1000 characters), `start >= 0`, and `end > start`, no later than total duration. `position` defaults to `bottom` and accepts `top`, `center`, or `bottom`; `fontSize` defaults to `48` and is an integer from 12 through 200; `color` defaults to `#ffffff`. Explicit newlines are supported; text does not wrap automatically.
- `audio` defaults to `[]`, with at most 16 tracks. Each requires `src`, `start >= 0`, positive `duration`, and must finish within the timeline. `in` defaults to `0`; `volume` defaults to `1`. All volumes range from `0` through `4`.
- All numbers must be finite. Clip and track source offsets are nonnegative. Video sources shorter than the requested interval are rejected before rendering. Image frames are held for the requested duration. Video audio is preserved at the selected volume; videos without audio and non-video clips receive silence. Additional tracks mix with the clip audio.

Images and videos scale and crop to fill the canvas. Caption text is literal, never executable filter syntax. The renderer uses a local font selected by the tool. Font availability, glyph coverage, and line lengths should be checked in the rendered preview.

Media is restricted to self-contained MP4/MOV/M4A/3GP, Matroska/WebM, AVI, MPEG-TS, MP3/AAC, WAV, FLAC, Ogg, and PNG/JPEG/WebP/BMP/TIFF inputs. Image signatures select a single-file demuxer and image clips hold the first decoded frame. Playlists, image sequences, SVG, and network sources are unsupported even if renamed to a supported extension. FFmpeg input format and protocol allowlists prevent an in-project playlist from opening other paths.

## Internal boundary

`src/project.mjs` exports synchronous `validateProject(value)` → a normalized project, asynchronous `loadProject(file)` → `{ project, projectPath, root }`, and `ProjectError` with `code` and optional `details`. Validation failures use `INVALID_PROJECT`; unreadable manifests use `PROJECT_READ_FAILED`; bad asset access uses `INVALID_ASSET`.

`src/render.mjs` exports asynchronous `checkTools()` → `{ ffmpeg, ffprobe }` version strings, `probeMedia(path)` → FFprobe JSON, and `renderVideo(loaded, { workDir, onProgress, signal })` → `{ file, duration, width, height, fps }`. It writes `render.mp4` inside the caller-owned, newly created work directory and never touches user-selected output paths. `onProgress` receives `{ stage, completed, total }`. The optional `signal` cancels owned render subprocesses. `FFMPEG_PATH` and `FFPROBE_PATH` select existing executables; they are never passed to a shell.

The CLI/job runner owns creating isolated job directories, recording status, publishing the completed file without overwrite, and retaining failures. Renderer and project modules do not import the reference project or research tools.

The separately versioned reference/Frameflow preparation interface is documented in `FRAMEFLOW.md`. It emits Frameflow-compatible storyboard documents, not version-1 Agent Video render projects. Do not pass one format to the other's renderer or infer source-clock cuts from output-clock word IDs. The package's public import entry exports the preparation APIs; this local render format remains version 1.

## Word timing and anchored captions

An optional `words` array stores supplied timestamps, not inferred speech timing:

```json
{
  "words": [
    { "id": "w1", "text": "Make", "start": 0.2, "end": 0.5 },
    { "id": "w2", "text": "something.", "start": 0.55, "end": 1.1 }
  ],
  "captions": [
    { "fromWord": "w1", "toWord": "w2", "position": "center" }
  ]
}
```

`words` defaults to `[]`, with at most 2000 entries. Each has a unique `id` using the clip-ID syntax, nonempty `text` of at most 200 characters, finite `start >= 0`, and `end > start` no later than the project duration. Words appear in chronological order and do not overlap. Word IDs and clip IDs occupy separate namespaces.

A caption uses either explicit `text/start/end`, or `fromWord/toWord` referencing an inclusive range in `words`. The two timing forms cannot be mixed. An anchored caption's optional `text` overrides its displayed wording; without it, the range's word text is joined with spaces (at most 1000 characters). Its start and end resolve from the first and last referenced word on every check, plan, and render. Reversed or unknown word IDs fail validation. Style fields and the 200-caption limit are unchanged. Normalized project JSON retains the anchors and preserves omitted text, so changing words does not freeze the old timing or wording.

`src/project.mjs` additionally exports `resolveCaptions(project)` → timed caption objects without modifying the project, and `validateAssets(project, root)` → asynchronous regular-file and canonical-confinement checks shared by loading and batch preflight.

## Word-linked cuts and overlays

A clip may have `untilWord: "word-id"` instead of `duration`. Its end is that word's end timestamp, and its start is the preceding clip's end (or zero). The resolved duration must span at least one output frame, including cumulative frame rounding. Unknown/backward word IDs, mixed `duration/untilWord`, and effects that no longer fit a retimed clip are errors. Normalization retains the word reference and never writes a stale derived duration into the project.

An overlay may use `fromWord/toWord` instead of `start/duration`, deriving the inclusive range's start and end. Mixed, unknown, or reversed anchors fail. `resolveClips(project)` and `resolveOverlays(project)` return fresh numeric render inputs without changing the editable declarations. `plan` exposes their current times. Words validate first against the 600-second ceiling and then against the complete resolved timeline.

## Overlays, clip effects and audio fades

Optional `overlays` defaults to `[]` (max 32). Each overlay requires unique clip-style `id`, `kind` (`image` or `video`), `src`, and a timing form plus `rect: {x,y,width,height}`. Rectangle coordinates and dimensions are integers; dimensions are positive and the whole rectangle stays inside the canvas. `opacity` defaults to 1 and ranges 0–1. Video overlays have optional nonnegative `in` (default 0). Image overlays hold their first decoded frame. They crop to fill the rectangle and are visible only in the selected timeline window. Source duration and local asset boundaries are checked. Overlay audio is muted; use a separate audio track for wanted sound.

```json
{
  "overlays": [
    { "id": "insert", "kind": "video", "src": "assets/broll.mp4", "start": 1, "duration": 2,
      "in": 0, "opacity": 0.9, "rect": { "x": 20, "y": 20, "width": 240, "height": 180 } }
  ]
}
```

Optional clip `effects` accepts only `fadeIn`, `fadeOut` (nonnegative seconds whose sum fits the resolved clip duration), `zoom` (centered constant zoom, 1–2), `brightness` (-1–1), `contrast` (0–3), and `saturation` (0–3). Defaults are 0 for fades/brightness and 1 for zoom/contrast/saturation. Effects are applied to the clip picture and participate in base-segment cache keys. They contain numbers, never executable FFmpeg expressions.

Audio tracks optionally accept `fadeIn` and `fadeOut`; both default to zero and must sum to no more than track duration. Fades apply to the local trimmed track before its start delay and final mix. Existing clip audio remains preserved unless muted.

`src/captions.mjs` exports `groupWordCaptions(words, maxWords = 4)` → anchored caption objects. It groups up to `maxWords` (integer 1–12) and starts a new group after a gap greater than 0.6 seconds or before joined text exceeds 1000 characters. It refuses input requiring more than 200 captions; it never truncates the transcript. The CLI `captions project.json --words words.json --out sibling.json [--group-size 4]` replaces `words` and `captions` using a nonempty JSON array of the word objects above. The new project stays beside the source, is validated, and never overwrites a file. This imports supplied timings; no transcription or alignment model runs.

## Batch variants and clip reuse

`batch project.json --variants variants.json --out-dir new-directory` accepts a JSON array of 1–100 objects `{ "id": "opening-a", "patch": { "title": "Opening A" } }`. IDs are unique, case-insensitively, match the clip-ID syntax, and cannot be Windows device names. Patch fields replace top-level project fields exactly as in `variant`; all resulting projects and assets are validated before creating the output directory. Relative assets retain the original project root.

The output directory must not exist. Variants run sequentially and produce `<id>.mp4`; `batch.json` records each pending/running/succeeded/failed/cancelled variant, job IDs, errors, and artifact metadata. A failed variant does not prevent later variants. Cancelling stops the current job and leaves remaining variants cancelled. The CLI returns a nonzero status unless every variant succeeds; completed outputs remain available. Each job retains its normalized editable project snapshot under the original project's `.agent-video/jobs/` directory.

`src/batch.mjs` exports `runBatch(loaded, variants, outDir, { signal, onProgress, render })` → a final batch record; `render` is an optional test seam forwarded to `runJob`. `src/jobs.mjs` forwards an optional shared `clipCache` Map to the renderer and records optional returned `cache` statistics in the artifact.

`renderVideo` accepts optional `clipCache`. Keys include encoded frame count, canvas, clip material/offset/volume/effects, source content hash, and encoder identity. Caption wording, clip IDs, overlays, and added audio do not affect base-segment reuse. Entries reference verified intermediate files; cache hits copy a valid segment into the current isolated job. Changed source bytes/settings or a missing/corrupt intermediate force a new segment encode. Reuse occurs within a running batch and across explicit resumes, and never skips final overlay/caption/audio composition. Returned `cache` is `{ hits, misses }`.

## Saved execution and resume

Every completed/reused segment is recorded in its job's `segments.json`: `{version:1,segments:[{key,file,sha256,bytes}]}`. Filenames are generated `clip-N.mp4` only. Resume loaders enforce regular files, canonical containment, file/count/size bounds and actual content digests. Stored project snapshots retain original asset roots and editable anchors; resume revalidates their schema and current assets. State updates use exclusive UUID temporary files and atomic rename.

`resume <project-directory> --job UUID [--out output.mp4]` creates a new foreground job for a failed, cancelled, or interrupted `running` job. It records `resumedFrom`, preserves old records, and refuses existing outputs. An old `running` record is not proof its process stopped; the tool does not terminate it or mutate its state.

`resume-batch <batch-directory>` loads the immutable base project and saved patches, checks successful output digests, and starts only unfinished cuts. It retains earlier job IDs. Concurrent batch run/resume is refused by an OS-owned endpoint lock; a crash releases ownership without relying on stale PID files. There is no automatic background worker. A corrupt/missing successful output is reported explicitly and never overwritten as part of resume.
