#!/usr/bin/env python3
"""A creator's projects: a channel, a page or a series, each with its own catalog of video worlds.

A project lives in the git-ignored `projects/<slug>/`: `project.json` (who the creator is, their audience and the
rules they keep), an optional `brand.json` used instead of `brand/` for its videos, and `worlds/<id>.md`, one world
per file. A world file is a JSON object between two `---` lines, then seven `## ` sections (creative/world-format.md).
A dropped world moves to `worlds/dropped/`, so a drop can be undone.

    python -m project.projects new <slug> --name "<name>"
    python -m project.projects check <slug>
    python -m project.projects drop <slug> <id>
    python -m project.projects propose <slug>               (asks for about seven worlds)
    python -m project.projects from-reel <slug> <video>     (studies the reel, asks for one world from it)
    python -m project.projects from-video <slug> <folder>   (asks for one world from a video made with a direction)
"""
import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from project import beats, eyes
from project.media import probe
from project.transcribe import REPO_ROOT
from project.validate import ValidationError, validate

PROJECTS_DIR = REPO_ROOT / "projects"
SECTIONS = ("Form", "Cut", "Camera", "Type", "Grade", "Sound", "Signature move")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SUMMARY_LENGTH = 160     # the catalog index's line for a world: the first sentence of its Form, cut here


class ProjectError(Exception):
    pass


@dataclass(frozen=True)
class World:
    id: str
    front: dict
    sections: dict[str, str]
    path: Path


def _folder(slug: str) -> Path:
    """The project's folder; a slug that is not a plain name (`..`, a path) never reaches the disk."""
    if not SLUG.match(slug or ""):
        raise ProjectError(f"project {slug} is not in projects/")
    return PROJECTS_DIR / slug


def new(slug: str, name: str) -> Path:
    if not SLUG.match(slug):
        raise ProjectError(f"{slug!r} cannot name a project: lower-case letters, digits and hyphens, starting with "
                           f"a letter or digit")
    folder = PROJECTS_DIR / slug
    if folder.exists():
        raise ProjectError(f"project {slug} already exists in projects/")
    (folder / "worlds").mkdir(parents=True)
    (folder / "project.json").write_text(json.dumps({"name": name, "about": "", "audience": "", "goals": "",
                                                     "platforms": [], "commitments": []}, indent=2,
                                                    ensure_ascii=False) + "\n", encoding="utf-8")
    return folder


def load(slug: str) -> dict:
    """The project's validated project.json."""
    path = _folder(slug) / "project.json"
    if not path.is_file():
        raise ProjectError(f"project {slug} is not in projects/")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        validate(doc, "project")
    except (json.JSONDecodeError, ValidationError) as e:
        raise ProjectError(f"projects/{slug}/project.json: {e}") from None
    return doc


def parse_world(text: str) -> tuple[dict, dict[str, str]]:
    """A world file's front matter, and its sections by heading."""
    parts = re.split(r"^---[ \t]*\r?$", text, maxsplit=2, flags=re.M)
    if len(parts) < 3 or parts[0].strip():
        raise ProjectError("no front matter: the file starts with a JSON object between two --- lines")
    try:
        front = json.loads(parts[1])
    except json.JSONDecodeError as e:
        raise ProjectError(f"front matter is not JSON: {e}") from None
    if not isinstance(front, dict):
        raise ProjectError("front matter is not a JSON object")
    sections: dict[str, list[str]] = {}
    heading = None
    for line in parts[2].splitlines():
        found = re.match(r"^## (.+?)\s*$", line)
        if found:
            heading = found.group(1)
            sections[heading] = []
        elif heading is not None:
            sections[heading].append(line)
    return front, {h: "\n".join(lines).strip() for h, lines in sections.items()}


def world_problems(file_id: str, text: str) -> list[str]:
    """Everything wrong with one world file, each naming the file."""
    try:
        front, sections = parse_world(text)
    except ProjectError as e:
        return [f"{file_id}: {e}"]
    problems = []
    try:
        validate(front, "world")
    except ValidationError as e:
        problems.append(f"{file_id}: {e}")
    if front.get("id") != file_id:
        problems.append(f"{file_id}: its id is {front.get('id')!r}, but it must be the file's name, {file_id!r}")
    problems += [f"{file_id}: the {s} section is missing or empty" for s in SECTIONS if not sections.get(s)]
    return problems


def _world_files(slug: str) -> list[Path]:
    return sorted((_folder(slug) / "worlds").glob("*.md"), key=lambda p: p.stem)


def worlds(slug: str) -> list[World]:
    """The project's worlds, sorted by id; any file with a problem stops it, named."""
    load(slug)
    found, problems = [], []
    for path in _world_files(slug):
        text = path.read_text(encoding="utf-8")
        wrong = world_problems(path.stem, text)
        if wrong:
            problems += wrong
            continue
        front, sections = parse_world(text)
        found.append(World(path.stem, front, sections, path))
    if problems:
        raise ProjectError(f"projects/{slug}/worlds needs fixing:\n" + "\n".join(f"  {p}" for p in problems))
    return found


def check(slug: str) -> list[str]:
    """Every problem in the project, without stopping at the first."""
    try:
        load(slug)
        problems = []
    except ProjectError as e:
        problems = [str(e)]
        if not (PROJECTS_DIR / slug).is_dir() or not SLUG.match(slug):
            return problems
    for path in _world_files(slug):
        problems += world_problems(path.stem, path.read_text(encoding="utf-8"))
    return problems


def _first_sentence(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0]
    return first if len(first) <= SUMMARY_LENGTH else first[:SUMMARY_LENGTH - 1] + "…"


def index(slug: str) -> str:
    """The catalog in one line per world: what a request carries instead of the worlds themselves."""
    lines = [f"- `{w.id}` · {w.front['name']} · {w.front['family']}: {_first_sentence(w.sections['Form'])}"
             for w in worlds(slug)]
    return "\n".join(lines) or "(no worlds yet)"


def digest(slug: str | None) -> str:
    """A fingerprint of the catalog, for the roll's seed: it changes when any world file does."""
    if slug is None:
        return ""
    h = hashlib.sha256()
    for path in _world_files(slug):
        h.update(path.stem.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def drop(slug: str, world_id: str) -> Path:
    """Move a world aside to worlds/dropped/, never over an earlier drop."""
    load(slug)
    source = _folder(slug) / "worlds" / f"{world_id}.md"
    if not SLUG.match(world_id) or not source.is_file():
        raise ProjectError(f"{world_id} is not a world in projects/{slug}/worlds/")
    dropped = source.parent / "dropped"
    dropped.mkdir(exist_ok=True)
    target, n = dropped / source.name, 2
    while target.exists():
        target, n = dropped / f"{world_id}-{n}.md", n + 1
    source.rename(target)
    return target


def brand_file(slug: str | None) -> Path | None:
    """The project's own brand kit, when it has one."""
    if slug is None or not SLUG.match(slug):
        return None
    path = PROJECTS_DIR / slug / "brand.json"
    return path if path.is_file() else None


def _worlds_request(slug: str, intro: str, ask: str) -> Path:
    """The request for new worlds: the project and its catalog's index, never the worlds themselves."""
    project, folder = load(slug), _folder(slug)
    path = folder / "worlds_request.md"
    path.write_text(f"""# New worlds for {project['name']}

{intro}

## The project

```json
{json.dumps(project, indent=2, ensure_ascii=False)}
```

## Its catalog now

{index(slug)}

## How

- Read `creative/world-format.md` first: the file format, the six families and a complete example. Then
  `creative/calibration.md`: what AI-made video always does, which no world may fall back on.
{ask}
- Write each world to `{(folder / "worlds").as_posix()}/<id>.md`, its id the file's name, in Frameflow's own words.
  References are links or paths, never copied media.
- Then run `python -m project.projects check {slug}` and fix what it reports.
""", encoding="utf-8")
    return path


def propose(slug: str) -> Path:
    """Ask for the project's first worlds, dug from its audience's culture."""
    return _worlds_request(slug, "Propose worlds for this project's catalog, for the creator to keep or drop.", """\
- Dig about seven worlds from the project's audience and their culture: where they already look, what they collect,
  the places and rituals they know. Use at least three families; at most one may take the project's own subject
  literally; none may be built from the creator's own tools of the trade (a camera, a timeline, a ring light).
- Each is a working system, not a costume: it gives the videos disciplines, never a filter.
- Each world's front matter has `"source": "proposed"`.""")


def from_reel(slug: str, video: Path) -> Path:
    """Study a reel the creator points at (its frames, cuts and tempo), and ask for one world from it."""
    load(slug)
    video = Path(video)
    if not video.is_file():
        raise ProjectError(f"not found: {video}")
    out = _folder(slug) / "reels" / video.stem
    try:
        eyes.study(video, out)
    except eyes.EyesError as e:
        raise ProjectError(str(e)) from None
    tempo = None
    if any(s.get("codec_type") == "audio" for s in probe(video).get("streams", [])):
        times = beats.beats(video)
        tempo = {"bpm": round(beats.tempo(times), 1) if len(times) > 1 else None,
                 "beats": [round(t, 3) for t in times]}
        (out / "tempo.json").write_text(json.dumps(tempo) + "\n", encoding="utf-8")
    sound = (f"`{(out / 'tempo.json').as_posix()}`: its music's beats and tempo" if tempo is not None
             else "it has no sound")
    return _worlds_request(slug, f"The creator wants a world from a reel they pointed at: `{video.resolve().as_posix()}`.", f"""\
- Frameflow studied the reel. Open `{(out / eyes.SHEET).as_posix()}`, its frames with each one's time, and read
  `{(out / eyes.STUDY).as_posix()}`: where it cuts, how sharp and bright it is; and {sound}.
- Write **one** world from what the reel does: how long its shots are and what its cuts land on, how it frames,
  where its type sits and how it behaves, its grade, its sound, and its one signature move. Describe the system,
  so it can carry videos that are not this reel; never copy its content.
- Its front matter has `"source": "reel"` and `"references": ["{video.resolve().as_posix()}"]`.""")


def from_video(slug: str, folder: Path) -> Path:
    """Ask for one world from a video the creator made with a direction and liked."""
    load(slug)
    folder = Path(folder)
    missing = [n for n in ("direction.json", "storyboard.json") if not (folder / n).is_file()]
    if missing:
        raise ProjectError(f"{folder} has no {' or '.join(missing)}: a world comes from a video made with a direction")
    return _worlds_request(slug, f"The creator liked a video they made, `{folder.resolve().as_posix()}`, and wants its "
                                 f"look as a world for this project.", f"""\
- Read the direction it was made with, `{(folder / 'direction.json').resolve().as_posix()}`, and the storyboard as
  built, `{(folder / 'storyboard.json').resolve().as_posix()}`.
- Write **one** world from what was built: the system behind it, so it can carry the project's next videos.
- Its front matter has `"source": "video"` and `"references": ["{folder.resolve().as_posix()}"]`.""")


def main() -> None:
    parser = argparse.ArgumentParser(description="A creator's projects and their catalogs of video worlds.")
    command = parser.add_subparsers(dest="command", required=True)
    made = command.add_parser("new", help="make a project to fill in with the creator")
    made.add_argument("slug")
    made.add_argument("--name", required=True)
    checked = command.add_parser("check", help="check the project and print its catalog")
    checked.add_argument("slug")
    dropped = command.add_parser("drop", help="move a world aside to worlds/dropped/")
    dropped.add_argument("slug")
    dropped.add_argument("id")
    proposed = command.add_parser("propose", help="ask for about seven worlds from the project's audience")
    proposed.add_argument("slug")
    reel = command.add_parser("from-reel", help="study a reel and ask for one world from it")
    reel.add_argument("slug")
    reel.add_argument("video", type=Path)
    video = command.add_parser("from-video", help="ask for one world from a video made with a direction")
    video.add_argument("slug")
    video.add_argument("folder", type=Path)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):     # a world can hold any script; Windows' code page cannot
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        if args.command in ("propose", "from-reel", "from-video"):
            path = {"propose": lambda: propose(args.slug), "from-reel": lambda: from_reel(args.slug, args.video),
                    "from-video": lambda: from_video(args.slug, args.folder)}[args.command]()
            print(f"Next: read {path}")
        elif args.command == "new":
            folder = new(args.slug, args.name)
            print(f"Made {folder}\nNext: fill in {folder / 'project.json'} with the creator.")
        elif args.command == "check":
            problems = check(args.slug)
            if problems:
                sys.exit("\n".join(problems))
            print(index(args.slug))
        else:
            print(f"Dropped: {drop(args.slug, args.id)}")
    except ProjectError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
