"""The plan, meaning the brief, written by a thinker from the creator's prompt and material.

Frameflow drives each step: it prepares the material, sends the thinker the request it already writes for
a brief, and checks the answer against the brief schema and check_brief's rules, each fact's page opened
for its quote (and again on Approve); the pages it cannot open are kept in `app_cache/plan_unopened.json`
for the app to mark. The creator then changes the plan by hand or in words, and answers or removes its open
questions. It stays a draft, `plan_draft.json`, until Approve: nothing is written to `brief.json` before
then, so a build in between never mixes a new plan with an old storyboard.

The app runs each step that thinks as a job, with the thinker its environment names (see `thinkers`):

    python -m project.app_think start FOLDER --prompt P [--footage F ...] [--asset F ...] [--music F ...]
                                             [--look F ...] [--script F] [--shape 9:16|16:9|1:1]
    python -m project.app_think plan-change FOLDER --words W
    python -m project.app_think answer FOLDER --question N --words W
    python -m project.app_think approve FOLDER
    python -m project.app_think change FOLDER --words W --version V
    python -m project.app_think test

Each prints its steps as `==> ` lines and its details indented four spaces, as a build does, and exits 0.
`approve` and `change` end with what the app reads, one line of `==> Done ` and a JSON object:
`{"storyboard"}`, its path, and `{"summary", "notes"}`. `test` prints `Ready: <the thinker's name>`.
A failure is one plain line on stderr, with the key taken out, and exit 1; or exit 3 (`EXIT_CHANGED`) when
the storyboard changed outside the app, so the app reloads it; or exit 4 (`EXIT_REFUSED`) when the thinker
says a change cannot be made in words, so the app says where to make it by hand.
"""
import argparse
import contextlib
import copy
import hashlib
import itertools
import json
import os
import re
import sys
import unicodedata
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable, Mapping

from project import produce, research, storyboard_edit
from project.thinkers import Thinker, ThinkError, _line, redact, thinker_from_env
from project.validate import ValidationError, load_schema, validate

PLAN_DRAFT = "plan_draft.json"
UNOPENED = "app_cache/plan_unopened.json"      # the pages of the plan's facts Frameflow could not open
NOT_CHECKED = re.compile(r"fact (\d+): not checked")     # research.check's line for such a fact
EXIT_CHANGED = 3        # not 2, which is argparse's for a command it cannot read
EXIT_REFUSED = 4
MISSING = "{name} was moved or deleted. Put it back where it was, or make a new video with it."


class Refused(storyboard_edit.EditError):
    """A change the thinker says cannot be made in words, in its words."""


SYSTEM =("You are the thinker for Frameflow, a video editor. Frameflow sends you one request, checks your "
          "answer and writes every file itself. Write no file and run nothing. Answer only with the JSON the "
          "request asks for: through the answer tool when you have one, otherwise as one fenced ```json block "
          "at the end of your final message.")

# The brief's request is the chat's too, whose steps an answer must skip; so every plan request ends with this.
LAST_STEP = ("\n## Answer with the plan\n\nFrameflow checks the plan, opens the sources and shows it to the creator "
             "itself. Skip the steps above that write a file, run a command or wait for the creator, and answer "
             "with the plan.\n")

# The storyboard's request is the chat's too; and an answer carries the compositions a chat would write.
STORYBOARD_LAST_STEP = (
    "\n## Answer with the storyboard\n\nFrameflow checks the storyboard, writes the files and builds it itself. "
    "For each HyperFrames composition you write, put its files in the answer's `files`, each with a relative "
    "`path` (such as `intro/index.html`) and its `text`, and name its folder the same way (`intro`) as the "
    "scene's `visual.path` or the `overlay.path`: Frameflow puts them in a folder of this answer's own. A file is "
    "`.html`, `.css`, `.js`, `.svg` or `.json`, at most 512 KB, and all of them at most 4 MB. Skip the steps "
    "above that write a file, run a command or wait for the creator, and answer with the storyboard and any "
    "composition files.\n")
FILE_SUFFIXES = (".html", ".css", ".js", ".svg", ".json")
FILE_BYTES, FILES_BYTES = 512 * 1024, 4 * 1024 * 1024


def new_folder(root: Path, prompt: str) -> Path:
    """A new folder under `root` for a video, named from the prompt's first words."""
    # Any script's letters, digits and marks; anything else, Windows' forbidden characters too, parts words.
    plain = "".join(ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else " " for ch in prompt.lower())
    name = "-".join(plain.split()[:5])[:40].strip("-") or "video"
    root.mkdir(parents=True, exist_ok=True)     # a file in its place raises here, not on every name below
    for n in itertools.count(1):
        folder = root / (name if n == 1 else f"{name}-{n}")
        with contextlib.suppress(FileExistsError):
            folder.mkdir()
            return folder


def _quiet(step: str) -> None:
    """Where a step's name goes when nobody is watching; the command line prints it."""


def _reader() -> Callable[[str], str]:
    """research.read, each page read once: a fix round checks the same facts again."""
    pages = {}

    def read(url: str) -> str:
        if url not in pages:
            try:
                pages[url] = research.read(url)
            except (research.ReadError, research.Gone) as e:
                pages[url] = e
        if isinstance(pages[url], Exception):
            raise pages[url]
        return pages[url]
    return read


def _checked(facts: list[dict], reader=None) -> tuple[list[str], list[str]]:
    """check_brief's problems with the facts, each page opened; and the pages it could not check, which the
    creator opens instead."""
    problems, lines = research.check(facts, reader=reader)
    return problems, [facts[int(m[1]) - 1]["url"] for m in map(NOT_CHECKED.match, lines) if m]


def _mark(folder: Path, pages: list[str]) -> None:
    """Keep the pages Frameflow could not open, for the app to mark their facts. By page, not number, so a
    fact dropped or given another page by hand keeps every other mark right."""
    (folder / UNOPENED).parent.mkdir(exist_ok=True)
    storyboard_edit._write_bytes(folder / UNOPENED, json.dumps(pages).encode("utf-8"))


def _draft(folder: Path) -> dict:
    """The draft, or after Approve a copy of the brief: a change to an approved plan is a draft again."""
    return produce._read(folder, PLAN_DRAFT if (folder / PLAN_DRAFT).is_file() else produce.BRIEF_FILE, "brief")


def _material(inputs: dict) -> list[Path]:
    """Every file the build reads. A recording's is Frameflow's copy, not the file picked, which may go once
    the copy is made."""
    paths = [f["source"] for f in inputs.get("footage", [])] + [
        item["path"] for key in ("assets", "music", "looks") for item in inputs.get(key, [])]
    return list(dict.fromkeys(map(Path, paths)))


def _check_material(paths: Iterable[Path]) -> None:
    """Refused before any thinking when a file is gone: no thinker's run is spent on a video that cannot build."""
    for path in paths:
        if not path.exists():
            raise ThinkError(MISSING.format(name=path.name))


def _think(folder: Path, thinker: Thinker, request: str, shape: str | None = None,
           step: Callable[[str], None] = _quiet) -> dict:
    """The thinker's plan, checked with its facts on their pages, kept as the draft. It may search: a plan is
    where facts are written."""
    material = _material(produce._read(folder, produce.INPUTS_FILE))
    _check_material(material)
    step(f"Writing the plan with {thinker.name}")       # after the check: a refused job did not think
    read, unopened = _reader(), []

    def check(draft: dict) -> list[str]:
        problems = [f"aspect: the creator chose {shape}"] if shape and draft["aspect"] != shape else []
        unopened[:] = []
        if draft.get("facts"):
            step("Checking the facts on their pages")
            wrong, unopened[:] = _checked(draft["facts"], read)
            problems = wrong + problems
            if problems:
                step(f"Writing the plan with {thinker.name}")      # a fix round: it is written again
        return problems

    draft = thinker.answer(SYSTEM, request, load_schema("brief"), check, search=True, material=material)
    storyboard_edit._write(folder / PLAN_DRAFT, draft)   # whole: the app may be reading it
    _mark(folder, unopened)
    return draft


def _request(folder: Path, thinker: Thinker, draft: dict, ask: str) -> str:
    """The brief's own request, then the plan so far and what to do with it."""
    inputs = produce._read(folder, produce.INPUTS_FILE)
    return (produce.brief_request(folder, inputs, can_search=thinker.can_search)
            + f"\n## The plan so far\n\n```json\n{json.dumps(draft, indent=2, ensure_ascii=False)}\n```\n\n{ask}"
            + LAST_STEP)


def _prepared_from(folder: Path, footage, assets, music, looks, script: Path | None) -> dict | None:
    """The folder's material, when it was prepared from exactly these files, each recording unchanged since."""
    try:
        kept = produce._read(folder, produce.INPUTS_FILE)
        given = ([produce.stamp(p) for p in footage],
                 *([Path(p).resolve().as_posix() for p in files] for files in (assets, music, looks)),
                 script.read_text(encoding="utf-8") if script else None)
    except (OSError, produce.ProduceError):
        return None     # none yet, or something prepare will say is wrong
    # A recording prepared before its size and time were kept has no stamp, so it is prepared again.
    recorded = ([f.get("stamp") for f in kept.get("footage", [])],
                *([item["path"] for item in kept.get(k, [])] for k in ("assets", "music", "looks")),
                kept.get("script"))
    return kept if given == recorded else None


def start(folder: Path, prompt: str, thinker: Thinker, *, footage=(), assets=(), music=(), looks=(),
          script: Path | None = None, shape: str | None = None, step: Callable[[str], None] = _quiet) -> dict:
    """Prepare the material, then have the thinker write the plan's draft. With no files given, the material
    the folder already holds is kept: after a restart the app cannot send the files it picked before. With the
    very files it was prepared from, it is kept too: Try again must not transcribe a recording again."""
    step("Preparing the material")
    _check_material([*footage, *assets, *music, *looks, *([script] if script else [])])
    given = footage or assets or music or looks or script
    kept = (_prepared_from(folder, footage, assets, music, looks, script) if given
            else produce._read(folder, produce.INPUTS_FILE) if (folder / produce.INPUTS_FILE).is_file() else None)
    if kept and (given or kept.get("script") is not None
                 or any(kept.get(k) for k in ("footage", "assets", "music", "looks"))):
        storyboard_edit._write(folder / produce.INPUTS_FILE, dict(kept, prompt=prompt))
    else:
        produce.prepare(folder, prompt, script, footage, assets, music, looks=looks)
    request = produce.brief_request(folder, produce._read(folder, produce.INPUTS_FILE),
                                    can_search=thinker.can_search)
    if shape:
        request += f"\n## The shape\n\nThe creator chose {shape}: make it the `aspect`.\n"
    request += LAST_STEP
    (folder / produce.BRIEF_REQUEST).write_text(request, encoding="utf-8")     # as it was asked
    return _think(folder, thinker, request, shape, step)


def change_plan(folder: Path, words: str, thinker: Thinker, step: Callable[[str], None] = _quiet) -> dict:
    """The draft with a change the creator asked for in words."""
    draft = _draft(folder)
    return _think(folder, thinker, _request(folder, thinker, draft,
                  f"## The change\n\nThe creator asks for this change to the plan:\n\n{words}\n\n"
                  "Send the whole plan again with it made, and everything else as it was.\n"), step=step)


def answer_question(folder: Path, number: int, words: str, thinker: Thinker,
                    step: Callable[[str], None] = _quiet) -> dict:
    """The draft with the creator's answer to its open question `number` (from 1) folded in."""
    draft = _draft(folder)
    questions = draft.get("open_questions", [])
    question = questions[_index(questions, number, "question")]
    return _think(folder, thinker, _request(folder, thinker, draft,
                  f"## An answer\n\nThe creator answered open question {number}, \"{question}\":\n\n{words}\n\n"
                  "Send the whole plan again with the answer folded in and that question taken out of "
                  "`open_questions`.\n"), step=step)


def _index(items: list, number, what: str) -> int:
    if not isinstance(number, int) or not 1 <= number <= len(items):
        raise produce.ProduceError(f"The plan has no {what} {number}.")
    return number - 1


def edit_plan(folder: Path, fields: dict) -> dict:
    """The draft with the creator's own edits: any brief field, `remove_question` and `drop_fact` (from 1), and
    `fact: {number, url, quote}` filling in a fact's source. A bad edit is one plain line and changes nothing."""
    draft, fields = _draft(folder), dict(fields)
    if "fact" in fields:        # before anything is removed, so the numbers are the ones the creator saw
        source, facts = fields.pop("fact"), draft.get("facts", [])
        facts[_index(facts, source.get("number"), "fact")].update(url=source.get("url"), quote=source.get("quote"))
    for key, listed, what in (("remove_question", "open_questions", "question"), ("drop_fact", "facts", "fact")):
        if key in fields:
            items = draft.get(listed, [])
            del items[_index(items, fields.pop(key), what)]
    draft.update(fields)
    try:
        validate(draft, "brief")
    except ValidationError as e:
        wrong = str(e).splitlines()[1:]         # each "at <field>: <what is wrong>", less the heading
        raise produce.ProduceError("That change was not made: " + "; ".join(w.strip() for w in wrong)) from None
    storyboard_edit._write(folder / PLAN_DRAFT, draft)
    return draft


# --- the storyboard --------------------------------------------------------------------

def _answer_schema() -> dict:
    """The storyboard's schema, and the composition files the answer may carry with it."""
    schema = load_schema("storyboard")
    schema["properties"]["files"] = {"type": "array", "items": {
        "type": "object", "required": ["path", "text"], "additionalProperties": False,
        "properties": {"path": {"type": "string", "minLength": 1}, "text": {"type": "string"}}}}
    return schema


def _set(folder: Path, files: list[dict]) -> Path:
    """Where an answer's files go: a folder named for them, so no answer replaces what an earlier storyboard
    uses (Undo back to it finds its own files) or any file of the video's own."""
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return folder.resolve() / "compositions" / digest


def _file_problems(folder: Path, files: list[dict]) -> list[str]:
    """The rules a carried file is written under: a relative path that stays in its set, web text, not big."""
    problems, inside, total = [], _set(folder, files), 0
    for file in files:
        path, size = file["path"], len(file["text"].encode("utf-8"))
        total += size
        # A drive, a root or a colon is refused on any system: `E:x` joins onto another folder of that drive,
        # and `a.html:b` is a stream of another file.
        named = PureWindowsPath(path)
        if ":" in path or named.drive or named.root or inside not in (inside / path).resolve().parents:
            problems.append(f"files: {path} is not a relative path that stays in its folder")
        elif Path(path).suffix.lower() not in FILE_SUFFIXES:
            problems.append(f"files: {path} is not an .html, .css, .js, .svg or .json file")
        elif size > FILE_BYTES:
            problems.append(f"files: {path} is over 512 KB")
    if total > FILES_BYTES:
        problems.append(f"files: {total / 1e6:.1f} MB in all is over 4 MB")
    return problems


def _board(folder: Path, answer: dict) -> tuple[dict, frozenset[str]]:
    """The answer's storyboard, each carried composition's folder named in full as the engine reads it from
    wherever it runs; and those folders."""
    board = copy.deepcopy({key: value for key, value in answer.items() if key != "files"})
    inside = _set(folder, answer.get("files", []))
    pages = {(inside / file["path"]).resolve() for file in answer.get("files", [])}
    carried = set()
    compositions = [scene["visual"] for scene in board["scenes"] if scene["visual"]["type"] == "composition"]
    for holder in compositions + ([board["overlay"]] if "overlay" in board else []):
        there = (inside / holder["path"]).resolve()
        if there / "index.html" in pages:
            holder["path"] = there.as_posix()
            carried.add(holder["path"])
    return board, frozenset(carried)


def write_storyboard(folder: Path, brief: dict, thinker: Thinker,
                     step: Callable[[str], None] = _quiet) -> tuple[dict, list[dict]]:
    """The thinker's storyboard for `brief`, checked as a build would check it, and the composition files it
    carries, `[{"path", "text"}]` with each path where it goes inside the video's folder. Nothing of either is
    written."""
    inputs = produce._read(folder, produce.INPUTS_FILE)
    asked = produce.storyboard_request(folder, brief)
    request = asked.read_text(encoding="utf-8") + STORYBOARD_LAST_STEP
    asked.write_text(request, encoding="utf-8")      # as it was asked

    def problems_of(answer: dict) -> list[str]:
        problems = _file_problems(folder, answer.get("files", []))
        if problems:
            return problems
        board, carried = _board(folder, answer)
        return (produce.check_storyboard(board, inputs, carried)
                or produce.check_buildable(folder, board, brief, inputs))

    def check(answer: dict) -> list[str]:
        step("Checking the storyboard")
        problems = problems_of(answer)
        if problems:
            step("Writing the storyboard")      # a fix round: it is written again
        return problems

    step("Writing the storyboard")
    answer = thinker.answer(SYSTEM, request, _answer_schema(), check, search=False, material=_material(inputs))
    files = answer.get("files", [])
    inside, video = _set(folder, files), folder.resolve()
    # Each destination is the very path the check resolved, so what is written is what was checked.
    return _board(folder, answer)[0], [
        dict(file, path=(inside / file["path"]).resolve().relative_to(video).as_posix()) for file in files]


def approve(folder: Path, thinker: Thinker, step: Callable[[str], None] = _quiet) -> Path:
    """Approve the draft: have its storyboard written, then write the composition files, and the brief and the
    storyboard as one change to undo. With no draft and no storyboard yet (a brief made in a chat), the brief is
    approved as it is. Refused, with nothing changed, while the plan has open questions or a fact its page does
    not bear out."""
    _check_material(_material(produce._read(folder, produce.INPUTS_FILE)))
    if not (folder / PLAN_DRAFT).is_file() and (folder / produce.STORYBOARD_FILE).is_file():
        raise produce.ProduceError("Nothing to approve: the plan has not changed since it was approved.")
    draft = _draft(folder)
    if draft.get("open_questions"):
        raise produce.ProduceError("The plan still has open questions. Answer or remove each one first:\n"
                                   + "\n".join(f"  - {q}" for q in draft["open_questions"]))
    step("Checking the facts")
    problems, unopened = _checked(draft.get("facts", []), _reader())     # each fact's page is opened again now
    if problems:
        raise produce.ProduceError("The plan's facts need fixing:\n" + "\n".join(f"  {p}" for p in problems))
    _mark(folder, unopened)
    # The storyboard as it was before the thinker began: one changed meanwhile is not replaced.
    expect = storyboard_edit.version(folder) if (folder / produce.STORYBOARD_FILE).is_file() else None
    board, files = write_storyboard(folder, draft, thinker, step)
    if expect:
        storyboard_edit._expect(folder, expect)     # before a file is written
    for file in files:
        path = folder / file["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        storyboard_edit._write_bytes(path, file["text"].encode("utf-8"))
    storyboard_edit.replace(folder, draft, board, expect)
    (folder / PLAN_DRAFT).unlink(missing_ok=True)
    return folder / produce.STORYBOARD_FILE


# --- a change in words -----------------------------------------------------------------

OPERATIONS = ("move", "delete", "add", "words", "title", "duration", "over", "picture", "rename_chapter",
              "keep_chapter", "remove_chapter", "video")

# One flat object, as a key's answer tool takes no choice of shapes at the top; `_shape` holds it to one of the two.
CHANGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "ops": {"type": "array", "minItems": 1, "items": {
            "type": "object", "required": ["op"], "properties": {"op": {"enum": list(OPERATIONS)}}}},
        "summary": {"type": "string", "minLength": 1},
        "refused": {"type": "string", "minLength": 1}}}

CHANGE_OPERATIONS = """
## The operations

A change is a list of these, made in order. Scenes and chapters are numbered from 1, and each operation sees the storyboard as the ones before it left it: after scene 2 is deleted, scene 3 is scene 2.

- `{"op": "move", "from": 4, "to": 1}`: scene 4 becomes scene 1, in the chapter of the scene whose place it takes.
- `{"op": "delete", "number": 4}`: scene 4 goes.
- `{"op": "add", "after": 3, "scene": {"kind": "title", "text": "..."}}`: a new scene after scene 3, or first with `"after": 0`. The `scene` is a title as here, `{"kind": "file", "path": "..."}` for one of the creator's files, or `{"kind": "recording", "words": "..."}` for words said in a recording.
- `{"op": "words", "number": 4, "words": "..."}`: what scene 4 says. A scene of a recording with no narration plays the words you give, found in that recording, so give a run of them just as they are said. For any other scene they are its narration, and `""` takes the narration away.
- `{"op": "title", "number": 4, "text": "..."}`: the words on screen of a title scene.
- `{"op": "duration", "number": 4, "seconds": 2.5}`: how long scene 4 lasts, from 0.5 to 600 seconds, for a title, a picture or a composition with no narration.
- `{"op": "over", "number": 4, "caption": "...", "cards": [], "broll": []}`: what is over scene 4. Each of `caption`, `cards` and `broll` you give replaces the scene's own, in the storyboard's shape, and `null` takes it away; leave out the ones that stay.
- `{"op": "picture", "number": 4, "path": "..."}`: one of the creator's files as scene 4's picture. Over a scene of a recording it is B-roll for the whole scene.
- `{"op": "rename_chapter", "number": 2, "title": "..."}`: chapter 2's name.
- `{"op": "keep_chapter", "number": 2}`: chapter 2 is kept as the creator's own.
- `{"op": "remove_chapter", "number": 2}`: chapter 2 goes, and its scenes join the chapter before it.
- `{"op": "video", "spoken_captions": true, "cut_to_beat": true, "look": "..."}`: the whole video's settings; give only the ones to change. `look` is the path of one of the video's looks, or `null` for none.

A file is named by its `path` in the storyboard or in the list of the creator's files. A recording's length changes through its words; a title's, picture's or composition's through `duration`. No operation changes anything else, such as the music.
"""

CHANGE_LAST_STEP = (
    "\n## Answer with the change\n\nFrameflow makes the change itself, checking each operation as it checks a "
    "change made by hand. Write no file, run no command and wait for nothing. Answer only with `ops`, the "
    "operations in the order to make them, and `summary`, one line of what changed; or, when these operations "
    "cannot make the change, only with `refused`, why in one line.\n")


def _shape(answer: dict) -> list[str]:
    return [] if set(answer) in ({"ops", "summary"}, {"refused"}) else [
        "Answer with `ops` and `summary`, or with `refused` alone."]


def change_in_words(folder: Path, words: str, expect: str, thinker: Thinker) -> dict:
    """A change the creator asked for in words, made as one change with one entry to undo: its notes, and the
    thinker's line of what changed. Refused, with nothing written, when the thinker says these operations
    cannot make it, or when the storyboard is not the one the app last read (`expect`), before or after."""
    storyboard_edit._expect(folder, expect)
    board, inputs = produce._read(folder, produce.STORYBOARD_FILE), produce._read(folder, produce.INPUTS_FILE)
    material = _material(inputs)
    _check_material(material)
    says = "\n".join(f"{n}. {storyboard_edit.said(scene, folder, inputs)}"
                     for n, scene in enumerate(board["scenes"], start=1))
    files = "\n".join(f"- {item['path']}" for item in inputs["assets"] + produce._looks(inputs)) or "None."
    request = ("# A change to a storyboard, in the creator's words\n\n"
               f"## The storyboard\n\n```json\n{json.dumps(board, indent=2, ensure_ascii=False)}\n```\n\n"
               f"## What each scene says\n\n{says}\n\n## The creator's files and looks\n\n{files}\n\n"
               f"## The change\n\nThe creator asks for this change:\n\n{words}\n"
               + CHANGE_OPERATIONS + CHANGE_LAST_STEP)

    def check(answer: dict) -> list[str]:
        if _shape(answer) or "refused" in answer:
            return _shape(answer)       # a refusal has no operations to check
        if storyboard_edit.version(folder) != expect:
            return []       # changed meanwhile: refused as that below, not sent back as the thinker's to fix
        return storyboard_edit.check_ops(folder, answer["ops"])

    answer = thinker.answer(SYSTEM, request, CHANGE_SCHEMA, check, search=False, material=material)
    if "refused" in answer:
        raise Refused(answer["refused"])
    # No file is the creator's pick here, so none is added; and `expect` is checked again before the write.
    notes = storyboard_edit.edit_many(folder, answer["ops"], expect, chosen=())
    return {"notes": notes, "summary": answer["summary"]}


# --- the command line ------------------------------------------------------------------

READY = {"type": "object", "required": ["ready"], "additionalProperties": False,
         "properties": {"ready": {"const": True}}}


def _step(text: str) -> None:
    print(f"==> {text}")


def _wrote(draft: dict) -> None:
    questions = len(draft.get("open_questions", []))
    print(f"    {draft['title']}, with {questions or 'no'} open question{'' if questions == 1 else 's'}")


def _done(result: dict) -> None:
    """The last line, which the app reads for what the job made."""
    print("==> Done " + json.dumps(result, ensure_ascii=False))


def main(argv: list[str], env: Mapping[str, str] = os.environ) -> int:
    parser = argparse.ArgumentParser(prog="python -m project.app_think")
    commands = parser.add_subparsers(dest="command", required=True)
    added = {name: commands.add_parser(name) for name in ("start", "plan-change", "answer", "approve", "change")}
    commands.add_parser("test")
    for command in added.values():
        command.add_argument("folder", type=Path)
    added["start"].add_argument("--prompt", required=True)
    for files in ("footage", "asset", "music", "look"):
        added["start"].add_argument(f"--{files}", type=Path, action="append", default=[])
    added["start"].add_argument("--script", type=Path)
    added["start"].add_argument("--shape", choices=("9:16", "16:9", "1:1"))
    added["answer"].add_argument("--question", type=int, required=True)
    for name in ("plan-change", "answer", "change"):
        added[name].add_argument("--words", required=True)
    added["change"].add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        thinker = thinker_from_env(env)
        if args.command == "test":
            thinker.answer(SYSTEM, 'Answer with `{"ready": true}`.', READY, lambda answer: [], search=False)
            print(f"Ready: {thinker.name}")
        elif args.command == "start":
            _wrote(start(args.folder, args.prompt, thinker, footage=args.footage, assets=args.asset,
                         music=args.music, looks=args.look, script=args.script, shape=args.shape, step=_step))
        elif args.command == "plan-change":
            _wrote(change_plan(args.folder, args.words, thinker, _step))
        elif args.command == "answer":
            _wrote(answer_question(args.folder, args.question, args.words, thinker, _step))
        elif args.command == "approve":
            _done({"storyboard": str(approve(args.folder, thinker, _step))})
        else:
            _step("Making the change")
            changed = change_in_words(args.folder, args.words, args.version, thinker)
            _done({"summary": changed["summary"], "notes": changed["notes"]})
    except Exception as e:      # the app shows this line; a traceback would tell the creator nothing
        # Only its own words: an error raised `from None` still holds the SDK's, which can echo the key.
        print(_line(redact(str(e) or type(e).__name__, env.get("FRAMEFLOW_KEY")), 1000), file=sys.stderr)
        return EXIT_CHANGED if getattr(e, "changed", False) else EXIT_REFUSED if isinstance(e, Refused) else 1
    return 0


if __name__ == "__main__":
    # UTF-8 whatever the PC's code page: a plan's title in Hindi must print as written. And never strict:
    # a file name with half a character in it would raise while a failure is printed, and show a traceback.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.exit(main(sys.argv[1:]))
