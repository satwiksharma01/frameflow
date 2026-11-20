"""The changes a creator makes to a storyboard in the app, one operation at a time.

Each operation reads storyboard.json, changes it, checks the result as a build would, and writes it back
atomically - or raises EditError and writes nothing. Chapters stay attached to their scenes: before a change
each scene knows its chapter, and afterwards each chapter starts at its first scene's new number.
"""
import copy
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from project import first_cut, produce
from project.cutpoints import span_of, tokenize
from project.media import MediaError, analyze
from project.validate import ValidationError, validate
from project.verify_cuts import words_in_clip

REASON = "Added by the creator in the app"
HISTORY = 200        # changes kept to undo, and to redo
CHANGED = ("The storyboard changed outside the app, so it was reloaded. "
           "Your last change was not made.")
NOT_SAID = "Not said in your recording. The words stay as they were."
PLAN = "plan-"       # in the name of a history entry that holds the brief with the storyboard


class EditError(Exception):
    """A change that cannot be made, in the words the creator is shown."""

    def __init__(self, message: str, changed: bool = False):
        super().__init__(message)
        self.changed = changed       # the storyboard changed outside the app since it was last read


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_bytes(path: Path, data: bytes) -> None:
    """Write as a whole or not at all: a reader never sees half a storyboard."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        for attempt in range(40):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:      # Windows refuses while a reader (a thumbnail, a build) holds it open
                if attempt == 39:
                    raise
                time.sleep(0.05)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write(path: Path, document: dict) -> None:
    _write_bytes(path, (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _timing(folder: Path, recording: dict | None) -> dict:
    path = folder / recording["folder"] / first_cut.TIMING_FILE if recording else None
    return _read(path) if path and path.is_file() else {"words": [], "pauses": []}


def said(scene: dict, folder: Path, inputs: dict) -> str:
    """What a scene says: its narration, else its recording's words inside its span, else a title's words."""
    visual = scene["visual"]
    if scene.get("narration"):
        return scene["narration"]
    if visual["type"] == "footage":
        recording = produce._match(visual["source"], inputs["footage"], "name")
        words = words_in_clip(_timing(folder, recording)["words"],
                              {"source_in": visual["start"], "source_out": visual["end"]})
        return " ".join(w["text"].strip() for w in words)
    return visual.get("text", "")


def _fps(folder: Path, recording: dict) -> float:
    return (_read(folder / produce.BRIEF_FILE).get("fps") if (folder / produce.BRIEF_FILE).is_file() else None) \
        or round(analyze(recording["source"]).nominal_fps)


def _find(folder: Path, recording: dict, words: str, near: float | None) -> tuple[float, float] | None:
    timing = _timing(folder, recording)
    try:
        return span_of(timing["words"], timing["pauses"], words, _fps(folder, recording), near,
                       recording["duration"])
    except ValueError as e:
        raise EditError(f"{e}. The words stay as they were.") from None


def _needs_duration(scene: dict, inputs: dict) -> bool:
    """As check_storyboard asks: a picture that does not play needs a length, or narration to set one."""
    visual = scene["visual"]
    asset = produce._match(visual["path"], inputs["assets"], "path") if visual["type"] == "asset" else None
    return (visual["type"] in ("title", "composition") or (asset is not None and asset["kind"] == "image")
            or (visual["type"] == "generated" and visual["kind"] == "picture"))


def _file(path: str, inputs: dict, chosen: list[str]) -> dict:
    """One of the creator's files: already in inputs, or picked in the app's file dialog and added now."""
    known = produce._match(path, inputs["assets"], "path")
    if known:
        return known
    resolved = Path(path).resolve()
    if resolved.as_posix() not in {Path(c).resolve().as_posix() for c in chosen}:
        raise EditError(f"{resolved.name} is not one of your files.")
    try:
        if not resolved.is_file():
            raise MediaError(f"{resolved} is not there")
        entry = produce.asset_entry(resolved)
    except (MediaError, OSError, ValueError, KeyError):
        raise EditError(f"Frameflow can't read {resolved.name} as a picture or a clip.") from None
    inputs["assets"].append(entry)
    return entry


def _contains(said_tokens: list[str], phrase: str) -> bool:
    want = tokenize(phrase)
    return any(said_tokens[i:i + len(want)] == want for i in range(len(said_tokens) - len(want) + 1)) if want else False


def _settle(scene: dict, folder: Path, inputs: dict) -> list[str]:
    """A card or B-roll whose words the scene no longer says shows from its start instead."""
    tokens, notes = tokenize(said(scene, folder, inputs)), []
    for card in scene.get("cards", []):
        if "when" in card and not _contains(tokens, card["when"]):
            notes.append(f"Card “{card['text']}” now shows from the start of the scene: "
                         f"“{card.pop('when')}” is not said in it any more.")
    for b in scene.get("broll", []):
        if "when" in b and not _contains(tokens, b["when"]):
            notes.append(f"B-roll {Path(b['path']).name} now shows from the start of the scene: "
                         f"“{b.pop('when')}” is not said in it any more.")
    return notes


def _owners(board: dict) -> list[int | None]:
    """Which chapter each scene is in, by the chapter's place in `sections`."""
    sections = board.get("sections", [])
    return [max((k for k, s in enumerate(sections) if s["from"] <= n), default=None)
            for n in range(1, len(board["scenes"]) + 1)]


def _regroup(board: dict, sections: list[dict], owners: list[int | None]) -> None:
    """Each chapter starts at its first scene's number; a chapter with no scenes goes."""
    regrouped = []
    for n, k in enumerate(owners, start=1):
        if k is not None and k not in [r[0] for r in regrouped]:
            regrouped.append((k, dict(sections[k], **{"from": n})))
    if regrouped:
        board["sections"] = [section for _, section in regrouped]
    else:
        board.pop("sections", None)


def _scene(board: dict, number) -> dict:
    if not isinstance(number, int) or not 1 <= number <= len(board["scenes"]):
        raise EditError(f"There is no scene {number}.")
    return board["scenes"][number - 1]


def _chapter(board: dict, number) -> dict:
    sections = board.get("sections", [])
    if not isinstance(number, int) or not 1 <= number <= len(sections):
        raise EditError(f"There is no chapter {number}.")
    return sections[number - 1]


def _new_scene(spec: dict, after: int, board: dict, folder: Path, inputs: dict, chosen: list[str]) -> dict:
    kind = spec.get("kind")
    if kind == "title":
        text = spec.get("text", "").strip()
        if not text:
            raise EditError("A title needs some words.")
        return {"visual": {"type": "title", "text": text}, "duration": 2.0, "reason": REASON}
    if kind == "file":
        entry = _file(spec.get("path", ""), inputs, chosen)
        scene = {"visual": {"type": "asset", "path": entry["path"]}, "reason": REASON}
        return dict(scene, duration=3.0) if entry["kind"] == "image" else scene
    if kind == "recording":
        if not inputs["footage"]:
            raise EditError("This video has no recordings to find words in.")
        beside = board["scenes"][after - 1]["visual"] if after else {}
        first = produce._match(beside["source"], inputs["footage"], "name") if beside.get("type") == "footage" else None
        for recording in ([first] if first else []) + [f for f in inputs["footage"] if f is not first]:
            span = _find(folder, recording, spec.get("words", ""), beside.get("start") if first is recording else None)
            if span:
                return {"visual": {"type": "footage", "source": recording["name"], "start": span[0], "end": span[1]},
                        "reason": REASON}
        raise EditError("Not said in your recordings.")
    raise EditError(f"Unknown kind of scene {kind!r}.")


def _change(board: dict, op: dict, folder: Path, inputs: dict, chosen: list[str]) -> list[str]:
    """Make `op` on `board` (and `inputs`, when a file is added), returning notes for the creator."""
    scenes, sections, owners = board["scenes"], board.get("sections", []), _owners(board)
    kind, notes = op.get("op"), []
    if kind == "move":
        _scene(board, op.get("from"))
        _scene(board, op.get("to"))
        owner = owners[op["to"] - 1]       # it joins the chapter of the scene whose place it takes
        scene, _ = scenes.pop(op["from"] - 1), owners.pop(op["from"] - 1)
        scenes.insert(op["to"] - 1, scene)
        owners.insert(op["to"] - 1, owner)
    elif kind == "delete":
        _scene(board, op.get("number"))
        if len(scenes) == 1:
            raise EditError("A video needs at least one scene.")
        scenes.pop(op["number"] - 1)
        owners.pop(op["number"] - 1)
    elif kind == "add":
        after = op.get("after")
        if not isinstance(after, int) or not 0 <= after <= len(scenes):
            raise EditError(f"There is no scene {after}.")
        scenes.insert(after, _new_scene(op.get("scene", {}), after, board, folder, inputs, chosen))
        owners.insert(after, owners[after - 1] if after else (owners[0] if owners else None))
    elif kind == "words":
        scene = _scene(board, op.get("number"))
        visual, words = scene["visual"], op.get("words", "")
        if visual["type"] == "footage" and not scene.get("narration"):
            recording = produce._match(visual["source"], inputs["footage"], "name")
            span = _find(folder, recording, words, visual["start"]) if recording else None
            if span is None:
                raise EditError(NOT_SAID)
            visual["start"], visual["end"] = span
        elif words.strip():
            scene["narration"] = words.strip()
        else:
            scene.pop("narration", None)
            if _needs_duration(scene, inputs) and "duration" not in scene:
                scene["duration"] = 3.0
                notes.append("It now lasts 3 seconds.")
        notes += _settle(scene, folder, inputs)
    elif kind == "title":
        scene = _scene(board, op.get("number"))
        if scene["visual"]["type"] != "title":
            raise EditError("Only a title has words on screen.")
        if not op.get("text", "").strip():
            raise EditError("A title needs some words.")
        scene["visual"]["text"] = op["text"].strip()
        notes += _settle(scene, folder, inputs)
    elif kind == "duration":
        scene, seconds = _scene(board, op.get("number")), op.get("seconds")
        if not _needs_duration(scene, inputs) or scene.get("narration"):
            raise EditError(f"Scene {op['number']}'s length comes from its recording or its narration.")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0.5 <= seconds <= 600:
            raise EditError("A scene lasts from 0.5 to 600 seconds.")
        scene["duration"] = seconds
    elif kind == "over":
        scene = _scene(board, op.get("number"))
        for key in ("caption", "cards", "broll"):
            if key in op:
                if op[key] in (None, "", []):
                    scene.pop(key, None)
                else:
                    scene[key] = op[key]
        for b in scene.get("broll", []):
            b["path"] = _file(b.get("path", ""), inputs, chosen)["path"]
        notes += _settle(scene, folder, inputs)
    elif kind == "picture":
        scene = _scene(board, op.get("number"))
        entry, visual = _file(op.get("path", ""), inputs, chosen), scene["visual"]
        if visual["type"] == "footage":
            scene["broll"] = [{"path": entry["path"], "duration": round(visual["end"] - visual["start"], 3)}]
        else:
            scene["visual"] = {"type": "asset", "path": entry["path"]}
            if _needs_duration(scene, inputs) and "duration" not in scene and not scene.get("narration"):
                scene["duration"] = 3.0
        notes += _settle(scene, folder, inputs)
    elif kind == "rename_chapter":
        chapter = _chapter(board, op.get("number"))
        if not op.get("title", "").strip():
            raise EditError("A chapter needs a name.")
        chapter.update(title=op["title"].strip(), confirmed=True)
    elif kind == "keep_chapter":
        _chapter(board, op.get("number"))["confirmed"] = True
    elif kind == "remove_chapter":
        _chapter(board, op.get("number"))
        gone = op["number"] - 1
        heir = gone - 1 if gone > 0 else (gone + 1 if len(sections) > 1 else None)
        owners = [heir if k == gone else k for k in owners]
    elif kind == "video":
        if "spoken_captions" in op:
            board["spoken_captions"] = bool(op["spoken_captions"])
        if "cut_to_beat" in op:
            if "music" not in board:
                raise EditError("This video has no music to cut to.")
            board["music"]["cut_to_beat"] = bool(op["cut_to_beat"])
        if "look" in op:
            if op["look"] is None:
                board.pop("look", None)
            elif not produce._match(op["look"], produce._looks(inputs), "path"):
                raise EditError(f"{op['look']} is not one of this video's looks.")
            elif board.get("look", {}).get("path") != op["look"]:
                board["look"] = {"path": op["look"]}
    else:
        raise EditError(f"Unknown change {kind!r}.")
    _regroup(board, sections, owners)
    return notes


def _made(folder: Path, ops: list[dict], chosen: list[str]) -> tuple[dict, dict, list[str], bool]:
    """The storyboard and the inputs with `ops` made in order, each checked as a build would check it; the
    notes for the creator; and whether a file was added. Nothing is written."""
    board, inputs = _read(folder / produce.STORYBOARD_FILE), _read(folder / produce.INPUTS_FILE)
    assets, notes = len(inputs["assets"]), []
    for op in ops:
        notes += _change(board, op, folder, inputs, list(chosen))
        try:
            validate(board, "storyboard")
            problems = produce.check_storyboard(board, inputs)
        except ValidationError as e:
            problems = [str(e)]
        if problems:
            raise EditError("That change can't be made: " + "; ".join(problems))
    return board, inputs, notes, len(inputs["assets"]) != assets


def _make(folder: Path, ops: list[dict], chosen: list[str]) -> list[str]:
    board, inputs, notes, added = _made(folder, ops, chosen)
    if added:
        _write(folder / produce.INPUTS_FILE, inputs)
    _write(folder / produce.STORYBOARD_FILE, board)
    return notes


def apply(folder: Path, op: dict, chosen: list[str] = ()) -> list[str]:
    """Make one change to a video's storyboard and write it, returning notes for the creator. Raises
    EditError, writing nothing, when the change cannot be made. A file path not among the video's assets
    is added only if it is in `chosen`: the files the creator picked in the app."""
    return _make(folder, [op], chosen)


def check_ops(folder: Path, ops: list[dict]) -> list[str]:
    """Why `ops`, made in order, would be refused: the first refusal's words, or nothing. A dry run of a
    thinker's answer, so an op in the wrong shape is a refusal too; nothing is written."""
    try:
        _made(folder, copy.deepcopy(ops), ())      # a change keeps parts of its op, and may then change them
    except EditError as e:
        return [str(e)]
    except (AttributeError, TypeError, KeyError):
        return ["An operation is not in the shape the request gives for it."]
    return []


# Versions and history. The app sends the version it last read with every change, so a change made against
# a storyboard someone else has since rewritten (the command line, an editor) is refused rather than lost.
# The bytes each change replaces are kept beside the video, so undo outlives the app. Each entry is named
# with the version it leads back from, so history never reaches past a change made outside the app.
# Approving a plan changes the brief with the storyboard: that entry holds both files, and its name says so.

def version(folder: Path) -> str:
    """The storyboard as it is now, as 16 hex digits."""
    return hashlib.sha256((folder / produce.STORYBOARD_FILE).read_bytes()).hexdigest()[:16]


def _stack(folder: Path, name: str) -> Path:
    return folder / "app_cache" / name


def _entries(stack: Path) -> list[Path]:
    return sorted(stack.glob("*.json")) if stack.is_dir() else []


def _push(stack: Path, data: bytes, leads_from: str) -> None:
    stack.mkdir(parents=True, exist_ok=True)
    entries = _entries(stack)
    number = int(entries[-1].stem.split("-")[0]) + 1 if entries else 1
    _write_bytes(stack / f"{number:06d}-{leads_from}.json", data)
    for old in _entries(stack)[:-HISTORY]:
        old.unlink()


def _top(folder: Path, name: str) -> Path | None:
    """The entry to step to next, if it leads from the storyboard as it is now."""
    entries = _entries(_stack(folder, name))
    return entries[-1] if entries and entries[-1].stem.endswith(f"-{version(folder)}") else None


def _clear(stack: Path) -> None:
    for entry in _entries(stack):
        entry.unlink()


def _expect(folder: Path, expect: str) -> None:
    if version(folder) != expect:
        raise EditError(CHANGED, changed=True)


def _both(folder: Path) -> bytes:
    """The brief and the storyboard as they are now, as one entry."""
    brief = folder / produce.BRIEF_FILE
    return json.dumps({"brief": brief.read_bytes().decode("utf-8") if brief.is_file() else None,
                       "storyboard": (folder / produce.STORYBOARD_FILE).read_bytes().decode("utf-8")}).encode("utf-8")


def replace(folder: Path, brief: dict, board: dict, expect: str | None) -> None:
    """Write an approved plan and the storyboard written from it, as one change that one undo takes back.
    A new video has no storyboard yet (`expect` is None), and so nothing to undo."""
    before = None
    if (folder / produce.STORYBOARD_FILE).is_file():
        _expect(folder, expect)
        before = _both(folder)
    _write(folder / produce.BRIEF_FILE, brief)
    _write(folder / produce.STORYBOARD_FILE, board)
    if before:
        _push(_stack(folder, "undo"), before, f"{PLAN}{version(folder)}")
        _clear(_stack(folder, "redo"))


def edit_many(folder: Path, ops: list[dict], expect: str, chosen: list[str] = ()) -> list[str]:
    """Every op in order as one change, written once or not at all, but only to the storyboard the app last
    read (`expect` is its version), keeping what it replaces as one entry to undo."""
    _expect(folder, expect)
    before = (folder / produce.STORYBOARD_FILE).read_bytes()
    notes = _make(folder, ops, chosen)
    _push(_stack(folder, "undo"), before, version(folder))
    _clear(_stack(folder, "redo"))
    return notes


def edit(folder: Path, op: dict, expect: str, chosen: list[str] = ()) -> list[str]:
    """`apply`, but only to the storyboard the app last read (`expect` is its version), keeping what it
    replaces to undo."""
    return edit_many(folder, [op], expect, chosen)


def _step(folder: Path, expect: str, back: str, forth: str, nothing: str) -> None:
    _expect(folder, expect)
    entry = _top(folder, back)
    if entry is None:
        # Whatever history is left leads from a storyboard that is no longer there.
        _clear(_stack(folder, back))
        _clear(_stack(folder, forth))
        raise EditError(nothing)
    board, brief = folder / produce.STORYBOARD_FILE, folder / produce.BRIEF_FILE
    plan = PLAN if f"-{PLAN}" in entry.name else ""     # an approved plan: the entry holds the brief too
    now = _both(folder) if plan else board.read_bytes()
    if plan:
        both = json.loads(entry.read_bytes())
        if both["brief"] is None:
            brief.unlink(missing_ok=True)
        else:
            _write_bytes(brief, both["brief"].encode("utf-8"))
        _write_bytes(board, both["storyboard"].encode("utf-8"))
    else:
        _write_bytes(board, entry.read_bytes())
    _push(_stack(folder, forth), now, f"{plan}{version(folder)}")
    entry.unlink()


def undo(folder: Path, expect: str) -> None:
    _step(folder, expect, "undo", "redo", "Nothing to undo.")


def redo(folder: Path, expect: str) -> None:
    _step(folder, expect, "redo", "undo", "Nothing to redo.")


def history(folder: Path) -> tuple[bool, bool]:
    """Whether there is a change to undo, and one to redo."""
    return _top(folder, "undo") is not None, _top(folder, "redo") is not None
