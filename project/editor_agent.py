#!/usr/bin/env python3
"""The editing agent: transcript + measured silences in, validated edit plan out.

Provider-agnostic. The model submits its plan through a single tool; our own
validator is the source of truth for whether the plan is acceptable, and its
errors go back to the model to fix. Compiling the accepted plan into a project
is deterministic code afterwards - the model never touches project files.

Usage:
    python -m project.editor_agent <transcript.json> [-o edit_plan.json] [--brief "..."]
"""
import argparse
import json
from pathlib import Path

from project.providers import Provider, ToolSpec, get_provider
from project.validate import ValidationError, load_schema, validate

TOOL_NAME = "submit_edit_plan"

# A kept span shorter than this is a sliver, not an edit, and can round to zero
# frames at compile time. Catch it here, where the model can still fix it.
MIN_KEEP_SECONDS = 0.1

# Below this much audible audio there is nothing to edit, and Whisper fills
# silence with stock phrases ("Thank you.") that would otherwise be sent to a
# paid model as if they were speech.
MIN_AUDIBLE_SECONDS = 3.0


class NoSpeechError(Exception):
    pass


def audible_seconds(transcript: dict) -> float:
    silent = sum(min(s["end"], transcript["duration_seconds"]) - s["start"]
                 for s in transcript.get("silences") or [])
    return max(0.0, transcript["duration_seconds"] - silent)

# Shared by both ways of running the editor: a model called through an API
# (tool mode), and a coding agent such as Claude Code reading a request file
# (agent mode). Only the submission instructions differ.
EDITOR_GUIDANCE = """You are the editor for Frameflow, making the first cut of a creator's raw recording. For one source video you receive a timestamped transcript and the silences measured from its audio, and you decide which spans to keep and which to remove.

Cut what a skilled human editor would cut from a talking-head or screen recording: dead air and long pauses, false starts, abandoned or repeated takes of the same line (keep the best take, usually the last complete one), and filler. Keep the substance, and keep the pacing natural: shorten long pauses rather than removing every breath, leaving roughly a quarter of a second of silence around speech. Short pauses inside a sentence belong to the speech; leave them.

Place cut points using the measured silences, not the transcript's segment boundaries. Transcript segments absorb neighbouring pauses, so a segment can begin seconds before its first word. A cut between two sentences belongs inside the silence that separates them.

When you are unsure about a decision, set its `confidence` to "low" and say what the doubt is in the reason. Default to keeping what you are unsure about: "kept: possibly a repeated take" is more useful than a confident wrong cut. Mark an uncertain removal "low" as well - the creator can see everything you kept, but what you cut is no longer in front of them, so a doubtful cut is the decision they most need pointed out.

The decisions must cover the whole source from 0 to its duration, in order, with no gaps or overlaps, so every second is explicitly kept or removed."""

SYSTEM_PROMPT = EDITOR_GUIDANCE + """

Submit your plan by calling submit_edit_plan. If the tool reports errors, correct them and submit again."""

TOOL_DESCRIPTION = (
    "Submit the complete edit plan for this source video. Call it once every span from 0 "
    "to the source duration has a keep or remove decision. The plan is validated; if anything "
    "is wrong you get specific errors back to fix before resubmitting."
)


def build_tool() -> ToolSpec:
    schema = load_schema("edit_plan")
    for key in ("$schema", "$id", "title", "description"):
        schema.pop(key, None)
    return ToolSpec(name=TOOL_NAME, description=TOOL_DESCRIPTION, input_schema=schema)


def build_user_prompt(transcript: dict, brief: str | None = None) -> str:
    lines = [
        f"Source duration: {transcript['duration_seconds']} seconds",
        f"Language: {transcript.get('language', 'unknown')}",
        "",
        f"Creator's brief: {brief.strip() if brief else 'none given - make a clean first cut'}",
        "",
        "Transcript segments (boundaries often include neighbouring silence):",
    ]
    lines += [f"[{s['start']:.2f}-{s['end']:.2f}] {s['text']}" for s in transcript["segments"]]
    lines += ["", "Measured silences (from the audio; place cut points inside these):"]
    silences = transcript.get("silences") or []
    lines += [f"[{s['start']:.2f}-{s['end']:.2f}]" for s in silences] or ["none detected"]
    return "\n".join(lines)


def check_plan(plan: dict, transcript: dict) -> list[str]:
    """Everything the model needs to fix, or an empty list if the plan is accepted."""
    try:
        validate(plan, "edit_plan")
    except ValidationError as e:
        return [str(e)]

    problems = []
    expected = transcript["duration_seconds"]
    if abs(plan["source_duration_seconds"] - expected) > 0.05:
        problems.append(
            f"source_duration_seconds is {plan['source_duration_seconds']} but the source is {expected} seconds"
        )
    for i, d in enumerate(plan["decisions"]):
        if d["action"] == "keep" and d["end"] - d["start"] < MIN_KEEP_SECONDS:
            problems.append(
                f"decision {i}: keeps only {d['end'] - d['start']:.3f}s ({d['start']}-{d['end']}); "
                f"kept spans must be at least {MIN_KEEP_SECONDS}s - merge it into a neighbour or remove it"
            )
    return problems


def ensure_speech(transcript: dict) -> None:
    """Raise NoSpeechError rather than send silence to an editor."""
    validate(transcript, "transcript")
    audible = audible_seconds(transcript)
    if not transcript["segments"] or audible < MIN_AUDIBLE_SECONDS:
        raise NoSpeechError(
            f"no usable speech: {audible:.1f}s of the {transcript['duration_seconds']}s recording is "
            f"above the silence threshold and {len(transcript['segments'])} speech segment(s) were "
            f"found. Check the recording's microphone input before editing."
        )


def build_agent_request(transcript: dict, brief: str | None, plan_path: Path,
                        build_command: str) -> str:
    """The edit request a coding agent (Claude Code, OpenCode, ...) works from.

    Same guidance, same inputs and same validation as tool mode; the agent
    writes the plan to a file and runs the build step, which reports any errors
    for it to fix.
    """
    schema = json.dumps(build_tool().input_schema, indent=2)
    return f"""# Frameflow edit request

{EDITOR_GUIDANCE}

## How to submit

Write the plan as JSON to `{plan_path.as_posix()}`, matching the schema below, then run:

```
{build_command}
```

That validates the plan and builds the Shotcut project. If it reports errors, fix the plan and run it again.

## Recording

{build_user_prompt(transcript, brief)}

## Edit plan schema

```json
{schema}
```
"""


def propose_edit_plan(transcript: dict, provider: Provider, brief: str | None = None,
                      max_attempts: int = 4) -> dict:
    ensure_speech(transcript)
    return provider.submit(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(transcript, brief),
        tool=build_tool(),
        check=lambda plan: check_plan(plan, transcript),
        max_attempts=max_attempts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Have a model propose an edit plan for a transcript.")
    parser.add_argument("transcript")
    parser.add_argument("-o", "--output", help="write the edit plan here instead of stdout")
    parser.add_argument("--brief", help="what the creator wants from this cut")
    parser.add_argument("--provider", help="anthropic (default) or openai")
    parser.add_argument("--model")
    parser.add_argument("--base-url", help="OpenAI-compatible endpoint URL")
    args = parser.parse_args()

    transcript = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    provider = get_provider(args.provider, args.model, args.base_url)
    plan = propose_edit_plan(transcript, provider, args.brief)
    text = json.dumps(plan, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output} (served by {provider.served_by})")
    else:
        print(text)


if __name__ == "__main__":
    main()
