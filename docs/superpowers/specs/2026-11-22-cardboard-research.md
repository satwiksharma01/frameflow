# Cardboard research: how it works, how it keeps quality, and how Frameflow gets there for free

**Date:** 2026-11-22 · **Status:** research, not a spec · **Why:** Satwik wants Frameflow to do what Cardboard does (Higgsfield to be an optional connection later), using free tools, HyperFrames and Remotion.

**Read:** cardboard.ai (home, `/desktop`, `/pricing`); docs.cardboard.ai (`/mcp`, `/mcp/tools`, `/mcp/first-video`, `/mcp/examples`, `/mcp/chatgpt`); the YC company page and Launch YC post; two YC job posts (Senior Applied ML Engineer, Evals & Data; Founding Design Engineer); OutlierKit's review; Shushant Lakhyani's "Cardboard vs HyperFrames" (Medium, 2026-11-06); mcpmarket's listing; remotion.dev (`/docs/license/pricing`, `/docs/license/faq`, `/docs/player`); the HyperFrames README. Everything below is in Frameflow's words. Claims are Cardboard's own unless marked as a reviewer's.

---

## 1. What Cardboard is

- **The company:** an agentic video editor from YC W26, built by a team of 8 in Bengaluru. Saksham Aggarwal (CEO) is a creator with about 250k views a month; Ishan Sharma (CTO) made Apple-style launch videos at HackerRank.
- **What it does:** turns the footage you already have into an edit you can watch, change and export. Its own line: it "edits the footage you already have", unlike generators such as Runway or Sora. It can still generate clips, images, music and voice for credits.
- **Who it's for:** growth and marketing teams first, then serious creators. They describe their aim as "vibe editing", and the Figma or Canva of video.
- **Where it runs:** a browser app (a real multitrack editor built on WebCodecs and WebGPU, backed by a cloud media pipeline), a Mac app that edits locally, a CLI, and an MCP server for Claude and ChatGPT.
- **What it costs:** Lite is $8 a month, or free in the Mac app, with three watermarked 1080p exports. Starter is $29, Creator $59 and Pro $175. Plans pay with two kinds of credits: **usage credits** for the agent's analysis, edits and cloud time, and **generative credits** for made media.

## 2. How it works

### The Director loop

Cardboard's agent is called the **Director**. Its loop, from the Mac app's page:

1. **Plans the edit, and shows the plan before editing.** The prompt can be "three 30-second ad variants" or "a testimonial from these interviews". An "Improve prompt" button rewrites a thin prompt first.
2. **Builds the cut on a real multitrack timeline.** Captions, the edit, voiceover and score each sit on their own track.
3. **Checks its own work on the frames.** It looks at frames of the result as the player draws them.
4. **You direct it** by chat or by hand on the timeline. Every change is a version you can undo.

They describe the difference from other tools like this: Descript's agent works on the transcript, CapCut gives you tools one at a time, and the Director edits a full timeline, matches a whole reference video, and checks its own work on the frames.

### The toolbox (its MCP server, 37 tools for Claude, more for ChatGPT)

The tool list is the best evidence of how the agent actually works:

| Group | Tools |
|---|---|
| **Timeline** | read it; **check an edit without applying it** (a dry run that shows what would change); apply an edit (cuts, trims, order, titles, look), saved as a version; **verify** (gaps, overlaps, text off screen, missing media); history; undo; **look** (frames of the edit as the player draws them) |
| **Media** | bring in a link (YouTube, X, Instagram, TikTok, files); screenshot a web page; search stock, archival and YouTube footage for a shot; search Cardboard's music library by mood; search its sound-effects library (whooshes, hits, clicks); probe a file; grab a frame; a **filmstrip** (evenly spaced frames in one image); **find scene cuts**; cut out the subject (credits) |
| **Audio and speech** | waveform image; audio levels (quiet parts, beats, loudest moment); clean speech and split stems; transcribe with word times; search transcripts; captions from transcripts; find silence; measure loudness |
| **Preview and export** | export, job status, cancel, show the preview in chat |
| **Help** | **docs**: Cardboard's editing guide, which the agent reads and follows while it edits |
| **ChatGPT only** | generate a clip, image, voiceover, music or sound effect with hosted models; voices and clones |

### What the user gets beyond the loop

- **Recipes:** 60 to 80+ ready-made video styles, such as a launch video, product showcase, podcast clip, testimonial, travel montage, vlog, caption styles, and stylised ones like "Paper Collage", "Invisible Glass" and "Keyframed Portal". Your footage drops into the style.
- **Matching a reference:** paste a link and it matches the pacing and colour, and on Creator and above the text styles and audio too.
- **Motion graphics from one line:** for example a chrome title, a liquid gradient, a globe with shipping routes, or a logo burst. Each lands editable on the timeline, and 3D product spins are possible.
- **Cutting to the beat,** with match cuts, transitions and effects synced to the music.
- **Clean-up:** dead air, filler words and retakes are removed. It finds the best moments in long recordings and labels them (story, advice, hot take). Captions, and reframing around the speaker.
- **Search by meaning:** "customer talking about ROI" finds the clip.
- **B-roll from the web:** the agent searches and watches dozens of candidate clips, 132 in their demo, and places the one that fits the line.
- **Voice cloning,** generated music and sound effects, and generated clips, all for credits.
- **Sharing and export:** a share link with comments for a team; export up to 4K; send the timeline to Premiere Pro or DaVinci Resolve.
- **Bring your own agent:** connect a paid Claude or ChatGPT plan, "no API keys"; or drive it from any agent through the CLI or MCP.
- **Privacy:** in the Mac app, footage stays local; only frames and the transcript go to the AI.

## 3. How it keeps quality

Eight mechanisms, from the strongest evidence to the weakest:

1. **Plan before acting, and show the plan.** You see the plan before it edits, which catches a wrong reading before any time is spent.
2. **A dry run before every change.** "Check a timeline edit" shows what would change without changing it.
3. **Deterministic checks.** "Verify the timeline" catches gaps, overlaps, text off screen and missing media.
4. **Looking at its own result.** "Look" shows the agent frames of the edit as the player draws them, so it judges the real render, not its memory of the plan.
5. **Every edit is a version.** Undo is always one step, so a bad edit costs nothing.
6. **An editing guide the agent follows.** The "docs" tool is their craft knowledge, read on demand: the same idea as Frameflow's playbooks.
7. **Proven styles.** Recipes and reference matching start every video from a style that already works, rather than from a blank page.
8. **Evals from real runs.** Their ML job post describes it: real agent runs are studied, failures become evaluation cases, quality is measured offline and online with automated checks and human review, and regression checks gate every release, with quality, latency and cost tracked. Taste is an explicit value: the design-engineer post asks for "design.md" files that set interface rules for the team *and its agents*.

Their stated stance on a first cut, on the homepage: the first version is supposed to be rough. Iteration is part of the design.

**Where reviewers found it short** (Medium, 2026-11-06; OutlierKit):
- hook text sat in front of the speaker's head until the subject cut-out finished in the background;
- it can't hear its own mix, so the user has to check the music level, and a recipe's sound peaks ran a little loud;
- it used still screenshots of websites where scrolling recordings would have been more alive;
- a generated recipe had small physics glitches;
- credits add up: 78 for a 35 s reel, 179 for one 10 s recipe;
- the Mac app is Apple Silicon only, there's a file-size cap, and it isn't built for frame-level work or heavy effects.

## 4. How it handles direction

The user directs at four levels:
- **the prompt,** improved on request;
- **a recipe** (a style);
- **a reference link** (pacing, colour, text, audio);
- **the conversation and the timeline afterwards.**

The Director decides everything else. There is no visible taste system beyond the recipes and the editing guide. Every user picks from the same 60 to 80 recipes, which is exactly where Frameflow's per-creator catalog (the taste engine) would differ.

---

## 5. Frameflow against Cardboard, part by part

| Cardboard | Frameflow today | Gap | Free way to close it |
|---|---|---|---|
| Director: plan shown, then cut | plan (brief) approved, then storyboard approved, then build | none in spirit; the plan is already shown | — |
| Dry run of an edit | change in words reports what changed after the fact | a preview of the change before applying it | the engine already computes the operations; show them first |
| Verify the timeline | picture check (black frames, captions off screen, graphics over faces), check by ear at joins, loudness | text in the platform's safe zones; overlaps; missing media is checked at build | extend the picture check (piece 4 of the creative engine) |
| **Look at its own result** | the picture check is code; the agent never looks at the build | **the agent judging real frames** of what it made | render frames or a contact sheet of the preview (Frameflow already renders frames) and give them to the agent in a check request |
| Versions and undo | Ctrl+Z in the app, `history/`, one Ctrl+Z in live OpenShot | — | — |
| Editing guide the agent reads | skills and requests carry the guidance | a craft library read on demand | the playbooks through the harness (piece 3) |
| Transcribe, silences, loudness, beats | yes (whisper word times, pauses, `beats`, loudness) | — | — |
| **Filmstrip, scene cuts, grab frame** | not in the engine (done by hand for run 11) | **the agent seeing inside clips** | ffmpeg contact sheets and scene detection, as the taste-engine plan's `from-reel` already does; make it a per-clip step at prepare |
| **Search by meaning** | no | **finding the shot** ("the close-up of the collar") | at prepare, the agent describes each shot from its filmstrip into a shot index (`shots.json`), searched by words; costs only the creator's own agent |
| Best moments in long recordings | `shorts` | — | — |
| Cut out the subject (hook text behind the head) | no | text that sits behind a person | open-source matting (e.g. RobustVideoMatting, GPL-3.0) as an optional tool; heavy, later |
| Clean speech, split stems | no | music removed from a recording; speech cleaned | open-source separation (e.g. Demucs, MIT) as an optional tool |
| Music and sound-effect libraries | creator's own music; no sound effects | **sound design** | a small bundled set of CC0 sound effects (whoosh, hit, riser, click); the creator's own music folder as a library searched by mood (tags from the agent) |
| Motion graphics from one line | HyperFrames titles, cards, captions and overlays written by the agent | one-line motion-graphics requests as a named feature, landing as editable clips | HyperFrames already does it; add it to the edit vocabulary (piece 2) |
| Recipes (60–80 styles) | "make it like this" from a reel | ready styles to start from | the taste engine's worlds and catalogs (piece 1), plus a small set of starter recipes Frameflow ships |
| Match a reference link | `--reference` through Agent Video | matching from a **link** (downloading the reel) | yt-dlp (Unlicense) to fetch a link the creator gives; the analysis exists |
| Cut to the beat | `cut_to_beat` | match cuts, transitions and effects on the beat | piece 2 |
| Web B-roll | no; generation behind a $0 cap | B-roll the creator didn't shoot | Pexels and Pixabay (free, but each needs a free API key); or the creator's own folders |
| Voice cloning, generated music and clips | Piper voices (local, free); Gemini behind a cap | cloned voice, generated music and clips | **not free at quality.** Open models with clean licences are rare (several popular ones are non-commercial). Keep these as optional paid connectors; Higgsfield fits here later |
| Multitrack timeline in the app | storyboard (scenes) in the app; the timeline is OpenShot's, with live changes | a timeline in Frameflow's own window | piece 6; see Remotion below |
| Share link with comments | no (local app) | team review | out of scope for a local app for now |
| Export MP4, or the timeline to Premiere or Resolve | the OpenShot project; export from OpenShot | **an NLE handoff** | OpenTimelineIO (Apache-2.0) export from the IR, which free Resolve imports; FCPXML for Final Cut |
| Bring your own agent; CLI and MCP | thinks with Claude Code, OpenCode or a key; CLI; skills | **an MCP server** so any agent can drive Frameflow | wrap the engine's commands as MCP tools; free |
| Evals from real runs | 731 engine tests, picture and ear checks, run notes in the vault | **quality measured across real videos** | a small evaluation set: real runs (like run 11) with what a good result must show, re-run after each engine change |

**What Frameflow already does that Cardboard doesn't advertise:** checks facts on their sources before a pitch states them; listens to every join; works fully locally with free voices; keeps an editable project in an open-source editor; and is about to have a taste engine with a catalog per creator.

## 6. HyperFrames and Remotion

| | HyperFrames | Remotion |
|---|---|---|
| Licence | **Apache-2.0**: free for everyone, compatible with Frameflow's GPLv3 | **Source-available.** Free for individuals and companies of up to 3 people, with unlimited commercial use. Bigger companies pay: a video editor or prompt-to-video app, or any app that embeds the Remotion Player, counts as "Remotion for Automators" at $0.01 per render with a $100 monthly minimum, and telemetry becomes mandatory for them from Remotion 5.0 |
| Authoring | plain HTML, CSS and GSAP; no build step; easy for an agent to write | React components; needs a bundler |
| Rendering | headless Chrome and ffmpeg, deterministic, frame-accurate | headless Chrome and ffmpeg |
| Preview | `hyperframes preview` (a browser editor) and a Studio app | **the Player**, a React component that plays a composition live inside an app; the Studio can't be embedded |
| In Frameflow today | titles, cards, captions, overlays, compositions | not used |

**What that means:**
- **HyperFrames is free for every Frameflow user** and already in place, so it should carry motion graphics, recipes' graphics and moving text.
- **Remotion's one unique offer is the Player:** a live, scrubbable preview inside Frameflow's React app. That is the piece Cardboard built itself on WebCodecs and WebGPU.
- **Remotion is free for you** (an individual, or a team of up to three), but not for every Frameflow user. A company of four or more using Frameflow would owe Remotion fees.
- **Remotion's licence adds restrictions GPLv3 doesn't allow.** So shipping it inside a GPLv3 app needs care: for example, an exception you add as the copyright holder, or keeping Remotion an optional install. This needs checking, not assuming.
- **A free alternative to the Player** is a lighter in-app preview: play the built preview with a timeline drawn over it, and render changed scenes quickly. That's more work but carries no licence question.

---

## 7. What it means for the order of work

To be "like Cardboard", the biggest gaps are not styles but **the agent's eyes and hands**:

1. **Eyes (new, first).**
   - Per-clip filmstrips and scene cuts at prepare.
   - A shot index the agent writes once, so shots can be searched by meaning.
   - **A look step after every build:** the agent judges a contact sheet of the real result against the plan, alongside the deterministic checks.
   - This is what made run 11's shot choice possible by hand, and what Cardboard's "look", "filmstrip" and "find scene cuts" do.
2. **Taste (piece 1, planned).** Projects, catalogs and the direction step. These are Cardboard's recipes, per creator, plus a few shipped starter recipes.
3. **Hands (piece 2).** Push-ins, punches, ramps, transitions, moving text and one-line motion graphics through HyperFrames, sound effects from a bundled free set, and ducking.
4. **Reach.** An MCP server for Frameflow, OTIO export to Resolve and Premiere, and fetching a reference from a link.
5. **The app (piece 6).** A timeline in Frameflow's window, with the Remotion question settled first.
6. **Paid, optional connectors.** Generated clips, music and voice, and Higgsfield, all behind the existing cap.
7. **Evals.** A small set of real videos re-run after engine changes, starting with run 11.
