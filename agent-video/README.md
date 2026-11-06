# Agent Video

An independently written local video tool for coding agents. The agent writes an editable JSON project; the CLI validates it, renders an MP4, and records what happened. It uses no Hypit packages or runtime and has no JavaScript dependencies.

An agent can inspect a reference, reconstruct an editable project, transcribe local speech, bind cuts/B-roll/captions to word IDs, composite supplied media, render variants, and resume interrupted work. Generation is excluded: the tool has no image, voice, or video generation service. It uses supplied local material and has no embedded LLM or web editor.

Version 1.1 also prepares reference workflows for Frameflow: measured reference evidence, agent-authored analysis and 2–3 concepts, strict storyboard/source-time checks, safe sample storyboards and a versioned handoff. It leaves Frameflow's code, native editor projects and manual-edit history untouched. Read [FRAMEFLOW.md](FRAMEFLOW.md) for the exact commands and public module API. Main Frameflow integration and native-editor execution remain the Frameflow developer's work; a rendered MP4 is not that handoff.

## Run it

Requirements: Node.js 22 or newer and FFmpeg/FFprobe on `PATH`. FFmpeg must support loading filter arguments with `-/filter_complex` and include `libx264`, AAC encoding, and `drawtext` (verified here with FFmpeg/FFprobe 9.0.1). The file-based filter option is described in the [official FFmpeg options](https://ffmpeg.org/ffmpeg.html#Options). Captions use an installed Arial, DejaVu Sans, or Liberation Sans font. Set `FFMPEG_PATH` and `FFPROBE_PATH` to executable paths when necessary. Local transcription additionally needs whisper.cpp and a compatible model. No JavaScript dependency installation, API key, or model-service credits are required.

Run directly from this source directory, or install a locally built archive into a separate directory:

```powershell
npm pack
npm install --prefix ./agent-video-install --ignore-scripts ./agent-video-local-1.0.0.tgz
npm exec --prefix ./agent-video-install --no -- agent-video --help
```

No global installation or registry publication is required. The examples below use the source launcher:

```powershell
node bin/agent-video.mjs doctor
node bin/agent-video.mjs init my-video
node bin/agent-video.mjs check my-video/project.json
node bin/agent-video.mjs plan my-video/project.json --json
node bin/agent-video.mjs render my-video/project.json --out output/my-video.mp4
```

`init` writes a six-second portrait example. Replace its color scenes with your own media: put files in `my-video/assets/`, use `kind: "video"` or `kind: "image"`, and supply `src: "assets/your-file.mp4"`. Video clips preserve source audio by default; set `volume: 0` to mute. Images and video crop to fill the selected canvas.

Read [FORMAT.md](FORMAT.md) for the complete project contract. Supported input families are MP4/MOV/M4A/3GP, Matroska/WebM, AVI, MPEG-TS, MP3/AAC, WAV, FLAC, Ogg, and PNG/JPEG/WebP/BMP/TIFF images. Image clips hold their first frame. Playlists, image sequences, SVG, and network inputs are deliberately rejected; convert them into a self-contained media file first. Captions support explicit line breaks, color, size, and three positions. They do not automatically wrap, so inspect your output when changing wording or canvas size.

## Inspect and reconstruct a reference

```powershell
node bin/agent-video.mjs inspect reference.mp4 --out-dir evidence --scene-threshold 0.3 --json
node bin/agent-video.mjs reconstruct reference.mp4 --out-dir my-project --scene-threshold 0.3 --json
```

Inspection saves actual stream metadata, a source digest, scene-cut candidates, representative frames, and a contact sheet in the new directory. Continuous shots receive multiple samples too. `report.json` records requested and actual frame seek times, the threshold, and whether the cut limit was reached. Lower the threshold to detect subtler changes; cut detection is a pixel-change heuristic, not semantic understanding.

Inspection and transcription require timed audio/video of at most ten minutes. Static image assets are supported in authored clips and overlays.

Reconstruction copies the source into the new project's `assets/` and creates sequential video clips at the detected cuts, preserving source audio and offsets. It retains inspection evidence beside the editable `project.json`. Review it with your agent, then change the material, timing, captions and overlays. Reconstruction does not infer a hidden original project, create replacement footage, or reproduce unseen effects automatically. An agent uses the evidence to author those editing decisions. Existing output directories are refused; source media is never moved or overwritten.

## Transcribe speech locally

Install an official [whisper.cpp release](https://github.com/ggml-org/whisper.cpp/releases) and a [compatible ggml model](https://github.com/ggml-org/whisper.cpp/tree/master/models). Point this shell at the files:

```powershell
$env:WHISPER_CPP_PATH = 'C:\tools\whisper\whisper-cli.exe'
$env:WHISPER_CPP_MODEL = 'C:\tools\whisper\ggml-tiny.en.bin'
node bin/agent-video.mjs doctor --json
node bin/agent-video.mjs transcribe reference.mp4 --out-dir speech --language en --json
node bin/agent-video.mjs captions my-project/project.json --words speech/words.json --out my-project/timed.json
```

The command extracts 16-kHz mono audio, runs the selected local recognizer, and writes measured `words.json`, `report.json`, prepared audio and raw recognition JSON. The CLI uses whisper.cpp's word segmentation and full JSON output; it never spreads a transcript evenly across a duration. Recognition and word boundaries can be wrong, especially with noise or a small model: check the words against the recording before making precise edits. Use a matching multilingual model and `--language auto` or another supported language when needed. English was verified with the official tiny.en model; recognition quality is not guaranteed for other model/language combinations.

`doctor` checks the configured executable/model files; it does not download or silently install them. The external executable and model stay outside the product package. Whisper.cpp word timing is documented as [experimental](https://github.com/ggml-org/whisper.cpp#word-level-timestamp-experimental).

## Make a second cut

Write a small JSON object containing top-level fields to replace. Arrays replace the entire original array; they do not merge by ID.

```json
{
  "title": "My second cut",
  "captions": [
    { "text": "A different opening", "start": 0, "end": 2, "position": "center" }
  ]
}
```

Save it as `edits.json`, then:

```powershell
node bin/agent-video.mjs variant my-video/project.json --patch edits.json --out my-video/second.json
node bin/agent-video.mjs check my-video/second.json
node bin/agent-video.mjs render my-video/second.json --out output/second.mp4
```

Variants stay beside the source project so their relative media paths remain valid. The command checks the resulting schema and local assets. Use `plan` to inspect its resolved timeline before rendering. You can also edit or duplicate project JSON directly.

## Captions that follow word timing

Supply a JSON array of timed words with stable IDs:

```json
[
  { "id": "w1", "text": "Hello", "start": 0.2, "end": 0.5 },
  { "id": "w2", "text": "there.", "start": 0.6, "end": 1.0 }
]
```

Import it into an editable sibling project:

```powershell
node bin/agent-video.mjs captions my-video/project.json --words words.json --out my-video/timed.json --group-size 4
node bin/agent-video.mjs plan my-video/timed.json --json
```

The command replaces the project's words and captions, grouping at most four words per caption by default. A pause longer than 0.6 seconds starts a fresh group. Each saved caption retains `fromWord` and `toWord`; it does not freeze a derived timestamp or wording. Editing the words' timestamps or text updates the caption when the project is checked or rendered. An optional caption `text` overrides the displayed wording while keeping its time anchors. Existing numeric captions continue to work.

The `captions` command only imports the supplied timestamps; use `transcribe` to measure a recording first. The bundled `examples/hello/words.json` is an authored timing fixture for a silent graphic demo, not measured speech.

## Picture changes and effects

A clip may use `untilWord: "w6"` instead of `duration`, ending at that word's current end time. Subsequent clips remain sequential. An overlay may use `fromWord/toWord` instead of numeric `start/duration`. Editing word timestamps moves the corresponding cut, B-roll window and captions together; `plan --json` shows resolved numeric times.

`overlays` composites up to 32 supplied images/videos into validated canvas rectangles, with explicit timing, source offset and opacity. Overlay sound is muted; add wanted sound explicitly to `audio`. Clip `effects` provides fade-in/out, centered zoom, brightness, contrast and saturation. Audio tracks support local fade-in/out. All fields and limits are in [FORMAT.md](FORMAT.md); raw filter strings are not accepted.

## Render a batch

Create a JSON array of named top-level project patches:

```json
[
  { "id": "cut-a", "patch": { "title": "First cut" } },
  { "id": "cut-b", "patch": { "title": "Second cut", "captions": [
    { "text": "Another opening", "start": 0, "end": 2 }
  ] } }
]
```

```powershell
node bin/agent-video.mjs batch my-video/project.json --variants variants.json --out-dir output/my-batch --json
```

The output directory must be new. All patches and asset paths are checked before it is created. Each variant runs as a separate recorded job and produces a named MP4. `batch.json` records outcomes, job IDs, errors, and output metadata; successful cuts stay available if another fails. The command exits nonzero for a failed, partial, or cancelled batch. Ctrl+C cancels the active job and marks the remaining cuts cancelled.

Within that batch, unchanged clip segments are reused. Keys include source file content, clip settings/effects, frame count, canvas, and encoder identity. Corrupt or missing intermediates are encoded again. Overlay, caption and audio composition still runs for each cut. Verified segment metadata is also retained for explicit resume. There is no global cache service. Artifact metadata reports `cache.hits` and `cache.misses`.

The bundled example makes three cuts with two full sets of matching segments and one changed scene:

```powershell
node bin/agent-video.mjs captions examples/hello/project.json --words examples/hello/words.json --out examples/hello/timed.json
node bin/agent-video.mjs batch examples/hello/timed.json --variants examples/hello/variants.json --out-dir output/word-cuts
```

## Use with an agent

Tell the agent to read [`skills/agent-video/SKILL.md`](skills/agent-video/SKILL.md), give it a brief and local media, and ask it to produce a video using this CLI. The skill is shipped here as an original instruction file; it has not been installed globally or registered in an agent configuration. A starting prompt:

> Read skills/agent-video/SKILL.md. Make a six-second vertical video using the local assets in my-video/assets. Write the project, check and plan it, render the MP4, inspect frames and audio, then return the output and the editable project.

The CLI has no embedded LLM. The coding agent provides creative decisions and edits JSON. This version makes no network requests or paid generation calls.

## Inspect jobs and failures

Each render prints a job UUID. Records, the exact normalized project snapshot, caption files, and intermediate media live in `.agent-video/jobs/<UUID>/` beside the project. Work runs in the foreground; progress uses stderr. Add `--json` to any command for one structured stdout result. Validation failures exit `1`; command usage errors exit `2`.

```powershell
node bin/agent-video.mjs status my-video/project.json --job <UUID> --json
```

The status record contains success/failure, output metadata, and a SHA-256 digest on success. Existing outputs are always preserved; choose a new output name to render again. Failed renders retain their job records and do not publish a video. Ctrl+C cancels the owned render subprocess and records cancellation. Source media must be long enough for the requested offsets and durations.

Resume a failed, cancelled or interrupted job as a new job, using its saved project and original asset root:

```powershell
node bin/agent-video.mjs resume my-project --job <UUID> --json
node bin/agent-video.mjs resume my-project --job <UUID> --out output/retry.mp4 --json
node bin/agent-video.mjs resume-batch output/my-batch --json
```

Resume validates current assets and verified segment files, preserves old job records, and records the new job's `resumedFrom`. A resumed batch reruns unfinished cuts and preserves successful output digests and job IDs. Missing/corrupt successful output is an error; the tool will not silently overwrite it. Concurrent batch execution/resume is refused through an OS-owned local execution lock, released when the process exits or crashes. A standalone resume starts a new foreground job; it never kills or assumes ownership of an earlier process. There is no detached worker, automatic retry daemon, or hidden background generation.

Job folders can contain a temporary copy of an installed font for rendering. Keep these local working files out of product distribution and source control. Intermediate files are retained for diagnosis; there is no automatic cleanup policy yet.

## Verify

From the source checkout:

```powershell
npm test
npm run demo
npm pack --dry-run
# With a supplied speech video and configured local recognizer:
node scripts/smoke.mjs reference.mp4 output/full-workflow-check
# Standalone reference-to-Frameflow handoff, with synthetic media:
node scripts/frameflow-smoke.mjs output/frameflow-check
```

Tests include real FFmpeg renders, not only command construction. They check output dimensions, frame order, literal and anchored captions, audio, invalid media, cancellation, asset confinement, structured CLI failures, batch outcomes, content-based reuse, output preservation, reference evidence and Frameflow handoff contracts. Integration tests require the rendering prerequisites above. The package allowlist includes implementation, original instructions, smoke scripts, product documentation and four example JSON files; reference research, Frameflow source/schemas and job artifacts are excluded.

The smoke command exercises source inspection, editable reconstruction, actual transcription, word-linked picture/caption edits, variants, output verification and interrupted-render resume. It requires a local speech video and an empty new output directory. The runtime was verified on Windows; other platforms have not been exercised. There is no automatic arbitrary-script forced alignment, semantic scene understanding, graphical editor, or AI media generation. Those are not claimed by the supplied-media workflow.
