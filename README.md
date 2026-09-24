# Frameflow

An AI editor that makes the first cut of a raw recording **as a fully editable Shotcut project** — never a flattened render. Open the result in [Shotcut](https://shotcut.org) and every cut is a real clip you can move, trim or undo. Then ask for changes in plain words, and they land on top of whatever you changed by hand.

```
raw recording  →  first cut (a real .mlt project)  →  you edit in Shotcut  →  "tighten the intro"  →  change applied, your edits intact
```

> **Status: early and experimental.** Cutting talking-head and screen recordings works end to end on real footage. B-roll, captions, graphics and short-form reframing are not built. Developed and tested on Windows 11 only.

## What it does

**First cut.** Given a raw recording, Frameflow transcribes it, measures its silences, and has an editor — Claude Code, or any model you have an API key for — decide what to keep: dead air, false starts, abandoned takes, instructions to yourself. The result is a Shotcut project with each kept span as its own clip, and a written reason for every decision.

**Changes.** Ask for a change to a project you already have, including one you've edited by hand in Shotcut. Frameflow works out what you changed since it last wrote the project, and won't undo your edits unless you ask it to. The previous version is always kept.

**What it will not do quietly:**
- **Cut mid-word without saying so.** Every cut point is moved into a measured pause. If the only pause is too short for a clean cut at your frame rate, a first cut warns you at build time, and a change refuses it so the editor picks a better boundary.
- **Ship a cut without listening to it.** After building, the project's audio is rendered and every join is transcribed again, to check the words either side survived.
- **Throw away your work.** If a change would lose something Frameflow can't carry — a filter, a fade, a title — it stops and names it instead of discarding it.

## Requirements

| | |
|---|---|
| **Python** | 3.10 or newer (tested on 3.13) |
| **Shotcut** | 26.x. Frameflow uses the `melt` engine and the `whisper-cli` transcriber that ship with it, found on `PATH`, in `C:\Program Files\Shotcut`, or in `%LOCALAPPDATA%\Programs\Shotcut` |
| **FFmpeg** | `ffmpeg` and `ffprobe`, on `PATH` or in `%LOCALAPPDATA%\Programs\ffmpeg\bin` |
| **Whisper model** | `ggml-large-v3-turbo-q5_0.bin` (548 MB) from the [whisper.cpp model repository](https://huggingface.co/ggerganov/whisper.cpp), saved into `models/` |

```bash
pip install -r requirements.txt
```

`FRAMEFLOW_WHISPER_CLI` and `FRAMEFLOW_WHISPER_MODEL` override where the transcriber and model are looked for.

## Making a first cut

### With Claude Code (no API key)

Open this repository in Claude Code and ask it to make a first cut of your recording. The `first-cut` skill in `.claude/skills/` runs the whole workflow, with Claude Code making the editorial decisions. The same workflow by hand, with any coding agent:

```bash
python -m project.first_cut "path/to/recording.mp4" --prepare --brief "tight, keep the demo"
```

Your agent then follows `output/<recording>/edit_request.md` and writes `edit_plan.json` beside it. Building checks the plan and reports every problem until it is right:

```bash
python -m project.first_cut "path/to/recording.mp4" --build --open
```

### With an API key

```bash
python -m project.first_cut "path/to/recording.mp4" --open
```

The default provider is Anthropic (`ANTHROPIC_API_KEY`). Any OpenAI-compatible endpoint works too — OpenAI, OpenRouter, Ollama, LM Studio, vLLM:

```bash
FRAMEFLOW_PROVIDER=openai FRAMEFLOW_MODEL=<model> FRAMEFLOW_BASE_URL=<endpoint> OPENAI_API_KEY=<key> python -m project.first_cut "recording.mp4"
```

If you run Frameflow from a terminal that Claude Code opened, set `ANTHROPIC_API_KEY` explicitly: without it the Anthropic SDK falls back to `ANTHROPIC_AUTH_TOKEN`, which that terminal sets to Claude Code's own session. API mode is implemented and tested against mocked providers, but has not yet been run against a live endpoint — agent mode has.

## Changing a project you already have

**Close the project in Shotcut first**, and reopen it afterwards. Shotcut does not reload a file that changed on disk, so saving from a window still showing the old version would write over the change.

With Claude Code, ask for the change and the `edit` skill takes it from there. By hand:

```bash
python -m project.edit "output/recording/recording.mlt" --prepare "the pauses in the first minute drag"
```

Your agent follows `change_request.md` and writes `operations.json`, then:

```bash
python -m project.edit "output/recording/recording.mlt" --apply --open
```

Or in one step with an API key: `python -m project.edit "<project.mlt>" "<what to change>"`.

Changes are `remove` and `restore` on spans of the recording. Reordering clips, and editing anything but the main video track, are not supported yet.

## What gets written

Everything for a recording goes in `output/<recording name>/`:

| File | |
|---|---|
| `<name>.mlt` | The Shotcut project |
| `<name>.frameflow.json` | Frameflow's record of what it last wrote. **Keep it beside the project** — it's how a later change tells your hand edits apart from its own |
| `transcript.json`, `timing.json` | What was said, and the measured pauses |
| `edit_plan.json` | Every first-cut decision, with its reason |
| `history/` | Every previous version of the project, kept before each change |

A recording with a variable frame rate — what most screen recorders and phone cameras produce — is first converted to a constant rate in the same folder, because cut points drift on variable-rate video.

## How it works

The editor decides *what* to cut. Everything else is deterministic code the model never touches: placing cuts in the audio, building the timeline, writing the project, and checking the result in the real MLT engine.

Two rules come from things that went wrong on real recordings:

- **The transcript says what was said; only measured audio says where.** Whisper's timestamps are estimates — at the word level it spreads words evenly through a silence, and one word was timed four seconds before it was spoken. So every cut point comes from silences measured in the audio, never from the transcript.
- **Human edits win.** A change is applied to the project as you have it now. An operation that would reverse something you did in Shotcut is rejected unless your instruction explicitly asks for it.

## Layout

| | |
|---|---|
| `project/first_cut.py`, `project/edit.py` | The two commands |
| `project/editor_agent.py`, `project/change_agent.py` | What the editor is shown, and asked to do |
| `project/cutpoints.py`, `project/verify_cuts.py` | Placing cuts in pauses, and listening to them afterwards |
| `project/reconcile.py`, `project/operations.py` | Working out your hand edits; applying changes without undoing them |
| `project/compile_mlt.py`, `project/parse_mlt.py` | Writing and reading Shotcut projects |
| `project/schema/` | JSON Schemas for the project model, edit plans and operations |
| `project/providers/` | Anthropic and OpenAI-compatible model providers |
| `examples/` | Real projects saved by Shotcut, used as test fixtures |

## Tests

```bash
python -m unittest discover tests
```

Tests that need recordings, which are not committed, skip themselves when the media is missing.

## License

Frameflow is free software under the [GNU General Public License v3.0](LICENSE) — the same license as Shotcut. You may use, study, change and share it; if you distribute a modified version, you must make its source available under the same license.
