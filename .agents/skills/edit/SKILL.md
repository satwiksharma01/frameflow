---
name: edit
description: Change a Frameflow project the user already has - including one they have edited by hand in Shotcut - acting as the editor yourself so no API key is needed. Use when the user asks to change, tighten, trim, put back, or remove something in an existing .mlt project, rather than cut a raw recording from scratch.
---

# Changing a project, with you as the editor

The first cut is made; the user may have changed it in Shotcut since. Frameflow reads the project as it is now, works out what the user changed by hand, and applies your changes without undoing theirs. You decide what to change.

1. **Prepare.** Run from the repository root, with the user's instruction in their own words:

   ```
   python -m project.edit "<project.mlt>" --prepare "<instruction>"
   ```

   If it stops because the project has things an edit would lose - filters, titles, crossfades, muted tracks - tell the user exactly what it listed and stop. Do not rerun with `--discard-unsupported` unless the user says to: it would remove their work from the project (the previous version is kept in `history/`, but they should choose that, not you).

2. **Edit.** Read `change_request.md` beside the project in full and follow it. It lists what the user changed by hand, the timeline in playing order, what was said (in or out of the cut), and the measured pauses. Write your operations to `operations.json` beside the project. Put every boundary in a measured pause. Do not undo the user's own edits unless their instruction explicitly asks; if it does, set `override_human_edit` saying which part asks.

3. **Apply.**

   ```
   python -m project.edit "<project.mlt>" --apply --open
   ```

   If it reports problems, fix `operations.json` and run it again until it succeeds. It re-reads the project each time, so if the user saved in Shotcut meanwhile, the check is against what they have now.

4. **Report.** Tell the user what changed in their words, not in seconds - which part is now out, which is back. Lead with anything you marked `"confidence": "low"`, anything the apply step flagged with `!`, and anything in their instruction you could not do with remove and restore. Say where the previous version was kept.
