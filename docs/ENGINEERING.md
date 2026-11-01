# Engineering notes

## Problem and boundary

An automated edit is useful only if the creator can inspect and revise it. Frameflow writes editable OpenShot projects (Shotcut on request) and a sidecar describing its last output: a first cut of a recording, shorts cut from a long one, or a video made from a prompt and the creator's own footage, images and music. Later changes remove and restore spans of the recording and add graphics and B-roll, without undoing what the creator changed by hand. It is not a general video editor: the creator finishes and exports in OpenShot.

## Decisions you can inspect

| Decision | Why | Tradeoff and evidence |
|---|---|---|
| Separate editorial decisions from timeline construction | An editor - Claude Code through the skills in [`.claude/skills/`](../.claude/skills/), or for first cuts and changes a model behind an API key - proposes a structured plan: what to keep, what each scene shows, what to change. Deterministic code validates it, places the clips and writes the project. | The plan can still be editorially wrong. Inspect [`editor_agent.py`](../project/editor_agent.py), [`change_agent.py`](../project/change_agent.py), [`validate.py`](../project/validate.py), [`plan_to_ir.py`](../project/plan_to_ir.py) and [`produce.py`](../project/produce.py). |
| Measure pauses in the audio | Transcript timing alone is too imprecise for word-safe cuts. | Real audio, Whisper and FFmpeg are needed to assess cut quality. See [`cutpoints.py`](../project/cutpoints.py) and [`verify_cuts.py`](../project/verify_cuts.py). |
| Preserve a sidecar and history | A later change must distinguish generated output from the creator's manual edits. | Unsupported edits may be refused rather than silently flattened. See [`reconcile.py`](../project/reconcile.py), [`operations.py`](../project/operations.py) and [`sidecar.py`](../project/sidecar.py). |
| Keep model providers behind a small interface | The same editing contract can be exercised with Anthropic or an OpenAI-compatible endpoint, when no coding agent is doing the editing. | Mocked-provider tests do not establish live endpoint reliability. See [`providers/`](../project/providers/) and [`test_first_cut.py`](../tests/test_first_cut.py). |
| One project model, OpenShot by default | The project model ([`ir.schema.json`](../project/schema/ir.schema.json)) is the source of truth, and each editor is a writer and reader pair. OpenShot is the default editor; Shotcut stays an option. | Vertical framing, B-roll and live changes are OpenShot-only for now. See [`editors.py`](../project/editors.py), [`compile_osp.py`](../project/compile_osp.py), [`parse_osp.py`](../project/parse_osp.py), [`compile_mlt.py`](../project/compile_mlt.py) and [`parse_mlt.py`](../project/parse_mlt.py). |
| Graphics are clips, not the final render | HyperFrames renders each title, caption and card with a transparent background, as a clip on its own track, so it stays editable; the creator exports the finished video from OpenShot. | Graphics need Node.js and a render each (cached). See [`hyperframes.py`](../project/hyperframes.py) and [`captions.py`](../project/captions.py). |
| Changes appear in the open editor | Frameflow's build of OpenShot runs a local control server, so a change lands in the window as the creator watches and one Ctrl+Z undoes it. | It needs Frameflow's patched build, checked on Windows only. See [`openshot_build.py`](../project/openshot_build.py), [`openshot_patch/`](../project/openshot_patch/) and [`openshot_live.py`](../project/openshot_live.py). |

## Reproduce the evidence

1. Follow the [synthetic demo](../README.md#try-the-core-logic-in-two-minutes) to inspect a ten-second edit plan becoming an eight-second timeline. No model or recording is involved.
2. Install `requirements.txt` and FFmpeg, then run `python -m unittest discover -s tests -v`. Linux and Windows CI exercise validation, provider loops, cut placement, manual-edit preservation and project building. Tests that need recordings, OpenShot's engine or the Piper voice skip when those are absent.
3. Follow the full workflow in the README for transcription, OpenShot's engine checks and join verification. This requires external software and media; the synthetic demo does not prove those stages. The measurements behind the design are in [findings](findings.md), and where Frameflow is going is in the [roadmap](roadmap.md).

## Current limits

The complete media workflow was developed and checked on Windows 11 only. CI establishes portable core behavior, not that OpenShot's engine, Whisper or Piper work on other systems. Changes cannot reorder clips yet; vertical framing, B-roll and live changes are OpenShot-only; stock footage and generated pictures or video are not built. API-provider behavior is covered with mocked clients, not a published live-provider benchmark. There is no measured claim of editing quality or production throughput.
