---
name: first-cut
description: Make a first cut of a raw video recording with Frameflow, acting as the editor yourself so no API key is needed. Use when the user asks to edit, cut, trim, or make a first cut of a video file in this repository.
---

# First cut, with you as the editor

Frameflow handles the mechanical work (frame-rate normalization, transcription, silence measurement, validation, building the Shotcut project). You make the editorial decisions.

1. **Prepare.** Run from the repository root:

   ```
   python -m project.first_cut "<video>" --prepare [--brief "<what the user wants>"]
   ```

   If it stops with "no usable speech", tell the user the measured numbers from the message and stop — there is nothing to edit, and the likely cause is the recording's microphone input.

2. **Edit.** Read `output/<video name>/edit_request.md` in full and follow it. It contains the editing guidance, the transcript, the measured silences, and the plan schema. Decide keep or remove for every span and write the plan to `output/<video name>/edit_plan.json`. Place cut points inside measured silences; the transcript's segment boundaries include surrounding pauses and are not cut points.

3. **Build.**

   ```
   python -m project.first_cut "<video>" --build --open
   ```

   If it reports problems with the plan, fix `edit_plan.json` and run the build again until it succeeds.

4. **Report.** Tell the user the kept duration against the original, and list each removed span with its reason, so they know what to review in Shotcut. Flag any decisions you were unsure about.
