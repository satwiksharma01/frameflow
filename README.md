# Frameflow

[![CI](https://github.com/satwiksharma01/frameflow/actions/workflows/ci.yml/badge.svg)](https://github.com/satwiksharma01/frameflow/actions/workflows/ci.yml)

An AI editor that makes the first cut of a raw recording **as a fully editable OpenShot project** — never a flattened render. Open the result in [OpenShot](https://github.com/OpenShot/openshot-qt) and every cut is a real clip you can move, trim or undo. Then ask for changes in plain words, and they land on top of whatever you changed by hand.

```
raw recording  →  first cut (a real .osp project)  →  you edit in OpenShot  →  "tighten the intro"  →  change applied, your edits intact
```

Prefer [Shotcut](https://shotcut.org)? Add `--editor shotcut` to a first cut and you get a Shotcut `.mlt` project instead; changes work on either.

> **Status: early and experimental.** Cutting talking-head and screen recordings works end to end on real footage. Stock footage and generated pictures or video are not built. Developed and tested on Windows 11 only.

## Try the core logic in two minutes

This synthetic example needs Python and `jsonschema` only. It does not download a Whisper model, read a recording, call an API, or need OpenShot:

```bash
git clone https://github.com/satwiksharma01/frameflow.git
cd frameflow
python -m pip install "jsonschema>=4.26.0"
python -m examples.demo_timeline
```

It removes an illustrative two-second pause from a ten-second source and writes the validated edit plan and timeline to `output/demo/`. The second kept clip starts at 4.8 seconds in the source and 2.8 seconds in the output. The source path is a placeholder: this demonstrates timeline construction, not speech recognition, cut quality or a playable export. CI runs this command on Linux and Windows.

[Engineering decisions and evidence](docs/ENGINEERING.md) · [Contributing](CONTRIBUTING.md)

## What it does

**First cut.** Given a raw recording, Frameflow transcribes it, measures its silences, and has an editor — Claude Code, or any model you have an API key for — decide what to keep: dead air, false starts, abandoned takes, instructions to yourself. The result is an OpenShot project with each kept span as its own clip, and a written reason for every decision. Ask for captions and what you say pops in word by word, each line a clip on its own Captions track. Ask for a vertical cut and a landscape recording fills a 9:16 frame, framed on your face and moving smoothly when you move; the crop is a clip setting you can change in OpenShot, and your change is kept through later edits. Your voice is turned up toward the -14 LUFS that YouTube, Instagram and TikTok play at, as the clip's volume, stopping before it would clip.

**Shorts from a long recording.** The editor picks the moments that stand on their own — each opening on a hook, starting and ending on a whole sentence — and each becomes its own vertical OpenShot project, framed on your face, with captions, built and checked like a first cut.

**A video from a prompt.** Describe the video you want — a reel, a YouTube video, a pitch, a product ad — and hand over whatever you have: a script, recordings, images, clips, music. It doesn't need your face on camera. The editor writes a brief for you to confirm, then a storyboard (the script, and what is seen, said and shown on screen in each scene) for you to confirm, then builds it: your footage and images on the main track, cutaways to your other images and clips while you talk, titles, captions, product cards and lower thirds rendered by HyperFrames (for a reel, what is said pops in word by word; a product card comes up as the product is named), a voiceover read on your computer by Piper's natural voice (trained on public-domain recordings, so you can post it), and your music under it, each on its own track. Cut to the music, every cut lands on its beat, except where that would clip a word you say. In Claude Code, just ask for the video; the `produce` skill runs the steps (`python -m project.produce`).

**Changes.** Ask for a change to a project you already have, including one you've edited by hand in OpenShot. Frameflow works out what you changed since it last wrote the project, and won't undo your edits unless you ask it to. Ask for B-roll and your own images and clips cut away from the recording where what you say matches them, on their own B-roll track, filling the frame with their sound turned down while your voice carries on. Captions, graphics and B-roll move with the cut. The previous version is always kept.

**What it will not do quietly:**
- **Cut mid-word without saying so.** Every cut point is moved into a measured pause. If the only pause is too short for a clean cut at your frame rate, a first cut warns you at build time, and a change refuses it so the editor picks a better boundary.
- **Ship a cut without listening to it.** After building, the project's audio is rendered and every join is transcribed again, to check the words either side survived. An OpenShot project is rendered by OpenShot's own engine, run without a window (FFmpeg stands in when OpenShot is not installed); a Shotcut project is rendered by Shotcut's own engine.
- **Add graphics that stay editable.** Ask for a title, caption, lower third or product card and it is rendered by HyperFrames with a transparent background onto its own Graphics track, anchored to the moment it's said. A product card shows the product's name, a line under it and its price as a tag; a lower third shows a name with a role under it. Both sit at the left just above the captions, in your brand kit. In your editor it's an ordinary clip you can move, trim or delete.
- **Change what's on screen.** When the project is open in Frameflow's build of OpenShot, a change appears in the window as you watch, and one Ctrl+Z there undoes it. Unsaved work in that window is saved before Frameflow reads the project. See [docs/findings.md](docs/findings.md) for how the integration works.
- **Throw away your work.** If a change would lose something Frameflow can't carry — an effect, a fade, a speed change, a title — it stops and names it instead of discarding it.

## Requirements

| | |
|---|---|
| **Python** | 3.10 or newer (tested on 3.13) |
| **OpenShot** | 4.0.x, in `C:\Program Files\OpenShot Video Editor` or `%LOCALAPPDATA%\Programs\OpenShot Video Editor`. Frameflow reads its profile list to name the project's size and frame rate the way OpenShot will recognise them |
| **FFmpeg** | `ffmpeg` and `ffprobe`, on `PATH` or in `%LOCALAPPDATA%\Programs\ffmpeg\bin` |
| **Transcription** | `python -m project.transcribe --install` fetches [OpenWhispr](https://github.com/OpenWhispr/openwhispr)'s build of whisper.cpp (1.2 MB, MIT, checksum-verified) into `tools/`, and the `ggml-large-v3-turbo-q5_0.bin` model (548 MB) into `models/` if there is none. Any `whisper-cli` already on `PATH`, or Shotcut's, is used instead; so is a model OpenWhispr has already downloaded |
| **Voice** | `python -m project.voiceover --install` fetches [Piper](https://github.com/OHF-Voice/piper1-gpl)'s `en_US-ljspeech-high` voice (114 MB, checksum-verified) into `models/piper/`. Its training recordings are public domain; many other Piper voices are non-commercial, so check a voice's model card before adding it there. Without it, narration uses a Windows voice |
| **Node.js** | 22 or newer, for graphics: Frameflow runs [HyperFrames](https://github.com/heygen-com/hyperframes) 0.8.199 through `npx` to render titles, captions and cards |
| **Shotcut** (optional) | 26.x, only for `--editor shotcut`. Its `melt` engine checks and renders Shotcut projects |

```bash
pip install -r requirements.txt
```

```bash
python -m project.transcribe --install
```

```bash
python -m project.voiceover --install
```

`FRAMEFLOW_WHISPER_CLI` and `FRAMEFLOW_WHISPER_MODEL` override where the transcriber and model are looked for.

**Talk instead of typing.** Install the [OpenWhispr](https://github.com/OpenWhispr/openwhispr/releases/latest) app, press its hotkey in Claude Code and say what you want - "make a 15 second reel for the new jacket", "tighten the intro". It transcribes on your computer, so your words don't leave it.

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

Add `--editor shotcut` to both commands for a Shotcut project instead, `--captions` for captions that pop in word by word as you speak, and `--vertical` for a 9:16 video (OpenShot only, for now).

### Shorts from one long recording

Ask Claude Code for shorts, Reels or TikToks from a recording and the `shorts` skill runs it. By hand:

```bash
python -m project.shorts "path/to/recording.mp4" --prepare --count 3
```

Your agent follows `shorts_request.md` and writes `shorts_plan.json`: for each short, where it starts and ends, its hook, and anything to remove inside it. Then:

```bash
python -m project.shorts "path/to/recording.mp4" --build
```

Each short is built in its own folder, `short-1/`, `short-2/`, ..., as a vertical first cut with captions.

### Your brand

Titles, cards and captions use your brand kit, `brand/brand.json` in this folder (it is yours, so git ignores it). Every field is optional; paths are relative to the file:

```json
{"font": "Brand-Bold.ttf", "text": "#1B1B1B", "accent": "#E4572E", "background": "#F4E9DA",
 "logo": "logo.svg", "uppercase_captions": false}
```

`font` is a font file or the name of an installed font; `accent` colours the word being said; `background` colours title screens and the plate behind cards; the logo sits above the text of title screens. Change it and the next build is restyled. Projects already built keep their look.

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

**Close the project in your editor first**, and reopen it afterwards. Saving from a window still showing the old version would write over the change.

With Claude Code, ask for the change and the `edit` skill takes it from there. By hand:

```bash
python -m project.edit "output/recording/recording.osp" --prepare "the pauses in the first minute drag"
```

Your agent follows `change_request.md` and writes `operations.json`, then:

```bash
python -m project.edit "output/recording/recording.osp" --apply --open
```

Or in one step with an API key: `python -m project.edit "<project.osp>" "<what to change>"`. A Shotcut `.mlt` project works the same way.

Changes remove and restore spans of the recording, and add graphics and B-roll at moments of it. Reordering clips is not supported yet.

## What gets written

Everything for a recording goes in `output/<recording name>/`:

| File | |
|---|---|
| `<name>.osp` | The OpenShot project (`<name>.mlt` with `--editor shotcut`) |
| `<name>.frameflow.json` | Frameflow's record of what it last wrote. **Keep it beside the project** — it's how a later change tells your hand edits apart from its own |
| `transcript.json`, `timing.json` | What was said, and the measured pauses |
| `edit_plan.json` | Every first-cut decision, with its reason |
| `shorts_plan.json`, `short-1/`, ... | The moments picked for shorts, and each short's project |
| `history/` | Every previous version of the project, kept before each change |

A recording with a variable frame rate — what most screen recorders and phone cameras produce — is first converted to a constant rate in the same folder, because cut points drift on variable-rate video.

## How it works

The editor decides *what* to cut. Everything else is deterministic code the model never touches: placing cuts in the audio, building the timeline, writing the project, and listening to the result.

Two rules come from things that went wrong on real recordings:

- **The transcript says what was said; only measured audio says where.** Whisper's timestamps are estimates — at the word level it spreads words evenly through a silence, and one word was timed four seconds before it was spoken. So every cut point comes from silences measured in the audio, never from the transcript.
- **Human edits win.** A change is applied to the project as you have it now. An operation that would reverse something you did in your editor is rejected unless your instruction explicitly asks for it.

## Layout

| | |
|---|---|
| `project/first_cut.py`, `project/shorts.py`, `project/edit.py`, `project/produce.py` | The commands: cut a recording, cut shorts from it, change a project, make a video from a prompt |
| `project/hyperframes.py`, `project/captions.py`, `project/voiceover.py` | Titles and cards rendered by HyperFrames; word-by-word captions; the voiceover |
| `project/reframe.py`, `project/broll.py`, `project/beats.py` | Framing on your face for vertical; cutaways to your own images and clips; the music's beat |
| `project/editor_agent.py`, `project/change_agent.py` | What the editor is shown, and asked to do |
| `project/cutpoints.py`, `project/verify_cuts.py` | Placing cuts in pauses, and listening to them afterwards |
| `project/reconcile.py`, `project/operations.py` | Working out your hand edits; applying changes without undoing them |
| `project/editors.py` | Which editor a project belongs to, and what differs between them |
| `project/compile_osp.py`, `project/parse_osp.py`, `project/openshot_template.py` | Writing and reading OpenShot projects |
| `project/openshot_build.py`, `project/openshot_patch/`, `project/openshot_live.py`, `project/openshot_render.py` | Frameflow's build of OpenShot: its patch, the client that drives its window, and the engine render |
| `project/compile_mlt.py`, `project/parse_mlt.py` | Writing and reading Shotcut projects |
| `project/schema/` | JSON Schemas for the project model, edit plans, operations, briefs and storyboards |
| `project/providers/` | Anthropic and OpenAI-compatible model providers |
| `examples/` | Real projects saved by OpenShot and Shotcut, used as test fixtures, and `demo_timeline.py`, the synthetic demo |

## Tests

```bash
python -m unittest discover tests
```

CI runs the tests on Linux and Windows with Python 3.13 and FFmpeg. Tests that need recordings, which are not committed, skip themselves when the media is missing; so do tests that write OpenShot projects when OpenShot is not installed. These checks do not validate a full OpenShot/Whisper workflow or a live model-provider endpoint.

## License

Frameflow is free software under the [GNU General Public License v3.0](LICENSE) — the same license as OpenShot and Shotcut. You may use, study, change and share it; if you distribute a modified version, you must make its source available under the same license.
