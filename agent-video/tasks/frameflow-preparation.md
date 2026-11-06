# Frameflow preparation — 2026-11-01

The user authorized the preparation work after reviewing the integration assessment. All changes stay in Agent Video. Frameflow remains a read-only contract reference; its main integration will happen later. No Hypit implementation, schema, templates or instructions may enter this product. No generation is added.

The required capability is a reference-to-storyboard workflow, not a replacement editor or renderer. Frameflow's current roadmap specifies reference pacing, shot lengths, caption style and hook analysis; 2–3 adapted concepts; a short sample; and a storyboard for its existing editable-project build.

Build order: storyboard contract → reference evidence/session → agent analysis/concepts → export/sample → CLI/public API/docs/package verification.

| Boundary | Responsibility | Verification |
| --- | --- | --- |
| `src/frameflow.mjs` | Independently implemented validation of the existing brief, supplied-input and storyboard interfaces; source-clock windows, media inventory, measured-pause safety and explicit generation refusal | Accepted and rejected real contract fixtures, file/duration checks, fractional-source rates without coercing source seconds |
| `src/reference.mjs` | Original reference evidence, pacing statistics, analysis/concept validation, session preparation, handoff and sample documents | Actual cut inspection; observations carry evidence or uncertainty; 2–3 independently authored concept storyboards; no overwrite or reference-as-replacement shortcut |
| CLI/public API | Structured JSON commands usable by a future Python caller; stable versioned handoff with file hashes and explicit delegated requirements | Real CLI preparation/check/export/sample; imported API; errors and cancellations remain machine-readable |
| Handoff | A validated storyboard, brief, supplied-media inventory, reference evidence, source-to-output mapping and review requirements | Validate exported JSON against Frameflow's actual current schemas using read-only access; no Frameflow runtime code dependency or code modification |

Commands planned: `reference-prepare <reference> --inputs <inputs.json> --brief <brief.json> --out-dir <new-session> [--timings <source-timings.json>]`; `reference-check <session>`; `frameflow-export <session> --concept <id> --out-dir <new-handoff>`; `reference-sample <session> --concept <id> --seconds <maximum> --out-dir <new-sample>`; `frameflow-check <storyboard.json> --inputs <inputs.json> --brief <brief.json> [--timings <source-timings.json>]`. All support `--json`.

Source timings are supplied measured pauses on each recording's source clock, not Agent Video's rendered timeline. Interior footage boundaries must remain safe after frame rounding; source endpoints are permitted. Samples retain whole scenes and refuse a first scene longer than the requested sample rather than introducing an unsafe cut. Generation-bearing narration/voice fields are rejected. Captions, native project export, custom HTML graphics, source normalization and human-edit reconciliation remain explicit Frameflow responsibilities. Unsupported intentions stay in review notes and must not be silently flattened or discarded. The JSON-only handoff supports up to 24-hour sources/storyboards (at most 100 scenes); it must not inherit the separate local renderer's ten-minute limit. File checks on a storyboard require its explicit brief/frame grid.

Agent analysis is authored by the host coding agent, with observations grounded in reference intervals. The tool does not infer unmeasured caption styles or hooks, fabricate concepts, claim automatic semantic recognition, or install an embedded model. A versioned request artifact gives the agent exact contracts and instructs it to inspect evidence, propose adapted concepts and retain uncertainties.

The baseline is the existing 101-test supplied-media tool. Use Node's test runner, add focused behavior tests before new logic, run the full suite, inspect the actual archive and exercise an installed archive. Real media tests can use deliberately simple fixtures but must be labeled as such; they are not artistic-parity benchmarks. Do not change old behavior or weaken existing checks. Frameflow source, schemas, docs, media and model files never belong in the package.

No integration code is written into Frameflow, and no user-specific source media or credentials are bundled. Licensing choices are left to the owner; this change does not claim legal clearance or full Hypit feature equivalence.

## Completion evidence

- [x] Reference evidence/session, strict agent analysis, 2–3 concept storyboards, safe sample and versioned export commands implemented.
- [x] Current Frameflow supplied-media/B-roll/cards/beat declarations preserved with explicit delegated timing requirements; voice/narration generation refused.
- [x] Source-time safety, file/provenance checks, self-contained timing documents and evidence hashes tested; cross-review findings fixed.
- [x] All 140 tests pass with zero skips under native Windows permissions.
- [x] The 28-file v1.1.0 archive installs independently, exposes its public API and passes actual Frameflow schema validation using its installed smoke workflow.
- [x] Changes stay within Agent Video. Frameflow's independent development continued during this task; it was accessed read-only and its tested schema hashes were recorded.

The future Frameflow developer still connects the prepared handoff to approval, timing preparation, native rendering/export and later human-edit-preserving changes. No native editor integration was claimed or attempted.
