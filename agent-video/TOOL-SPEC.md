# Agent Video: complete supplied-media tool

The user requested the complete tool and explicitly excluded generation on 2026-10-31. This specification preserves that scope. Image, voice and video generation, paid provider connectors, and a new web interface are excluded. The coding agent makes creative decisions; the local CLI supplies reliable inspection, transcription, editing, rendering and revision tools. No reference implementation is a dependency or source of copied code.

## Required capabilities

1. Preserve the existing original project format, command-line/agent workflow, validation, local-media rendering, numeric and supplied-word captions, audio, variants and batches.
2. Inspect a supplied media file: actual metadata, duration, video/audio presence, representative frames, contact sheet and measured scene-cut candidates. Produce machine-readable evidence usable by an agent.
3. Reconstruct an editable starting project from a local reference video. Copy the selected source into the new project, preserve its audio, split at measured cut candidates, and retain a report explaining what was measured. Do not claim to infer unavailable semantic content or generate replacements.
4. Transcribe local speech into word timestamps using an explicitly configured local whisper.cpp executable and model. Normalize real recognizer output, reject malformed output, support cancellation, and connect the result to anchored captions. Demonstrate real speech transcription when the external prerequisite is prepared.
5. Composite supplied image/video B-roll and picture-in-picture over the base timeline. Add constrained local clip effects (fades, image/video zoom, brightness/contrast/saturation), caption styles, and audio fades. Keep all filter syntax generated from validated typed data.
   Bind picture changes to speech as well as captions: a base clip may end at a word ID, and an overlay may use an inclusive word range. Preserve those references in editable JSON so changing word timing moves the corresponding cut or B-roll window.
6. Retain execution state and resume failed/cancelled renders and unfinished batches. Reuse verified clip intermediates across resumed jobs without overwriting existing outputs or trusting stale source media. Preserve successful batch cuts and report missing/corrupt completed artifacts explicitly.
7. Provide current CLI help, original agent instructions, no-account examples, package/install instructions, meaningful behavioral/integration tests, a reviewed release archive, and an end-to-end demonstration from supplied media through inspection, reconstruction, transcription, editing, variants and render.

The tool is a local production system, not a hosted multi-user service. FFmpeg/FFprobe and an optional local transcription engine are external executables. Runtime preparation must be explicit. The implementation uses Node standard libraries unless a concrete capability requires more.

## Media inspection module boundary

`src/media.mjs` exports:

- `inspectMedia(file, { workDir, sceneThreshold = 0.3, signal })` returns `{ source, sha256, duration, width, height, fps, hasVideo, hasAudio, scenes, frames, contactSheet }`. `scenes` is an ordered list of cut offsets in seconds (excluding 0 and duration); `frames` contains generated absolute PNG paths; `contactSheet` is a generated image path or null for audio-only input. All output files are inside a caller-owned fresh `workDir`. Reject media longer than 600 seconds, malformed scene thresholds, unsupported containers and absent/unknown durations. Use the same protocol/demuxer restrictions as the renderer. Bound frame/cut counts and diagnostics.
- `reconstructMedia(file, directory, { sceneThreshold = 0.3, signal })` requires a new directory; returns `{ project, report }` absolute paths. Copy the source into `assets/`, author an original version-1 project split at observed scene offsets with enough frames per clip, and store the inspection evidence in `inspection/`. Preserve clip audio and source offsets; choose a valid even canvas. All media stays local. Existing output directories are refused.

## Local transcription module boundary

`src/transcribe.mjs` exports `transcribeMedia(file, { workDir, language = 'en', signal })` returning `{ words, text, engine, language, audio, raw }` from actual recognition. `words` uses the existing `{id,text,start,end}` format; `audio` is its prepared 16-kHz mono WAV; `raw` names the saved recognizer JSON. Read `WHISPER_CPP_PATH` and `WHISPER_CPP_MODEL`; reject missing prerequisites with clear errors. Invoke whisper.cpp with word-level segmentation and full JSON output, based on official CLI documentation. Do not estimate a word timeline by evenly distributing a transcript. Exclude blank/special tokens; reject invalid timing instead of inventing it. Keep recognition results under `workDir` and never overwrite user files. Max source duration 600 seconds. Optionally export a pure parser for deterministic schema tests.

## Composition extension contract

`overlays` is optional (default `[]`, max 32). Each item has unique clip-style `id`, `kind` (`image`/`video`), project-relative `src`, `start >= 0`, positive `duration` fitting the timeline, `rect: {x,y,width,height}` in canvas pixels (integer, positive dimensions, fully inside the canvas), optional `in` for video (default 0), and `opacity` 0–1 (default 1). Overlay audio is intentionally not mixed; add it explicitly to `audio`. Images hold their first frame. Video is trimmed and scaled/cropped into its rectangle and only visible during its specified window. No raw filter expressions.

Clips accept optional `effects: {fadeIn, fadeOut, zoom, brightness, contrast, saturation}`. Defaults: fade durations 0, zoom 1, brightness 0, contrast/saturation 1. Fade durations are nonnegative and sum to at most the clip duration; zoom 1–2 gives a centered constant zoom; brightness -1–1, contrast 0–3, saturation 0–3. Unsupported or nonfinite values fail. Effects participate in segment reuse keys. Old projects without effects continue unchanged.

Audio tracks accept optional `fadeIn`/`fadeOut` (nonnegative, sum no greater than their duration); apply in their local trimmed interval before delay/mix. Caption style extensions remain optional and must preserve literal text safety. No new feature may weaken existing asset confinement, demuxer allowlists, command length protections, or no-overwrite behavior.

### Speech-linked picture timing

A clip uses either numeric `duration` or `untilWord: "word-id"`. The latter ends at that word's end timestamp; its start remains the previous clip's end. Resolve its duration against the current supplied/measured words every time, reject unknown/backward ends or durations shorter than one frame, and retain `untilWord` without materializing a stale numeric duration in normalized project JSON. Effects must fit the resolved duration. Word timestamps validate independently against the 600-second maximum first, then against the resolved final project duration. This avoids circular parsing without weakening timeline bounds.

An overlay uses either numeric `start/duration` or `fromWord/toWord` (inclusive). Derive its start from the first word and its duration through the last word's end; retain anchors in normalized JSON. Mixed numeric/word timing, unknown/reversed ranges and windows outside the final project are errors.

`src/project.mjs` exports `resolveClips(project)` and `resolveOverlays(project)` alongside `resolveCaptions`, returning numeric render inputs without mutating or freezing the source declarations. Rendering and CLI planning consume these resolved values. Old numeric projects keep their behavior.

## Resume boundary

`src/resume.mjs` exports `resumeJob(root, id, { output, signal, onProgress })` and `resumeBatch(directory, { signal, onProgress })`. Failed/cancelled jobs retain normalized project snapshots and original asset roots. Resume validates that snapshot and assets again, starts a new job linked by `resumedFrom`, and optionally reuses only verified intermediates. Default output is the original requested output if absent; any existing output is refused. Abruptly interrupted jobs may be resumed as a new foreground job, without killing or claiming ownership of any old process.

Persist segment cache metadata in the owned job directory (`segments.json`), recording key/digest and only relative generated segment filenames. Load it with strict schema, count, size, regular-file and canonical path checks. Never accept arbitrary absolute cache paths from disk. Content/settings/encoder identity remain part of keys.

New batches retain an immutable normalized base project snapshot and their patches. Resume validates the stored projects against the original asset root, verifies successful output digests, leaves successful outputs untouched, and starts only unfinished variants. Missing/corrupt successful outputs must produce a clear error instead of silently being treated as success or overwritten. Save new job IDs and preserve prior job lineage.

Root CLI integration owns parsing and user-facing commands; module implementers must not edit `src/cli.mjs` concurrently.
