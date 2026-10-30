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

## The content workflow (agreed, not built yet)

One prompt in: what the creator wants, plus an optional script, raw footage
and assets. The video does not have to show the creator's face. Stages: brief
→ script → storyboard (each scene picks its source: footage, graphic, asset,
generated media, voiceover) → make the pieces → assemble into the editable
project → check and refine.

Two kinds of capability:

- **Skills are a library, not wiring.** Content skills (hooks, scripts,
  platform playbooks, caption styles) sit in one folder with a description
  each. For every video the AI writes a plan naming the skills it will use and
  why, and the creator can change it. A per-user profile (brand voice, skills
  always or never used) personalises it. The creator will share their skills
  later.
- **Features are built-in engines** with a fixed contract, registered in a
  table like the editors: first cut, HyperFrames graphics, a "make it like
  this reference video" engine, and later voiceover and music.

The reference-video engine will be the creator's own rebuild of Hypit's idea,
written from scratch. Hypit itself (hypit-ai/hypit) is under a modified Apache
2.0 that forbids bundling it in a product sold to others or hosting it for
other people without a commercial license. A from-scratch rebuild avoids that,
as long as no Hypit code is copied into it. How Frameflow uses the engine will
be decided once it exists; the key question is whether it hands over separate
layers that land on separate tracks rather than one flat render.

## Deliberately not done

- **Headless video export**: the creator exports from OpenShot themselves. The
  engine runner could do it later with the same mechanism.
- **Rebuilding OpenShot from source**: not needed while its app code ships as
  Python.
