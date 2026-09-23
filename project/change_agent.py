#!/usr/bin/env python3
"""The editor for changes to an existing project (Phase 7a).

The counterpart of editor_agent.py, which makes first cuts. A first cut sees
the whole recording and decides every second; a change sees the cut the
creator has now - including anything they did in Shotcut - and makes only the
change they asked for, as operations (see operations.py).

What the editor is shown, and why:

  - The instruction, and what the creator changed by hand since Frameflow
    last wrote the project: their edits win, so the editor needs to know them.
  - The timeline in playing order, which may differ from recording order once
    a human has been at it.
  - What was said, marked in or out of the cut, with source times.
    Operations are addressed in source seconds, and "put back the part about
    pricing" needs the removed material to be visible too.

Text and timing come from different places, on purpose. Whisper's word
timestamps are interpolated, not measured: across a 3.9s silence it spread
"Today I want to show you how to, um." evenly, timing "Today" four seconds
before it was spoken. So the transcript is shown as phrases for what was
said, and the measured pauses are listed separately as where cuts can go -
the same split that made the first cut work (finding 4).
"""
import json
from pathlib import Path

from project.operations import main_index
from project.providers import Checker, Provider, ToolSpec
from project.reconcile import HumanChanges, source_key
from project.validate import load_schema

TOOL_NAME = "submit_operations"

# Pauses at least this long are listed for the editor. Shorter ones are the
# gaps inside a sentence, which the first cut's guidance says to leave alone.
LISTED_PAUSE_SECONDS = 0.3
PHRASE_MAX_WORDS = 20

CHANGE_GUIDANCE = """You are the editor for Frameflow, changing a creator's video project that already has a first cut. The creator may have edited it by hand in Shotcut since. Make the change their instruction asks for, and nothing else.

You change the cut with two operations on spans of the recording, given in seconds into the recording as the transcript below shows them. `remove` takes a span out of the cut. `restore` puts a span of the recording back, in recording order. Code works out which clips that trims, splits or joins.

The transcript tells you what was said, but its times are Whisper's estimates: a phrase's words may have been spoken anywhere between the measured pauses around it. The measured pauses are exact. Put every boundary in a measured pause - to remove a phrase, start the span in the pause before it and end it in the pause after it. Code then places each boundary precisely inside its pause.

The creator's own edits win. Do not restore what they removed, or remove what they put back, unless the instruction explicitly asks for that; when it does, set override_human_edit and say which part of the instruction asks. Any other operation that would undo their edit is rejected.

Change only what the instruction asks for. If it is ambiguous, make the smallest reasonable change, set "confidence": "low" and put the doubt in the reason. If part of it cannot be done by removing and restoring - reordering, effects, B-roll, captions - do the part that can be done and say in the summary what was left undone. If nothing should change, submit no operations and explain why in the summary."""

SYSTEM_PROMPT = CHANGE_GUIDANCE + """

Submit by calling submit_operations. If the tool reports errors, correct them and submit again."""

TOOL_DESCRIPTION = (
    "Submit the operations that make the creator's requested change. They are checked against "
    "the project as it is on disk; if anything is wrong you get specific errors back to fix "
    "before resubmitting."
)


def build_tool() -> ToolSpec:
    schema = load_schema("operations")
    for key in ("$schema", "$id", "title", "description"):
        schema.pop(key, None)
    return ToolSpec(name=TOOL_NAME, description=TOOL_DESCRIPTION, input_schema=schema)


def _clock(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}:{rest:05.2f}"


def _in_cut(start: float, end: float, kept: list[tuple[float, float]]) -> float:
    """How much of [start, end) is in the cut, in seconds."""
    return sum(max(0.0, min(end, b) - max(start, a)) for a, b in kept)


def phrase_lines(words: list[dict], kept: list[tuple[float, float]]) -> list[str]:
    """What was said, as phrases marked in the cut (+), out of it (-), or partly (~).

    Phrases end at sentence punctuation. Their times are Whisper's and only
    approximate, which is why a phrase can be marked ~ - a cut boundary lies
    somewhere inside it, as far as those times can tell.
    """
    phrases, current = [], []
    for word in sorted(words, key=lambda w: w["start"]):
        current.append(word)
        if word["text"].rstrip().endswith((".", "?", "!")) or len(current) >= PHRASE_MAX_WORDS:
            phrases.append(current)
            current = []
    if current:
        phrases.append(current)

    lines = []
    for phrase in phrases:
        start, end = phrase[0]["start"], phrase[-1]["end"]
        share = _in_cut(start, end, kept) / (end - start) if end > start else 0.0
        mark = "+" if share > 0.9 else "-" if share < 0.1 else "~"
        lines.append(f"{mark} [{start:.2f}-{end:.2f}] {' '.join(w['text'].strip() for w in phrase)}")
    return lines


def pause_lines(pauses: list[dict], kept: list[tuple[float, float]]) -> list[str]:
    """Measured pauses long enough to cut in, and how much of each the cut plays."""
    lines = []
    for pause in sorted(pauses, key=lambda p: p["start"]):
        length = pause["end"] - pause["start"]
        if length < LISTED_PAUSE_SECONDS:
            continue
        played = _in_cut(pause["start"], pause["end"], kept)
        state = ("in the cut" if played > length - 0.01 else "not in the cut" if played < 0.01
                 else f"{played:.2f}s of it in the cut")
        lines.append(f"[{pause['start']:.2f}-{pause['end']:.2f}] {length:.2f}s, {state}")
    return lines


def build_context(instruction: str, ir: dict, changes: HumanChanges, timing: dict) -> str:
    """Everything the editor needs to make one change, shared by agent and API mode."""
    track = ir["tracks"][main_index(ir)]
    clips = sorted(track["clips"], key=lambda c: c["timeline_start"])
    total = max((c["timeline_start"] + c["timeline_duration"] for c in clips), default=0.0)
    recording = source_key(timing["source"])
    words = timing["words"]

    def opens_with(clip: dict) -> str:
        """Roughly - word times are estimates, so this can be a phrase off."""
        if source_key(clip["source"]) != recording:
            return "(no transcript for this recording)"
        inside = [w["text"].strip() for w in words
                  if clip["source_in"] <= (w["start"] + w["end"]) / 2 < clip["source_out"]]
        return " ".join(inside[:8]) + (" ..." if len(inside) > 8 else "")

    kept = [(c["source_in"], c["source_out"]) for c in clips if source_key(c["source"]) == recording]
    parts = [
        f"## Instruction from the creator\n\n{instruction.strip()}",
        "## What the creator changed in the editor since Frameflow last wrote this project\n\n"
        + "\n".join(f"- {line}" for line in changes.lines()),
        f"## The timeline now\n\nMain track {track['id']}: {len(clips)} clips, {_clock(total)} long, "
        f"in playing order.\n\n| # | plays at | recording (seconds) | opens with |\n|---|---|---|---|\n"
        + "\n".join(f"| {n} | {_clock(c['timeline_start'])}-{_clock(c['timeline_start'] + c['timeline_duration'])}"
                    f" | {Path(c['source']).name} {c['source_in']:.2f}-{c['source_out']:.2f} | {opens_with(c)} |"
                    for n, c in enumerate(clips, start=1)),
        f"## What was said\n\n{Path(timing['source']).name}, {timing['duration_seconds']:.2f}s. "
        f"Phrases marked + are in the cut, - are not, ~ are partly in it. Times are seconds into "
        f"the recording but only approximate - use the pauses below for boundaries.\n\n```\n"
        + "\n".join(phrase_lines(words, kept)) + "\n```",
        f"## Measured pauses of {LISTED_PAUSE_SECONDS}s or more\n\nExact, in seconds into the "
        f"recording. Every operation boundary belongs inside one of these.\n\n```\n"
        + "\n".join(pause_lines(timing["pauses"], kept)) + "\n```",
    ]
    others = [t for i, t in enumerate(ir["tracks"]) if i != main_index(ir) and t["clips"]]
    if others:
        parts.append("## Other tracks\n\n" + "\n".join(
            f"- {t['id']} ({t['type']}): {len(t['clips'])} clip(s). Operations do not touch these, "
            f"and they keep their positions when the main track changes." for t in others))
    return "\n\n".join(parts)


def build_agent_request(context: str, operations_path: Path, apply_command: str) -> str:
    schema = json.dumps(build_tool().input_schema, indent=2)
    return f"""# Change request

{CHANGE_GUIDANCE}

Write the operations as JSON to `{operations_path.as_posix()}`, matching the schema at the end, then run:

```
{apply_command}
```

It checks the operations against the project as it is on disk right now and reports every problem. Fix them and run it again until it succeeds.

{context}

## Operations schema

```json
{schema}
```
"""


def propose_operations(context: str, provider: Provider, check: Checker,
                       max_attempts: int = 4) -> dict:
    return provider.submit(system=SYSTEM_PROMPT, user=context, tool=build_tool(),
                           check=check, max_attempts=max_attempts)
