#!/usr/bin/env python3
"""What goes beside a finished video when it is posted on YouTube.

    python -m project.publish <project.osp> --prepare
    (the agent follows publish_request.md and writes publish.json)
    python -m project.publish <project.osp> --write

The editor writes the title, description, tags and chapters; the limits are
YouTube's, checked here as its own pages give them (chapters:
support.google.com/youtube/answer/9884579; the rest: the Data API's videos
resource). A chapter starts at a moment of the recording, like a graphic, and
--write works out where that moment plays in the project as it is now. So
after any change, by hand or by Frameflow, run --write again and the chapter
times follow the cut. Uploading stays the creator's.
"""
import argparse
import json
import sys
from pathlib import Path

from project.change_agent import phrases
from project.edit import EditError, load
from project.first_cut import PlanError, _step
from project.media import MediaError
from project.operations import _plays_at, main_index
from project.validate import ValidationError, load_schema, validate

REQUEST_FILE = "publish_request.md"
PLAN_FILE = "publish.json"
PACKAGE_FILE = "publish.txt"

TITLE_MAX = 100              # characters
DESCRIPTION_MAX = 5000       # bytes of UTF-8, chapter list included
TAGS_MAX = 500               # characters, counted as tags_length counts them
CHAPTER_MIN_SECONDS = 10

GUIDANCE = """You are writing what goes beside a creator's finished video when they post it on YouTube: its title, description, tags and chapters. Write in the creator's voice, from what is said in the video below, and promise nothing the video does not deliver. Add no link the creator has not given you.

- Title: what a viewer gets from watching, in at most 100 characters.
- Description: open with the lines that make someone want to watch, then anything else worth saying. Leave out times: the chapter list is added after the description. At most 5,000 bytes with it, and no < or >.
- Tags: a few, mainly words people misspell when they search for this; YouTube says tags otherwise play a minimal role. At most 500 characters in all.
- Chapters: for a video with distinct parts, at least three. The first starts the video and takes only a title. Each later one starts where its part starts: give the first number on that line below, the moment of the recording, as `at`. Every chapter runs at least 10 seconds. A Short, or a video without distinct parts, gets no chapters: leave them out."""


def tags_length(tags: list[str]) -> int:
    """Tags as YouTube counts them: the commas between them count, and so do the
    quotation marks round a tag with a space in it."""
    return sum(len(t) + 2 * (" " in t) for t in tags) + max(len(tags) - 1, 0)


def _stamp(seconds: int, hours: bool) -> str:
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if hours else f"{m}:{s:02d}"


def _end(ir: dict) -> float:
    return max((c["timeline_start"] + c["timeline_duration"] for c in ir["tracks"][main_index(ir)]["clips"]),
               default=0.0)


def chapter_starts(chapters: list[dict], ir: dict, source: str) -> tuple[list[int], list[str]]:
    """The whole second each chapter starts at in the cut, and any chapter whose moment
    is not in it. Rounded down, so a chapter never starts after its first word."""
    main = ir["tracks"][main_index(ir)]["clips"]
    starts, problems = [0], []
    for n, chapter in enumerate(chapters[1:], start=2):
        at, problem = _plays_at(main, chapter["at"], source)
        if problem:
            problems.append(f"chapter {n} ({chapter['title']}, at {chapter['at']}s): {problem}")
        else:
            starts.append(int(at))
    return starts, problems


def description(doc: dict, ir: dict, source: str) -> str:
    """The editor's description, then the chapter list YouTube reads chapters from."""
    chapters = doc.get("chapters")
    if not chapters:
        return doc["description"].strip()
    starts, _ = chapter_starts(chapters, ir, source)
    hours = _end(ir) >= 3600
    return doc["description"].strip() + "\n\n" + "\n".join(
        f"{_stamp(s, hours)} {c['title']}" for c, s in zip(chapters, starts))


def check(doc: dict, ir: dict, source: str) -> list[str]:
    """Everything to fix before YouTube would take the package; empty if it would."""
    try:
        validate(doc, "publish")
    except ValidationError as e:
        return [str(e)]
    problems = []
    if len(doc["title"]) > TITLE_MAX:
        problems.append(f"the title is {len(doc['title'])} characters; YouTube allows {TITLE_MAX}")
    problems += [f"the {field} has < or >, which YouTube does not allow"
                 for field in ("title", "description") if set(doc[field]) & set("<>")]
    if tags_length(doc["tags"]) > TAGS_MAX:
        problems.append(f"the tags come to {tags_length(doc['tags'])} characters as YouTube counts them (the "
                        f"commas, and quotes round a tag with a space); it allows {TAGS_MAX}")
    chapters = doc.get("chapters")
    if chapters:
        starts, wrong = chapter_starts(chapters, ir, source)
        problems += wrong
        if not wrong:
            end, hours = _end(ir), _end(ir) >= 3600
            for n, (chapter, a, b) in enumerate(zip(chapters, starts, starts[1:] + [end]), start=1):
                if b - a < CHAPTER_MIN_SECONDS:
                    problems.append(f"chapter {n} ({chapter['title']}) runs {b - a:.1f}s from {_stamp(a, hours)}; "
                                    f"each chapter needs at least {CHAPTER_MIN_SECONDS}s, in the order they play")
    if not problems:
        size = len(description(doc, ir, source).encode("utf-8"))
        if size > DESCRIPTION_MAX:
            problems.append(f"the description with its chapter list is {size} bytes; YouTube allows {DESCRIPTION_MAX}")
    return problems


def package(doc: dict, ir: dict, source: str) -> str:
    """publish.txt: each part ready to paste into YouTube Studio."""
    return (f"Title\n{doc['title']}\n\nDescription\n{description(doc, ir, source)}\n\n"
            f"Tags\n{', '.join(doc['tags'])}\n")


def said_lines(ir: dict, timing: dict) -> list[str]:
    """What is said in the cut, a phrase a line in playing order: where it starts in the
    recording, where that plays in the video, and the words."""
    main = ir["tracks"][main_index(ir)]["clips"]
    hours = _end(ir) >= 3600
    lines = []
    for phrase in phrases(timing["words"]):
        heard = [(w, at) for w in phrase if (at := _plays_at(main, w["start"], timing["source"])[0]) is not None]
        if heard:
            first, at = heard[0]
            lines.append((at, f"[{first['start']:.2f}] {_stamp(int(at), hours)}  "
                              + " ".join(w["text"].strip() for w, _ in heard)))
    return [line for _, line in sorted(lines, key=lambda pair: pair[0])]


def build_request(ir: dict, timing: dict, plan_path: Path, write_command: str) -> str:
    """The request a coding agent works from to write the package."""
    return f"""# Publish request

{GUIDANCE}

## How to submit

Write the package as JSON to `{plan_path.as_posix()}`, matching the schema below, then run:

```
{write_command}
```

That checks it against YouTube's limits and the project as it is now, and writes `{PACKAGE_FILE}` beside the project. If it reports problems, fix the JSON and run it again.

## What is said in the video

{_stamp(int(_end(ir)), _end(ir) >= 3600)} long, cut from {Path(timing['source']).name}. A phrase a line, in the order they play: [seconds into the recording], where that plays in the video, then the words. Word times are estimates, so a phrase can start a moment before its number.

```
{chr(10).join(said_lines(ir, timing))}
```

## Package schema

```json
{json.dumps(load_schema("publish"), indent=2)}
```
"""


def load_package(folder: Path, ir: dict, source: str) -> dict:
    """Read the package an agent wrote, raising PlanError with everything to fix."""
    path = folder / PLAN_FILE
    if not path.exists():
        raise PlanError(f"no package at {path}; run --prepare and have your agent write it")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PlanError(f"{path} is not valid JSON: {e}") from e
    problems = check(doc, ir, source)
    if problems:
        raise PlanError(f"{path} needs fixing:\n" + "\n".join(f"  {p}" for p in problems))
    return doc


def main() -> None:
    parser = argparse.ArgumentParser(description="Write what goes beside a finished video on YouTube.")
    parser.add_argument("project", help="the finished project: an OpenShot .osp or a Shotcut .mlt")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true", help="write publish_request.md for a coding agent")
    mode.add_argument("--write", action="store_true",
                      help="check publish.json and write publish.txt from the project as it is now")
    args = parser.parse_args()

    path = Path(args.project).resolve()
    try:
        _step(f"Reading {path.name}")
        project = load(path, discard_unsupported=True)      # nothing is rewritten, so nothing can be lost
        plan = project.folder / PLAN_FILE
        if args.prepare:
            request = project.folder / REQUEST_FILE
            request.write_text(build_request(project.ir, project.timing, plan,
                                             f'python -m project.publish "{path}" --write'), encoding="utf-8")
            print(f"\nPublish request: {request}")
            print(f"Next: have your agent follow it and write {plan}, then run --write.")
            return
        doc = load_package(project.folder, project.ir, project.timing["source"])
    except (EditError, PlanError, MediaError) as e:
        sys.exit(f"\n{e}")

    text = package(doc, project.ir, project.timing["source"])
    out = project.folder / PACKAGE_FILE
    out.write_text(text, encoding="utf-8")
    print(f"\n{text}\nPublish package: {out}")


if __name__ == "__main__":
    main()
