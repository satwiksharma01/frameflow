- [x] Project validation and asset-boundary tests pass.
- [x] Renderer passes real media, audio, and caption integration checks.
- [x] CLI can initialize, check, plan, render, inspect a job, and create a variant.
- [x] Original agent instructions and no-account example work.
- [x] Example and variant MP4s are rendered and inspected.
- [x] Independent product package boundary is reviewed.

Verification: `npm test` passed all 33 tests with no skips on Windows, Node 22.14.0 and FFmpeg/FFprobe 9.0.1. `npm audit --offline --omit=dev` reports no package vulnerabilities (there are no JavaScript dependencies). Review found and fixed progress-error handling, long-caption argument limits, and playlist path escapes; regression tests cover each.

Final `output/demo.mp4` and `output/variant.mp4` are each 720×1280, 30 fps, 180 frames, and 6 seconds. Representative frames were visually inspected. These graphic examples intentionally contain silent audio; audio preservation/mixing is verified with generated-tone integration fixtures. The packed archive contains 12 allowlisted files, no reference/research/job artifacts, and its extracted CLI successfully checked its included example.

The paragraph above records the first local-media milestone (v0.1). Cross-platform execution has not been tested beyond Windows. The optional skill is shipped in the product and has not been registered globally.

## Version 0.2

- [x] Supplied word timestamps validate and round-trip without freezing derived captions.
- [x] Anchored captions resolve current word text and timing; numeric captions remain supported.
- [x] `captions` imports word JSON into a validated sibling project.
- [x] `batch` preflights all patches/assets, preserves output directories, and records each job outcome.
- [x] Batch-local clip reuse checks source content, settings, encoder identity, and intermediate integrity.
- [x] Real renders verify changed caption composition, image content replacement, video audio/offset/volume, and corrupt/missing cache recovery.
- [x] Original agent instructions, examples, and public format describe both commands and their limits.

Verification: full `npm test` passes 56 tests with no skips. The three-cut, six-second timed batch succeeds with cache hits 0, 3, and 2 respectively; five of nine segments are reused, while final captions/audio are composed for each cut. Representative frames were visually inspected. The sample word timestamps are authored fixtures, not measured speech.

The preceding list records the historical v0.2 checkpoint. The user subsequently excluded generation and requested the complete supplied-media tool.

## Version 1.0.0 — complete supplied-media workflow

- [x] Actual metadata, cut candidates, representative frames/contact sheet and editable source reconstruction.
- [x] Actual local speech transcription and integration with anchored captions.
- [x] Supplied image/video overlays, opacity/geometry/timing, clip effects and audio fades.
- [x] Word-linked base cuts and B-roll windows retaining editable anchors through re-timing.
- [x] Durable segment metadata and explicit job/batch resume, output digests and lineage.
- [x] OS-owned batch execution exclusion and exclusive temporary state writes.
- [x] 101-test full suite, real speech workflow, and all 100 actual variant outputs verified.
- [x] Updated original agent instructions, public schema, setup/install guide and third-party inventory.
- [x] Final runtime archive independently installed and exercised; contents audited against the product boundary.
- [x] Requirement-by-requirement completion audit in COMPLETION.md.

Generation is excluded by user instruction. Remaining documented platform/recognition limits are explicit operating constraints, not unfinished required commands.
