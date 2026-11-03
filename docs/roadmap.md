# Frameflow roadmap

What OpenMontage does, what Frameflow does differently, and what to build next
for the videos Frameflow is for: YouTube videos, pitches for ideas, and reels
(fashion, lifestyle, products woven in).

Written 2026-10-31, from OpenMontage's `main` branch on that day. "Where
Frameflow stands" updated 2026-11-04.

## How this was worked out

The method is the investigation workflow of REA (morluto/rea): turn the
question into a checklist, answer each item from evidence, and keep what was
seen apart from what was inferred and what is still unknown. REA's own skill
says to skip its binary and app tooling when the full source is available, and
OpenMontage's is, so the evidence is its repository:

- the README and `AGENT_GUIDE.md` (its contract for agents);
- two pipeline manifests, `talking-head.yaml` and `clip-factory.yaml`;
- the whole file list (2,669 paths) from GitHub's tree API, searched by name;
- the header text of `auto_reframe.py`, `export_bundle.py` and
  `skills/meta/video-reference-analyst.md`.

OpenMontage is AGPLv3. Nothing here copies its code; this is a map of what it
does, so Frameflow can decide what to build in its own way.

## What OpenMontage is

An agent-first production system. There is no orchestrator in code: the coding
agent reads a pipeline manifest (YAML), then a "director" instruction file
(Markdown) for each stage, and calls Python tools. Every pipeline runs the same
stages: research, proposal, script, scene plan, assets, edit, compose, publish.
Each stage writes a JSON artifact checked against a schema, and the stages
marked for approval cannot be written as complete without it.

The output is a rendered file, `projects/<name>/renders/final.mp4`, composed
by Remotion (React), HyperFrames (HTML) or FFmpeg.

## Findings

O = observed in the evidence, I = inferred from it, U = unknown.

| Question | Answer | |
|---|---|---|
| Does the creator get a project to edit? | No editor project anywhere: no OTIO, FCPXML, EDL, Premiere, Resolve, Kdenlive or OpenShot file in 2,669 paths. The deliverable is `final.mp4`; changes go back through the agent as new `edit_decisions` and a new render. | O (a search of file names, not of file contents) |
| Do the creator's own edits survive? | There is nothing for them to survive in: the creator never holds the timeline. | I |
| How is the work driven? | Agent-first: 13 pipeline manifests (one a smoke test), a director file per stage, 209 Python files under `tools/`, found through a registry. | O |
| How is talking-head footage handled? | Transcribe, cut silences, track faces, reframe, burn in captions with Remotion, colour grade, retouch faces and eyes, clean up audio. The pipeline is marked beta. | O |
| Long recording to many shorts? | `clip-factory`: rank candidate clips, keep each self-contained, put the hook in the first 2-3 s, plan the framing per platform, write metadata per clip. Beta. | O |
| Vertical from landscape? | `auto_reframe`: face tracking with MediaPipe/OpenCV, a smoothed track, then an FFmpeg crop baked into the file. | O |
| "Make me something like this"? | A reference video is analysed for transcript, pacing, scenes, keyframes and style; then come 2-3 differentiated concepts, a cost estimate and a sample before full production. | O |
| Captions? | Word by word, burned into the render by Remotion. | O |
| Quality checks? | After rendering: ffprobe, frames from 4 positions checked for black frames and broken overlays, audio checked for silence and clipping, subtitles checked. Before rendering, a "slideshow risk" score. | O (how well they work: U) |
| Approval and visibility? | Gates at proposal, script, scene plan, assets and publish. Backlot, a local web board, shows the run live and replays it. | O |
| Cost? | Estimate, reserve, reconcile; asks above $0.50 per action; $10 cap by default. | O |
| Providers? | 60+ by its own count: 20+ video generators, 15+ image, 10+ voices, music (Suno, ElevenLabs, a local library folder), 16 stock-footage sources. | O |
| Look and feel? | Style playbooks (YAML: type, colour, motion, audio) and platform profiles (YouTube, Shorts, Reels, TikTok, LinkedIn). | O |
| Publishing? | A local export bundle with the render and SEO metadata; no upload yet. | O |

## Where Frameflow stands

| | OpenMontage | Frameflow today |
|---|---|---|
| What the creator gets | A rendered `.mp4` | An OpenShot project (or Shotcut), every cut, graphic, caption and sound a clip they can change |
| Their changes by hand | Not a concept | Detected and kept; an edit that would undo one is refused unless asked |
| Asking for changes | The agent re-renders | Applied to the project as it is now, live in the open OpenShot window, one Ctrl+Z to undo |
| Cuts in speech | Silence cutting | Cut points moved into measured pauses, then every join played back through OpenShot's engine and transcribed to check no word was clipped |
| Sound | Audio clean-up; checked for silence and clipping after rendering | Speech set toward -14 LUFS as a clip volume; no clean-up, and no limiter yet |
| Captions | Burned in | Word by word, each line a clip, following the cut through later edits |
| Video from a prompt | 12 pipelines, research, generated images and video | Brief, storyboard, build: the creator's footage, images and music, HyperFrames titles, Piper's voice |
| Graphics | Remotion and HyperFrames, GSAP | HyperFrames without GSAP (GSAP's licence doesn't fit), transparent clips on their own track; product cards and lower thirds that come up when their words are said |
| Reframing to vertical | Face tracking, the crop baked into a new file | Face following as a crop and position on the clip, which the creator can nudge in OpenShot and later edits keep |
| Long video to shorts | Ranked clips, hook first, metadata per clip | Each short its own vertical project with captions, every cut in a measured pause and heard back; a title, description and tags from `publish` |
| Reference video | Yes | Planned: the creator's rebuild of Hypit |
| B-roll and stock | 16 stock sources, CLIP search | The creator's own images and clips on a B-roll track, anchored to what is said and moved by later edits; no stock |
| Voice, music | Piper and ~10 paid voices; music generation and search | Piper with a public-domain voice, or Windows'; the creator's music, with the cuts on its beat when asked |
| Generated pictures and video | Many providers | Google's Gemini behind one interface, with the creator's key; a free stand-in for trying it |
| Look and feel | Style playbooks (type, colour, motion, audio) and platform profiles | A brand kit (font, colours, logo, caption style) on every title, card and caption; a colour LUT per video on the picture; aspect and loudness per platform |
| Checks on the picture | After every render | After every build and edit: black frames, captions off screen and graphics over a face, in frames OpenShot's engine draws |
| Publishing | An export bundle: the render and SEO metadata | A title, description, tags and chapters beside the project, checked against YouTube's limits; the chapters follow the cut; uploading stays the creator's |
| Cost control | Yes | An estimate before anything paid runs, and a cap per build that is $0 unless the creator raises it |

**Where Frameflow wins: the project stays the creator's.** OpenMontage's answer
to "change this" is to render again. Frameflow's answer is a timeline the
creator can open, change by hand, and ask for more changes on, without losing
their own. Every item below keeps that: whatever Frameflow adds lands in the
project as something editable, not baked into pixels.

**What not to chase:** breadth for its own sake. Sixty providers, 3D worlds,
character rigs and avatars don't serve YouTube, pitches and reels made from the
creator's own footage. Borrow OpenMontage's ideas where they serve those, and
build them Frameflow's way.

## Roadmap

Ordered by what unblocks the most of the vision soonest. Each step ends with a
check that can be run, as everything so far has.

### 1. Reels from your own footage

The format the creator posts most, and the shortest path from what exists.

- **Vertical reframing that stays editable.** A 16:9 recording becomes 9:16
  through a crop and position on the clip, not a crop baked into a new file:
  the creator can nudge it in OpenShot. Start with a fixed centre crop (it fits
  how the creator's webcam recordings are framed), then follow the face, as
  smoothed position keyframes. *Done when:* a first cut with `--vertical` opens
  in OpenShot as 1080×1920 with the face in frame throughout, and moving the
  crop by hand survives the next edit.
  *Status:* built and checked (2026-10-31): `--vertical` on a first cut and
  footage in 9:16 and 1:1 prompt-made videos fill the frame, framed on the
  face, with smooth moves when the speaker moves; a crop moved by hand in
  OpenShot is kept through an edit.
- **Many shorts from one long recording.** The editor picks N self-contained
  moments (a hook in the first 2 s, no mid-sentence starts), and each becomes
  its own project with captions and vertical framing. It reuses the first cut,
  cut placement, captions and the check by ear. *Done when:* the 5-minute test
  recording gives 3 shorts, each starting and ending in a measured pause.
  *Status:* built (2026-10-31): `python -m project.shorts` and the `shorts`
  skill. The test recording gave 3 shorts of 37, 42 and 23 s, every cut in a
  measured pause; heard back through OpenShot's engine, each opens and ends on
  a whole sentence. Word timings now come from whisper.cpp's DTW alignment,
  because Whisper's own collapsed in places and left a short with 11 s of no
  captions; with them, and lines that never flash by, every caption line in
  the three shorts is up for at least 0.3 s (see findings).
- **A voice that can be posted.** Piper (offline, free) beside the Windows
  voice; it also needs word timings for captions. *Done when:* a prompt-made
  reel narrated by Piper has captions in sync, checked by transcribing it.
  *Status:* built and checked (2026-10-31): Piper's public-domain
  `en_US-ljspeech-high` voice is the default, with word timings from its own
  phoneme durations. The jacket reel rebuilt with it, rendered through
  OpenShot's engine and transcribed: every caption line comes up within
  0.09 s of its first word (see findings).
- **Loudness and level for the platform.** Measure integrated loudness (LUFS)
  and set the voice level for the platform's target as a volume on the clips,
  so it stays adjustable.
  *Status:* built and checked (2026-10-31): speech is set toward -14 LUFS, as a
  clip volume, stopping where its peaks would pass -1 dBTP. Rendered through
  OpenShot's engine: the three shorts went from -31.6 to -18.0 to -18.8 LUFS,
  the Piper reel to -16.3. Reaching -14 on peaky speech needs a limiter, which
  volume alone cannot do (see findings).

### 2. Product pitches and fashion reels

- **A brand kit.** Fonts, colours, logo and caption style per creator, used by
  every title, card and caption: OpenMontage's style playbooks, kept small.
  *Done when:* changing the kit restyles the next build without touching code.
  *Status:* built and checked (2026-11-01): `brand/brand.json` sets the font
  (a file or an installed font), text, accent and background colours, a logo
  and caption capitals. The jacket reel rebuilt with a sample kit, frames
  rendered through OpenShot's engine: title screens in the brand colour under
  the logo, captions in the brand font and accent; without a kit nothing
  changes (see findings).
- **Product cards, price tags and lower thirds** as HyperFrames templates of
  Frameflow's own (no GSAP), anchored to the moment a product is named.
  *Status:* built and checked (2026-11-01): a product card (name, a line, the
  price as a tag) and a lower third (name, role), in the brand kit, at the
  left above the captions. A storyboard scene's card comes up as its words
  are said; an edit places one at a moment of the recording. Checked through
  OpenShot's engine: on the jacket reel the card came up on the frame where
  the voice says "the Nomad". The price tag lives inside the product card; a
  tag pinned to an item in the picture is not built (see findings).
- **B-roll on its own track.** First from the creator's own asset folder,
  matched to what is being said; stock (Pexels, Pixabay, with the creator's
  free keys) only if they want it. Clips sit on a B-roll track, anchored to the
  transcript like graphics, so edits move them too.
  *Status:* built and checked (2026-11-01), from the creator's own files: a
  storyboard scene cuts away as its words are said, an edit at a moment of the
  recording. Each fills the frame with its own sound turned down, and later
  edits move graphics and B-roll with the cut. Checked through OpenShot's
  engine on the first short: a photo and a clip came in on their words, the
  speaker's voice carried on under the clip, and after an edit removed 2.13 s
  before them both moved up 2.13 s. No stock yet, and nothing helps the agent
  see what a clip shows (see findings).
- **Cutting to the beat.** Beat detection on the music, so fashion and
  lifestyle reels cut on the beat; cuts stay ordinary clip boundaries.
  *Status:* built and checked (2026-11-01): when the storyboard's music sets
  `cut_to_beat`, each cut moves to the nearest beat it can without cutting
  into a word that is heard, the narration or the end of a clip. The beat comes
  from Frameflow's own tracker (numpy). Checked on a 120 BPM track: a six-scene
  reel rendered through OpenShot's engine had 4 of its 5 cuts within 16 ms of a
  beat; the fifth stayed off the beat to keep a word whole (see findings).
- **A look per video:** a colour LUT as an OpenShot effect the creator can
  switch off.
  *Status:* built and checked (2026-11-01): a storyboard's `look` is one of
  the creator's own LUTs (`--look`) or one of the 50 OpenShot ships (CC0), put
  on every footage, image, clip and B-roll clip as OpenShot's Color Map effect;
  titles, cards and captions keep their colours. Edits keep it. Rendered through
  OpenShot's engine: every picture frame graded, the titles and the caption's
  own pixels unchanged, and with the LUT set to None on each clip the video
  came back exactly as built without a look (see findings).

### 3. "Make it like this"

The reference-video engine: the creator's from-scratch rebuild of Hypit, to be
integrated when it is handed over. OpenMontage's version shows the useful
shape: analyse pacing, shot lengths, caption style and the hook; propose 2-3
concepts that keep the structure and change the subject; make a short sample
before the whole video. In Frameflow it produces a storyboard, so the rest of
the prompt workflow builds it as an editable project.

### 4. YouTube videos and pitches

- **Chapters and a publish package:** title, description, tags and chapter
  times from the transcript, written beside the project (OpenMontage's export
  bundle). Uploading stays the creator's.
  *Status:* built and checked (2026-11-02): `python -m project.publish` and
  the `publish` skill write `publish.txt` beside the project, each part ready
  to paste into YouTube Studio and checked against YouTube's limits. A chapter
  starts at a moment of the recording, so writing it again after an edit moves
  it with the cut. On the test recording's first cut, rendered through
  OpenShot's engine, each of seven chapters opened on its words; after an edit
  took out 6.27 s before the third, the five after it moved up and still did.
  Videos made from a prompt are not covered yet (see findings).
- **Screen recordings for builder content:** a screen recording plus a face
  camera, laid out picture-in-picture as editable clips.
  *Status:* built and checked (2026-11-02): `--screen` on a first cut puts the
  screen recording on a Screen track under the face, which shrinks to the
  bottom-right corner of a 16:9 frame. The two are lined up by the voice both
  recorded, and an edit cuts the screen wherever it cuts the face. On a
  made-up pair, the test recording and a screen recording carrying its voice
  through another microphone, started 3.217 s earlier, it found 3.219 s.
  Rendered through OpenShot's engine, the screen showed exactly the frame
  expected and the face its own, before and after two edits, and a face moved
  and resized by hand and a zoomed screen clip were kept. Not checked on a
  real screen recording yet (see findings).
- **Research for pitches:** the agent gathers facts with sources into the
  brief, which the creator confirms like any brief.
  *Status:* built and checked (2026-11-02): the brief carries `facts`, each
  with who says it, its page and the exact words on it. `--brief` opens every
  page and looks for those words before the creator confirms, refusing a
  misquote or a page that is not there, and leaving a PDF or a page it cannot
  read for the creator to open. The narration names the source where a number
  carries the point. Checked on a pitch for Frameflow: four facts from Goldman
  Sachs, YouTube and Adobe found on their pages, a misquote and a made-up page
  refused, and the 59-second video heard naming each source (see findings).

### 5. Checks on the picture, and a library of skills

- **Look at the result:** after a build, render frames through OpenShot's
  engine and check for black frames, captions off screen, and graphics covering
  a face, the way the check by ear already listens to joins. *Done when:* a
  deliberately misplaced caption is reported.
  *Status:* built and checked (2026-11-03): after a first cut, a short, an
  edit or a produce build, OpenShot's engine draws frames and Frameflow
  reports black frames (just after each cut, in each clip, and wherever the
  main track is empty), captions running off the screen (each line in its last
  frame), and titles, cards or lower thirds over a tenth of a face OpenCV
  finds. On the captions-check cut, the two captions moved by hand were the two
  of 172 reported, and the gap a deleted clip left was reported black; a
  product card and a lower third over faces were reported, and two reels of
  titles were clean (see findings).
- **The creator's content skills as a library:** their skills, once shared,
  offered per video and picked in the brief, as agreed; never wired in.
- **Generated pictures and video, optionally:** behind one interface, with a
  cost estimate and a cap before anything paid runs (OpenMontage's budget
  rules), and the result landing as an ordinary clip.
  *Status:* built and checked with a free stand-in (2026-11-04): a storyboard
  scene can be a `generated` picture or clip described in words. Before the
  build makes any, it adds up what the new ones cost and stops above the
  video's cap, which is $0 unless the creator raises it with `--budget`; each
  is made once, then lands as an ordinary asset clip. Google's Gemini (Nano
  Banana 2.1 pictures, Gemini Omni Flash clips) runs once the creator sets
  `GEMINI_API_KEY`: it is paid only, and not called yet. A teaser built with
  the stand-in placed both on the main track, built again without making them
  twice, and with Gemini chosen stopped at $1.06 over the $0 cap before any call
  (see findings).

### Later, outside this repository

Plugging Frameflow into Produk, when that work starts. Not before.

## Deliberately not planned

- **Headless export by default.** The creator exports from OpenShot.
- **Avatars, lip sync, 3D worlds, character animation.** OpenMontage has them;
  none of the three kinds of video needs them.
- **A web board like Backlot.** OpenShot's window is already where the creator
  watches the project change; a board would be a second place to look.
- **Translation and dubbing.** Worth a look once there is an audience abroad.
