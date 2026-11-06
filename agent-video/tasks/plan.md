# First runnable milestone

The user approved the capability map and explicitly requested implementation on 2026-10-31. Proceed through the scoped local-media milestone without further planning approval. The public project contract is `FORMAT.md`.

1. Validate and normalize independently designed project JSON, including real local asset boundaries. Write failing behavioral tests before implementation.
2. Render sequential colors, images, and video; preserve clip audio; mix added audio; overlay literal timed captions. Prove behavior with FFprobe and short integration renders.
3. Connect original CLI commands to project validation, render planning, isolated job records, safe output publication, and editable variants. Add original agent instructions and a no-account example.
4. Run the full tests, render the example and a caption variant, visually inspect frames, and inspect the release file list for reference dependencies or research artifacts.

Project validation and renderer implementation can proceed independently against the written boundary. CLI integration depends on both. Product code uses Node standard libraries; FFmpeg/FFprobe are external prerequisites, not bundled dependencies. No hosted generation connectors are in this milestone.

Input JSON and local media are untrusted. Limit schema sizes and timing, confine input paths to the project, invoke subprocesses with argument arrays and no shell, treat caption text literally, and never overwrite existing output or source media.

## Next slice: supplied word timing and batch variants

User requested continued implementation. Extend the version-1 contract compatibly as recorded in `FORMAT.md`:

1. Add supplied word validation, durable caption anchors, caption resolution, and a grouping helper. Verify re-timing/re-wording, mixed timing refusal, and normalized round trips.
2. Add batch-local clip reuse keyed by actual inputs. Verify unchanged clips hit, changed source/settings miss, corrupt/missing intermediates re-encode, and final captions still differ.
3. Add batch preflight, sequential jobs, no-overwrite output directory, per-variant failure/cancellation status, and CLI commands for captions and batch execution. Verify with real renders and failure-path tests.
4. Review input boundaries and packaging; render timed-caption and batch examples and update original agent instructions.

No model account, new JavaScript dependency, network generation call, or reference implementation is needed. Actual transcription and hosted generation remain outside this slice.
