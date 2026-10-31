---
name: shorts
description: Cut several short vertical videos (Reels, Shorts, TikToks, clips) from one long recording with Frameflow, acting as the editor yourself so no API key is needed. Use when the user asks for shorts, reels, clips or highlights from a longer video, rather than one cut of the whole recording (first-cut).
---

# Shorts from one long recording, with you as the editor

Frameflow handles the mechanical work (transcription, measuring pauses, placing cuts, framing the face, captions, listening to every cut). You pick the moments.

1. **Prepare.** Run from the repository root, with `--count` set to how many shorts the user wants (3 if they don't say):

   ```
   python -m project.shorts "<video>" --prepare --count 3 [--brief "<what the shorts are for>"]
   ```

   If it stops with "no usable speech", tell the user the measured numbers from the message and stop.

2. **Pick.** Read `output/<video name>/shorts_request.md` in full and follow it. Put every start, end and removal inside a measured silence. Whisper's word timings drift on long recordings, so when a cut depends on exactly which word comes after a pause, transcribe just that slice to check. Write the plan to `output/<video name>/shorts_plan.json`.

3. **Build.**

   ```
   python -m project.shorts "<video>" --build
   ```

   If it reports problems with the plan, fix `shorts_plan.json` and run it again until it succeeds.

4. **Report.** For each short: its title, its length, its opening line, and the project's path. Say which hook is weakest, and anything the build flagged: a cut with no pause near it, or a join that doesn't sound clean.
