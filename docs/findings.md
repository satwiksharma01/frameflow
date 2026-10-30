# Findings: how Frameflow integrates with video editors

What we decided, why, and what we checked. The code is the source of truth for
details; this records the reasoning behind it.

## The idea

Frameflow never owns the timeline. The creator's editor does. Frameflow writes a
real, editable project, the creator changes it by hand, and Frameflow's next
change lands on top of their work instead of replacing it.

Three layers make that work:

1. **The IR** (`project/schema/ir.schema.json`) is the editor-neutral source of
   truth: tracks, clips, source spans, and now opacity, volume and fades. Every
   decision (first cut, remove, restore) is made on the IR.
2. **One adapter per editor**, registered in `project/editors.py`. An adapter
   writes the IR as the editor's project file, reads the file back, names
   anything an edit would lose, and renders the audio to check cuts by ear.
   Adding an editor means adding one entry; nothing else changes.
3. **The sidecar** (`<name>.frameflow.json`) holds what the editor's file
   cannot (provenance, track types) and the last version Frameflow wrote, so
   `reconcile` can tell the creator's hand edits apart from Frameflow's.

Hand edits win. An edit is checked against what the creator changed, and
anything the IR cannot carry stops the edit with a list of what would be lost,
instead of dropping it silently.

## Editors

| Editor | Status | Why |
|---|---|---|
| OpenShot 4.0.1 | Default | Simplest interface of the open-source editors, active, GPLv3 like Frameflow, plain JSON project file, Python app code we can patch |
| Shotcut | Optional (`--editor shotcut`) | MLT project; melt renders and checks it headlessly |
| OpenCut | Not yet | The working version (opencut-classic) was archived on 2026-05-17 and needs Docker, Postgres and Redis. The rewrite (MIT, planned MCP server and headless mode) is unreleased. Revisit when it ships |
| DaVinci Resolve | Not yet | 21.1 removed scripting from the free edition, so an MCP connector needs Studio. Resolve imports and exports OTIO, so a file-based OTIO adapter would reach the free edition |

## OpenShot: what the file format taught us

All of this was checked against a project OpenShot itself saved
(`examples/openshot-saved.osp`):

- A layer's `number` is N × 1,000,000; a higher layer draws on top. Clip
  `position`, `start` and `end` are in seconds. Media paths are relative to the
  project file.
- OpenShot 4.0.1 looks a project's profile up by its description, among its own
  profile files. An unknown description silently opens as "HD 720p 30 fps", so
  Frameflow names a profile that exists, or refuses.
- Re-saving in OpenShot only adds thumbnails and a project id, so a round trip
  through OpenShot keeps Frameflow's clips intact.
- OpenShot crashes on start when it inherits Git Bash's `MSYSTEM`, so every
  launch strips it.
- **Fades are keyframes**, not effects. The Fade and Volume menus put Bezier
  points on the clip's `alpha` and `volume` curves, counted in *source* frames
  from 1 (`round(start × fps) + 1`). Frameflow reads exactly the shapes those
  menus write (a steady level, an optional rise at the first frame, an optional
  fall at the last) into `opacity`, `volume_db`, `fade_in` and `fade_out`, and
  writes them back the same way (copied from `Fade_Triggered` and
  `Volume_Triggered` in openshot-qt's `timeline.py`). A hand-drawn curve, a
  fade left off the clip's edge by a trim, or a muted clip still stops the
  edit.
- When an edit cuts inside a faded clip, the fade stays on the clip's outer
  edge: the first piece keeps the fade-in, the last keeps the fade-out. When
  restoring material joins two clips, the joined clip keeps the first one's
  fade-in and the second one's fade-out.

## Changing OpenShot itself

OpenShot is GPLv3, so we may change it. That is not "anything goes": if we
distribute a changed OpenShot, its full source goes with it under GPLv3, the
copyright notices stay, and it cannot be called "OpenShot" (a trademark).
Frameflow is GPLv3 too, so the two fit. If Produk is closed source, it should
run Frameflow's OpenShot as a separate program and talk to it over files or a
local connection, never merge its code. Get a legal check before shipping.

We chose **a small patch, not a rewrite**. OpenShot is a large Python/Qt app on
a C++ engine, and a deep fork would mean merging every upstream release by hand.

### How the patch is applied: Frameflow's build of OpenShot

OpenShot ships its application code as plain Python files beside its
executable. `python -m project.openshot_build` makes a build of its own in
`%LOCALAPPDATA%\Frameflow\OpenShot-4.0.1`:

- the executable, its DLLs and the `classes` package are copied (about 117 MB);
- every other folder is a directory junction into the install (no admin rights
  needed; hard links into Program Files were refused);
- the copied `classes` gets `project/openshot_patch/`, and `classes/app.py` gets
  one hook line after the main window appears.

The installed OpenShot is never modified and still runs as before. The build
checks that `app.py` is the version the patch was written for, and refuses
otherwise. Rebuild after updating OpenShot.

When Claude Code runs Frameflow from the Windows desktop app, `%LOCALAPPDATA%`
is redirected into the app's own storage, so the build lands there. Frameflow
builds again wherever it does not find one.

### What the patch adds

**1. A headless engine runner.** The launcher imports `classes` before it opens
any window, with libopenshot already loaded. With `FRAMEFLOW_RUN` set to a
Python file, the patched `classes/__init__.py` runs that file and exits. That
gives Frameflow OpenShot's own engine (libopenshot 1.0.1, on OpenShot's Python
3.8) with no window. `project/openshot_render.py` uses it to render a project's
main-track audio, so cuts are checked by ear exactly as OpenShot plays them,
fades included. FFmpeg's approximation remains only for machines without
OpenShot. Only the main track is rendered, because B-roll sound over a join
would mask the words being checked.

**2. A live control server.** Once the window is up, `frameflow_bridge.py`
listens on localhost on a port the system picks, and writes the port and a
fresh random token to `~/.openshot_qt/frameflow_bridge.json`. It takes one JSON
request per line, each carrying the token:

| Request | Effect |
|---|---|
| `status` | The open project's path, and whether it has unsaved changes |
| `save` | Saves the open project to its own file |
| `load` | (Frameflow's edits send it only after `status` shows that project is open.) For the open project: applies the new version as a difference (clips, files, layers) in one transaction, so it appears in place and one Ctrl+Z undoes it. For any other project: opens it as File > Open would |

The bridge applies edits through OpenShot's own update manager (`insert`,
`update`, `delete` with a transaction id), the same path the timeline's own
menus use. It runs on Qt's main thread.

On Frameflow's side (`project/openshot_live.py`, wired through `editors.py`):

- before reading a project for an edit, Frameflow saves the creator's unsaved
  work in the open window, so it edits what they see;
- after writing the new version, Frameflow pushes it to the window;
- `--open` shows the project in an already-open window, or launches
  Frameflow's build of OpenShot (so the server is running).

With no window open, every live call does nothing and Frameflow works through
files alone, as before.

## What has been checked

- Round trips of fades, opacity and volume between the IR and `.osp`, and the
  exact points the Fade In menu writes (tests).
- The build: a probe ran inside it on libopenshot 1.0.1 / Python 3.8; the
  installed OpenShot was left untouched (tests).
- The engine render of the saved fixture: 12 s, with silence in the main
  track's gap (tests).
- The bridge, live, by eye in the window: a clip Frameflow moved from 5–8 s to
  20–30 s appeared there as soon as it was pushed, and one Ctrl+Z put it back.
- An edit only updates the window when that same project is open in it. An
  early version opened whatever project an edit wrote, which switched a
  creator's window to a test project; `update` now checks first (tested).
- The bridge's diff logic: one transaction, clips removed before anything they
  depend on (tests with OpenShot's modules stubbed out).

## Not yet checked

- A fade written by Frameflow, played back in OpenShot.
- Shotcut paths (melt is not installed here).

## HyperFrames: graphics as editable clips

HyperFrames (heygen-com/hyperframes, run as `npx hyperframes@0.8.199`) renders
HTML into video. Frameflow uses it for titles, captions, lower thirds and
product cards, never for the whole video, so the project stays editable.

- An edit's `graphics` list adds them: each has text (or a HyperFrames project
  folder, `composition`, for anything else), a moment in the recording and a
  duration. The moment is mapped through the cut, so the graphic appears when
  that is said; a moment that was cut out, or a graphic that would overlap
  another, is sent back to fix.
- `project/hyperframes.py` renders each to a transparent ProRes 4444 `.mov`
  (`--format mov`, yuva444p12le) in the project's `graphics/` folder, cached
  by content, before the project is written. The clip then sits on a Graphics
  track above the footage like any other media.
- The built-in text card animates without GSAP. HyperFrames seeks whatever
  object is in `window.__timelines`, and GSAP's own license is not one Frameflow
  can ship under, so the card drives its fade and rise with a small timeline
  object of its own.
- HyperFrames refuses a frame rate written as `30.0`; Frameflow passes `30` or
  an exact fraction like `30000/1001`.
- Checked by eye in OpenShot: a card added to an open project appeared on a
  new Graphics track and played over the footage, transparent around it.

Not yet: graphics in a first cut (today they come from an edit), captions
generated from the transcript word by word, and audio from a composition
(rendered `.mov` files are picture only).

## OpenWhispr: transcription, and talking to Frameflow

OpenWhispr (OpenWhispr/openwhispr, MIT) is a dictation app built on
whisper.cpp. Frameflow uses it two ways:

- **Its transcription engine.** OpenWhispr pins and tests its own whisper.cpp
  builds (OpenWhispr/whisper.cpp, release 0.0.11). Besides the server its app
  runs, each release has a plain CLI build, `whisper-cpp-win32-x64-cpu.zip`
  (1.2 MB): whisper-cli under another name, with every option Frameflow uses,
  and the MSVC runtime DLLs beside it so it runs without the VC++
  redistributable. `python -m project.transcribe --install` fetches it into
  `tools/`, checked against the SHA-256 GitHub publishes for it, which is
  pinned in the code. Frameflow also uses a model in OpenWhispr's cache
  (`~/.cache/openwhispr/whisper-models/ggml-<name>.bin`) when it has none of
  its own. The installed app only ships the server, so Frameflow fetches the
  CLI build rather than depending on the app.
- **Dictation.** The app itself lets the creator speak prompts and edit
  requests into Claude Code. Nothing in Frameflow is needed for that.

This unblocked transcription on this machine, which had a model but no
whisper-cli. First cuts, footage in the prompt workflow, and the check by ear
now run end to end: 25.7 s of footage transcribes in about 37 s on the CPU.
The check by ear rendered a join through libopenshot and re-transcribed it;
on the test recording, which is mostly room noise, Whisper's word timings are
too loose for its verdict to mean much (it stretched one word over 9.6 s).

Not yet: GPU transcription (OpenWhispr's CUDA build is 773 MB; its Vulkan
build is server-only), and Parakeet, OpenWhispr's faster model, which runs on
sherpa-onnx rather than whisper.cpp.

## The content workflow: a video from a prompt

One prompt in, with whatever the creator has: a script, recordings, images or
clips, music. The video does not have to show the creator's face.
`project/produce.py` runs it in three stages, each a request the AI answers
with a JSON file that the next stage checks:

1. **Brief** (`brief.json`): format, aspect (16:9, 9:16 or 1:1), length,
   audience, tone, the skills it will use, and any open questions. The creator
   confirms it; open questions block the next stage.
2. **Storyboard** (`storyboard.json`): the script, then each scene in order -
   what is seen (a footage span, an image or clip, a HyperFrames title or
   composition), what the voice says, an optional caption. The creator
   confirms it.
3. **Build**: Windows' built-in voice reads each scene's narration; a scene
   lasts as long as its footage span, or as long as its narration takes. Images
   become clips with a slow push in. Titles and captions are rendered by
   HyperFrames. The project gets V1 (picture), Graphics, Captions, Voice and
   Music tracks. Under narration a visual's own sound drops to -60 dB; music
   sits at -18 dB under a voice, -6 dB without, and fades out at the end.

The result is an ordinary Frameflow project, so edits and the live OpenShot
window work on it as on any other.

Two kinds of capability, as agreed:

- **Skills are a library, not wiring.** The brief names the skills a video
  will use and why; the creator can change that. The creator will share their
  skills later, and a planner that offers them is still to build.
- **Features are built-in engines** with a fixed contract: first cut,
  HyperFrames graphics, voiceover, and later a "make it like this reference
  video" engine - the creator's own from-scratch rebuild of Hypit's idea.
  Hypit itself (hypit-ai/hypit) is under a modified Apache 2.0 that forbids
  bundling it in a product sold to others or hosting it for other people
  without a commercial license; a rebuild avoids that as long as no Hypit code
  is copied in.

What was learned building it:

- **OpenShot audio tracks**: OpenShot has none as such; an audio track is a
  layer of sound files, which draw nothing, so Frameflow puts them above the
  picture (the bottom layer is the main track). A sound file's reader must carry
  the fields libopenshot gives it itself - stream index, timebase, channel
  layout, frame rate and frame count - or it plays silence. Video readers do not
  need them. Found by rendering through libopenshot: the first audio test only
  compared levels and passed on the footage's own sound.
- **HyperFrames cards** centred with `left:50%` lay out in half the frame and
  wrap early; `width:max-content` with a max width fixes it.
- Vertical (`FHD Vertical 1080p 30 fps`) and square profiles exist in
  OpenShot 4.0.1.

Checked: a 9:16 product reel built from a prompt, an image and music - three
scenes, 14.1 s - rendered through libopenshot, with the voice and music heard
throughout and the titles, image and caption where the storyboard put them.

Not yet: an API mode (today the coding agent is the editor), stock footage and
AI-generated pictures, a better voice than Windows' (Piper or a paid one, as
another function in `voiceover.py`), word-by-word captions, and muting rather
than -60 dB (a volume of 0 is not read back yet).

## Deliberately not done

- **Headless video export**: the creator exports from OpenShot themselves. The
  engine runner could do it later with the same mechanism.
- **Rebuilding OpenShot from source**: not needed while its app code ships as
  Python.
