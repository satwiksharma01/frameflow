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

Not yet: graphics in a first cut (today they come from an edit), and audio
from a composition (rendered `.mov` files are picture only).

## A brand kit on every title, card and caption

The creator's look lives in one file, `brand/brand.json` (schema:
`project/schema/brand.schema.json`): a font, text, accent and background
colours, a logo, and whether captions are in capitals. Cards and captions read
it when they are rendered, so changing it restyles the next build and leaves
built projects alone. The storyboard request passes it to the agent, so the
compositions it writes match. With no kit, everything looks as before.

- **The font and logo travel with each composition.** HyperFrames renders a
  folder, so both are copied in beside `index.html` under fixed names
  (`brand-font.ttf`, `brand-logo.svg`, ...). A font file is declared for weights
  100-900, so Chrome draws it as it is instead of thickening it for bold.
- **HyperFrames drops the page's own background.** The first branded build put
  the background colour on `html, body`; the title screen rendered black, with
  the colour showing only on the card's plate. On the composition's root
  element it fills the frame.
- **Dark caption text needs a light outline.** With the kit's dark text and the
  black outline, captions over the footage could not be read. The outline is
  now picked against the text colour: black around light text, white around
  dark.
- Checked: the jacket reel rebuilt with a sample kit (Georgia Bold from a font
  file, cream, orange, an SVG logo, lower-case captions), with frames rendered
  through OpenShot's engine beside the plain build: title screens in the brand
  colour under the logo, captions in the font with the accent on the word being
  said, and the plain build unchanged.

Not yet: a kit per video (one kit applies to everything; swap the file for
another brand), and restyling a built project when the kit changes (a later
edit renders new caption lines in the new style beside the old ones).

## Product cards and lower thirds

Two card layouts of Frameflow's own, animated without GSAP like the plain
card: a product card (the product's name, a line under it, its price as a tag
in the kit's accent) and a lower third (a name, a role under it, an accent bar
at the left). Both take the brand kit and sit at the left, just above the line
where spoken captions go, so the two never cover each other.

- **Anchored to words, not seconds.** A storyboard is written before the voice
  is made, so the agent cannot know when a word will be said; it can name the
  words. A scene's card gives `when` ("the Nomad"), and the narration's word
  timings, or the recording's transcript over footage, say when the first of
  them is said. Words the scene does not say, or a card on top of another
  graphic, stop the build with the scene named.
- **In an edit,** a graphic takes `kind`, `subtitle` and `price` beside its
  text and lands at its moment of the recording, as graphics already did.
- **A fixed spot can cover a face.** On the jacket reel's photo, where the face
  sits mid-frame, the product card covers the eyes; on the talking-head short
  the lower third sits across the chin. The creator can move it (Location Y in
  OpenShot). Keeping cards off the face belongs with checking the picture.
- Checked through OpenShot's engine: the jacket reel with a product card on
  "the Nomad", in the sample kit, starts it on frame 80, where Piper says
  "the" (2.66 s), half faded in by frame 84; a lower third added by an edit to
  the first short, without a kit, comes up as the speaker starts and stays
  above the captions.

Not yet: a product photo in the card, and a price tag on its own pinned to the
item in the picture.

## Captions, word by word

`--captions` on a first cut, or `"spoken_captions": true` in a storyboard,
shows what is said as captions that pop in word by word, with the word being
said in yellow. `project/captions.py` groups the words into short lines and
puts them through the cut: a line never crosses a cut, and words from removed
spans are gone. Every line is a clip on a Captions track, so the creator can
move, trim or delete one like footage.

- **One render, many clips.** A HyperFrames render spends about 24 s starting
  up: a 2 s card took 25.8 s and an 8 s card 34.6 s. One render per line
  would take over an hour for a five-minute video. So every line is drawn back
  to back in one transparent .mov, and each clip plays its own span of it.
- **Where the words come from.** For recordings, Whisper's word timings
  (`timing.json`). They have no punctuation or capitals, so captions are
  drawn in capitals. For narration, the voice's own timings (Piper's phoneme
  durations, or the Windows voice's progress events), saved beside each .wav:
  exact, and in the script's own spelling ("$129"
  stays "$129", where Whisper would write the words it heard).
- **System.Speech reports word positions as if the audio were 16 kHz**,
  whatever the file's rate. Measured against the pauses in files written at
  16, 22.05 and 44.1 kHz; the default file is 22.05 kHz, so positions are
  scaled by 16000/22050. Corrected, "It's" started at 2.194 s against a
  measured pause ending at 2.204 s.
- **Lines**: at most 14 characters on a vertical video, 28 on a landscape
  one, measured in Arial Black capitals at the size used; a new line after a
  sentence ends or a pause of 0.35 s; a line stays up 0.3 s after its last
  word, or until the next line if that comes within 0.5 s. Whisper can stretch
  one word over seconds of noise, so a word holds its line 1.5 s at most.
- **Layout**: words not yet said keep their space, so a line doesn't jump
  sideways as it fills in. On a vertical video, lines sit at 68% of the height,
  above where the app's buttons and text cover a reel.

Checked on a real recording: a first cut keeping 268 s of 326 s got 173
lines from one render, in 4 min 26 s. Frames rendered by OpenShot's own
engine show each line transparent over the footage with the word being said
in yellow. The cost is size: the render is ProRes 4444, 465 MB for those
268 s. A codec that stores transparent areas cheaply (QuickTime Animation or
PNG in .mov) would be far smaller if libopenshot reads it.

**Edits move the captions with the cut.** Each line is anchored to the moment
of the recording under its start, and moves to where that moment now plays. A
line whose moment was removed goes; one that now runs into a cut stops there.
Speech left without a line - put back by the edit, or the surviving end of a
line that went or was cut short - gets new lines from `timing.json`, in one
small render. Lines the creator moved, trimmed or deleted by hand are
followed, kept trimmed, or stay deleted. Checked on the same recording:
removing a repeated sentence (3.6 s) moved 136 lines, dropped 2 and added 1
for a word left over, in 13.5 s. The edited audio, rendered by OpenShot's
engine and transcribed again, matched each line after the cut word for word.

Not yet: captions are not offered in an edit request ("add captions" today
makes a fixed graphic), and only tracks of captions follow the cut - a title
or card on the Graphics track keeps its position, since a title meant for the
opening shouldn't vanish when the first seconds are cut.

## Vertical video: a crop the creator can move

`--vertical` on a first cut, and footage in a 9:16 or 1:1 prompt-made video,
fill the frame: the IR clip gets `transform.fill`, which OpenShot shows as
Scale "Crop". The picture is scaled to cover the frame and framed on the face;
nothing is re-encoded, so the creator can change it like any clip setting.

- **Position is in OpenShot's own units.** For a filled clip in 4.0.1, a
  location of 1 moves the picture exactly off screen: half the frame plus half
  the scaled picture. The IR keeps positions as a fraction of the frame instead
  (`transform.position.x`), and the compiler and parser convert. Measured by
  rendering a white bar through OpenShot's engine: centred, it starts at pixel
  540 of 1080; moved by 0.1 of the frame, at 648.
- **A move by hand becomes a keyframe.** Changing Location X in OpenShot's
  properties with the playhead anywhere but a clip's first frame adds a point
  there, with linear interpolation and no handles: the picture slides to the
  new place. So the IR holds positions as keyframes too, in seconds of the
  recording; cutting a clip in two leaves each half with the same curve, so
  each moment keeps its framing. Checked in OpenShot itself: Location X set to
  0.1 at 5 s, saved, then an edit removed 1.9 s inside that clip; both halves
  kept the move, and frames rendered by OpenShot's engine show it.
- Speech an edit puts back is framed like the recording around it.
- A crop curve shaped by hand (Bezier handles moved), or a clip moved while it
  fits the frame, is still named by an edit as something it would lose.
- Shotcut refuses a filled clip rather than drop the crop.

**Following the face** (`project/reframe.py`). OpenCV's frontal-face
detector, which ships with OpenCV, runs on frames sampled four times a second
(1,303 frames of a 5-minute recording in about 7 s). The crop is a camera
operator, not a tracker:

- Detections are a 2 s median, so a miss, a nod or a glance aside does nothing.
- The window holds still until the face drifts more than a quarter of the
  window's width from where it has been, and then holds at least 2 s more.
- Each hold is framed on the median of where the face was during it, not where
  it started: framed on the first two seconds, the test recording sat further
  off-centre than a plain centre crop in 3 of 6 frames.
- A move takes 0.6 s, as keyframes on the clip's position in seconds of the
  recording, smooth (OpenShot's default Bezier) into its new place.
- The window stays inside the recorded picture: FFmpeg's cropdetect found
  black bars in the test recording leaving a picture only 508 px wide in a
  1280 px file, so the 405 px window can shift just 51 px either way.

Checked on that recording: the face was found in 1,243 of 1,303 frames; the
speaker never moved far enough to need a move, so the crop is one framing,
centred on where the face usually is. In 12 frames rendered by OpenShot's
engine across the cut, the face is a median 32 px from the frame's centre,
against 56 px for a centre crop (worst 139 against 125, while leaning). The
moves themselves are checked with simulated faces; OpenShot draws keyframed
positions where the IR says, as measured with the white bar.

Not yet: following on the vertical axis, or more than one person (the largest
face wins). And only the most recently opened Frameflow
OpenShot window can be changed live: a second window takes over the bridge
file, and closing it removes the file, so the first window's changes land on
disk but not on screen until it is reopened.

## Shorts from one long recording

`python -m project.shorts` asks the editor for the moments that stand on their
own (a hook in the first two seconds, a whole sentence at each end, 20-60 s),
then builds each as a first cut of its own: everything outside the moment is a
removal, so cut placement, face framing, captions and the check by ear are the
first cut's, unchanged.

Checked on the 5-minute test recording: three shorts (37, 42 and 23 s); every
cut moved into a measured pause, by 47 ms at most. Each short rendered through
OpenShot's engine and transcribed opens and ends where the plan said. What it
showed:

- **Whisper's own word timings fail in stretches of a long recording.** Over
  263-266 s, about 40 words were timed into half a second, and the next word
  ("basically") was stretched over 13 s. The short covering that stretch
  showed 14 caption lines in 0.4 s and then none for 11 s, and its check by
  ear flagged a join because the word it expected was wrong (the speech there
  is whole). Cut placement was unaffected: it uses measured pauses, not words.
  Transcribing an 8 s slice on its own also showed that a phrase the full
  transcript had twice ("I could also just tell") was said once.
- **Word timings now come from whisper.cpp's DTW alignment.** Measured
  against pauses, a token's DTW time is where the word *ends* ("yeah" at
  278.19 s, the pause after it from 278.22; "really" 258.33, pause 258.36). So
  a word ends at its last token's DTW time, and starts where the word before it
  ended, or at the end of a measured pause between them. Over the whole
  5-minute recording: words starting inside a measured pause went from 108 to
  0, words timed as zero length from 45 to 9, words stretched over 2 s from 3
  to 0, and the 263-266 s stretch is timed word by word. It needs the model's
  alignment preset (`-dtw large.v3.turbo`, read from the model's file name)
  and flash attention off: with it on, whisper.cpp quietly returns no DTW
  times. The word pass took 7 min for the 5.4-minute recording on whisper's
  default 4 threads, and 3.5 min on all 16 (an i5-12500H: 4 fast cores, 8
  slow), with the same words and times. On a 60 s slice the same pass took
  64 s on 4 threads, 50 on 8, 44 on 12 and 43 on 16, so Frameflow passes every
  thread. Transcribing each short's span again, tried first, was no
  better once the whole recording had DTW times, and is not done.
- **A word too short to read gets company.** With true timings, a short word
  left alone on a caption line ("the", "current") was up for 3 frames. A line
  that would be up for under 0.3 s now takes the last word of the line before
  it, across a breath of up to 0.5 s (as long as a line is held for the next
  anyway). Across the three shorts: no line up for under 0.3 s, no speech
  uncaptioned for over 2 s, and every join sounds clean.
- **A pause can sit inside a word.** The third short was meant to start after
  "So", in a measured 0.25 s pause; heard back, it still opens on "So", whose
  soft end runs under the silence threshold.

## Speech at the platforms' level

YouTube, Instagram and TikTok play speech at about -14 LUFS, and a quiet video
stays quiet beside everything else in the feed. Frameflow measures each
recording and each voice line with ffmpeg's loudnorm and sets a clip volume
(`volume_db`) that brings it toward -14 LUFS, stopping where its true peaks
would pass -1 dBTP. It is an ordinary clip setting: OpenShot shows it as the
clip's volume, it survives a save and later edits, and footage put back by an
edit gets the volume of the recording around it. First cuts, shorts, voice
lines and footage in prompt-made videos get it; Shotcut projects do not yet
(its compiler does not write clip volume).

- **OpenShot keeps loudness exactly.** Rendered tones at +6 and +13.2 dB came
  out +6.00 and +13.20 louder, so volumes above 0 dB work. A mono file plays
  into both channels 3 dB down each: just as loud, with peaks 3 dB lower. So
  a file is measured as it will play, converted to stereo first; without that,
  Piper's mono lines had their peaks overstated by 3 dB and were turned down.
- **Volume alone stops short of -14 on peaky speech.** The test recording reads
  -31.6 LUFS with a true peak of -14.2 dBTP; +13.2 dB is all it can take, and
  it lands at -18.4. Piper normalizes its output to full scale, so its lines
  get about +2 dB. Rendered through libopenshot: the three shorts went from
  -31.6 to -18.4, -18.0 and -18.8 LUFS, peaks -1.1 to -1.8 dBTP; the Piper reel
  from -19.4 to -16.3, peak -1.0. Getting to -14 needs a limiter or compressor
  on the voice. OpenShot has a Compressor effect, but `edit` refuses projects
  with effects today, so adding one means teaching edits to keep effects
  first.
- The joins still check clean when louder: 2 of 2, 3 of 3.
- Measuring the 5.4-minute recording takes about 10 s; each short measures it
  again.

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
3. **Build**: Piper's voice (or, without it, a Windows voice) reads each
   scene's narration; a scene
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

A voice that can be posted (2026-10-31):

- **Piper** (OHF-Voice/piper1-gpl, GPLv3, `pip install piper-tts`) reads
  offline with a natural voice. Its voices carry their training data's
  licence, and most English ones are non-commercial or unclear: hfc_female and
  ryan are CC BY-NC-SA; amy, kusal, alan and jenny point elsewhere; lessac's
  Blizzard licence is restrictive, and most voices are fine-tuned from lessac.
  Trained on public-domain recordings: ljspeech, kristin, norman, john, bryce
  (US) and cori (UK). Frameflow installs `en_US-ljspeech-high` by default.
- **Word timings come from the voice itself.** Loaded with
  `include_alignments=True`, Piper gives every phoneme's length in samples;
  they add up exactly to the audio. Words are the runs of phonemes between
  spaces (`^` and `$` open and close a sentence). To line them up with the
  script, each script word is phonemized on its own to count its runs: "$129"
  is said as three. On six reel-style lines the counts matched five times; in
  "everyone... so," Piper runs two words together, and times are then spread
  in proportion.
- Loading the voice takes about 3 s, once per build; reading three sentences
  took 1.1 s.

Checked: the jacket reel rebuilt with Piper and spoken captions (3 scenes,
11.1 s, 11 caption lines), rendered through libopenshot and transcribed with
DTW word times. 24 of its 25 words were heard (Whisper wrote "shrubs" for
"shrugs"); every caption line comes up within 0.09 s of its first word being
heard, under 3 frames, and words were placed a median 0.08 s after Whisper
heard them start.

Not yet: an API mode (today the coding agent is the editor), stock footage and
AI-generated pictures, and muting rather than -60 dB (a volume of 0 is not
read back yet).

## Deliberately not done

- **Headless video export**: the creator exports from OpenShot themselves. The
  engine runner could do it later with the same mechanism.
- **Rebuilding OpenShot from source**: not needed while its app code ships as
  Python.
