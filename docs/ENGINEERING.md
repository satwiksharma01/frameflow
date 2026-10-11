# Engineering notes

## Problem and boundary

An automated first cut is useful only if the creator can inspect and revise it. Frameflow writes editable Shotcut timelines and a sidecar describing its last output. It currently supports keep/remove decisions and later remove/restore operations; it is not a general video editor.

## Decisions you can inspect

| Decision | Why | Tradeoff and evidence |
|---|---|---|
| Separate editorial decisions from timeline construction | A provider proposes a structured plan; deterministic code validates it and places clips. | Provider output can still be editorially wrong. Inspect [`editor_agent.py`](../project/editor_agent.py), [`validate.py`](../project/validate.py) and [`plan_to_ir.py`](../project/plan_to_ir.py). |
| Measure pauses in the audio | Transcript timing alone is too imprecise for word-safe cuts. | Real audio, Whisper and FFmpeg are needed to assess cut quality. See [`cutpoints.py`](../project/cutpoints.py) and [`verify_cuts.py`](../project/verify_cuts.py). |
| Preserve a sidecar and history | A later change must distinguish generated output from the creator's manual edits. | Unsupported edits may be refused rather than silently flattened. See [`reconcile.py`](../project/reconcile.py), [`operations.py`](../project/operations.py) and [`sidecar.py`](../project/sidecar.py). |
| Keep model providers behind a small interface | The same editing contract can be exercised with Anthropic or an OpenAI-compatible endpoint. | Mocked-provider tests do not establish live endpoint reliability. See [`providers/`](../project/providers/) and [`test_first_cut.py`](../tests/test_first_cut.py). |

## Reproduce the evidence

1. Follow the [synthetic demo](../README.md#try-the-core-logic-in-two-minutes) to inspect a ten-second edit plan becoming an eight-second timeline. No model or recording is involved.
2. Install `requirements.txt`, then run `python -m unittest discover -s tests -v`. Linux and Windows CI exercise validation, provider loops, cut placement and manual-edit preservation. Media-dependent tests explicitly skip when their recordings are absent.
3. Follow the full recording workflow in the README for transcription, real engine checks and join verification. This requires external software and media; the synthetic demo does not prove those stages.

## Current limits

The complete media workflow was developed on Windows. CI establishes portable core behavior, not full cross-platform Shotcut support. Reordering, b-roll, captions and graphics are unfinished. API-provider behavior is covered with mocked clients, not a published live-provider benchmark. There is no measured claim of editing quality or production throughput.
