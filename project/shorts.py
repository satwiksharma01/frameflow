#!/usr/bin/env python3
"""Cut short vertical videos from one long recording.

    prepare: video -> transcript + measured pauses, as for a first cut
                   -> shorts_request.md
    pick:    an editor picks the moments that stand on their own
    build:   shorts_plan.json, checked -> each moment a first cut of its own,
             vertical and captioned, in short-1/, short-2/, ...

Each short goes through the whole first-cut build: cut points placed in
measured pauses, the crop framed on the face, captions, and every cut listened
to. A coding agent you already run (Claude Code, OpenCode, ...) is the editor,
as in first_cut's agent mode.

    python -m project.shorts <video> --prepare [--count 3] [--brief "..."]
    python -m project.shorts <video> --build
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from project import first_cut
from project.editor_agent import NoSpeechError, build_user_prompt, check_plan
from project.first_cut import PlanError
from project.hyperframes import HyperFramesError
from project.media import MediaError
from project.openshot_template import ProfileError
from project.transcribe import TranscriptionError
from project.validate import ValidationError, load_schema, validate

REQUEST_FILE = "shorts_request.md"
PLAN_FILE = "shorts_plan.json"

GUIDANCE = """You are the editor for Frameflow, cutting short vertical videos - Reels, Shorts, TikToks - from one long recording by a creator. Pick {count} moments that each stand on their own: someone who has seen nothing else of the recording understands it and gets something from it, such as a tip, a story with its payoff, or a strong opinion.

- Open on the hook. The first two seconds decide whether someone keeps watching, so start on a line that grabs: a claim, a question, a surprise. Never start mid-sentence, or on a line that leans on what came before ("so", "and that's why", "like I said").
- End on the payoff, at the end of a sentence, not trailing into the next thought.
- Aim for 20 to 60 seconds each, after removals.
- Inside a moment, remove what a first cut would: false starts, repeated takes (keep the best, usually the last complete one) and long pauses. Keep the rest.
- Moments do not overlap.
- Start and end each moment, and each removal, inside a measured silence. Transcript segments absorb neighbouring pauses, so their boundaries are not cut points. The build moves each cut into the nearest measured pause.
- If fewer than {count} moments stand on their own, pick fewer and say why in `reasoning`. A weak short is worse than none."""


def build_request(transcript: dict, count: int, brief: str | None, plan_path: Path, build_command: str) -> str:
    """The request a coding agent works from to pick the shorts."""
    return f"""# Frameflow shorts request

{GUIDANCE.format(count=count)}

## How to submit

Write the plan as JSON to `{plan_path.as_posix()}`, matching the schema below, then run:

```
{build_command}
```

That checks the plan and builds one editable project per short. If it reports errors, fix the plan and run it again.

## Recording

{build_user_prompt(transcript, brief or "none given - pick the strongest moments")}

## Shorts plan schema

```json
{json.dumps(load_schema("shorts_plan"), indent=2)}
```
"""


def edit_plan(short: dict, duration: float) -> dict:
    """The short as a first cut of the whole recording: everything outside the
    moment removed, and whatever the editor removed inside it."""
    removes = [{"start": 0.0, "end": short["start"], "reason": "before this short"},
               *short.get("remove", []),
               {"start": short["end"], "end": duration, "reason": "after this short"}]
    decisions, at = [], 0.0
    for r in removes:
        if r["end"] <= r["start"]:
            continue
        if r["start"] > at:
            decisions.append({"action": "keep", "start": at, "end": r["start"], "reason": f"the short: {short['title']}"})
        decisions.append({"action": "remove", **r})
        at = r["end"]
    if at < duration:
        decisions.append({"action": "keep", "start": at, "end": duration, "reason": f"the short: {short['title']}"})
    return {"source_duration_seconds": duration, "reasoning": short["reason"], "decisions": decisions}


def check_shorts(plan: dict, transcript: dict) -> list[str]:
    """Everything the editor needs to fix, each named with its short; empty if the plan is accepted."""
    try:
        validate(plan, "shorts_plan")
    except ValidationError as e:
        return [str(e)]

    duration = transcript["duration_seconds"]
    problems = []
    for n, short in enumerate(plan["shorts"], 1):
        mistakes = []
        if not short["start"] < short["end"] <= duration:
            mistakes.append(f"runs {short['start']}-{short['end']}s; it must end after it starts, "
                            f"and by the end of the {duration}s recording")
        at = short["start"]
        for r in short.get("remove", []):
            if not at <= r["start"] < r["end"] <= short["end"]:
                mistakes.append(f"removal {r['start']}-{r['end']}s must lie inside the short, "
                                f"after the removal before it")
            at = r["end"]
        if not mistakes:                       # the cut it makes is only worth checking once it is well formed
            mistakes = check_plan(edit_plan(short, duration), transcript)
        problems += [f"short {n} ({short['title']}): {m}" for m in mistakes]
    return problems


def load_plan(out_dir: Path, transcript: dict) -> dict:
    """Read the shorts plan an agent wrote, raising PlanError with everything to fix."""
    path = out_dir / PLAN_FILE
    if not path.exists():
        raise PlanError(f"no shorts plan at {path}; write it first (see {out_dir / REQUEST_FILE})")
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PlanError(f"{path} is not valid JSON: {e}") from e
    problems = check_shorts(plan, transcript)
    if problems:
        raise PlanError(f"{path} needs fixing:\n" + "\n".join(problems))
    return plan


def build(video: Path, out_dir: Path, plan: dict, verify: bool = True) -> list[Path]:
    """Build each short as a vertical, captioned first cut in its own folder."""
    duration = json.loads((out_dir / first_cut.TRANSCRIPT_FILE).read_text(encoding="utf-8"))["duration_seconds"]
    projects = []
    for n, short in enumerate(plan["shorts"], 1):
        first_cut._step(f"Short {n} of {len(plan['shorts'])}: {short['title']}")
        folder = out_dir / f"short-{n}"
        folder.mkdir(exist_ok=True)
        for name in (first_cut.TRANSCRIPT_FILE, first_cut.TIMING_FILE):
            shutil.copy(out_dir / name, folder / name)
        # ponytail: each short finds the face over the whole recording again (~7s per 5 min); cache it if that adds up.
        projects.append(first_cut.build(video, folder, edit_plan(short, duration), verify=verify,
                                        captions=True, vertical=True, name=f"{video.stem}-short-{n}"))
    return projects


def main() -> None:
    parser = argparse.ArgumentParser(description="Cut short vertical videos from one long recording.")
    parser.add_argument("video")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true",
                      help="transcribe and write shorts_request.md for a coding agent")
    mode.add_argument("--build", action="store_true",
                      help="check shorts_plan.json and build one OpenShot project per short")
    parser.add_argument("--count", type=int, default=3, help="how many shorts to look for (default: 3)")
    parser.add_argument("--brief", help="what the shorts are for, e.g. 'only the money tips'")
    parser.add_argument("--language", default="auto", help="spoken language code, or 'auto'")
    parser.add_argument("--out", help="output folder (default: output/<video name>)")
    parser.add_argument("--no-verify", action="store_true",
                        help="skip listening to each cut and looking at the picture (faster, but a clipped word "
                             "or a black frame can slip through)")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"no such file: {video}")
    out_dir = Path(args.out) if args.out else first_cut.REPO_ROOT / "output" / video.stem

    try:
        if args.prepare:
            transcript = first_cut.prepare(video, out_dir, args.language)
            command = " ".join(["python", "-m", "project.shorts", f'"{video}"', "--build",
                                *(["--out", f'"{args.out}"'] if args.out else [])])
            request = out_dir / REQUEST_FILE
            request.write_text(build_request(transcript, args.count, args.brief, out_dir / PLAN_FILE, command),
                               encoding="utf-8")
            print(f"\nShorts request: {request}")
            print(f"Next: have your agent follow it and write {out_dir / PLAN_FILE}, then run --build.")
            return

        transcript_path = out_dir / first_cut.TRANSCRIPT_FILE
        if not transcript_path.exists():
            sys.exit(f"no transcript at {transcript_path}; run with --prepare first")
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        projects = build(video, out_dir, load_plan(out_dir, transcript), verify=not args.no_verify)
    except (NoSpeechError, PlanError, MediaError, TranscriptionError, ProfileError, HyperFramesError) as e:
        sys.exit(f"\nStopped: {e}\nIntermediate files are in {out_dir}")

    print("\nShorts:")
    for project in projects:
        print(f"  {project}")


if __name__ == "__main__":
    main()
