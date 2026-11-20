"""What an app asks the engine, answered in JSON.

    python -m project.app_api videos ROOT          the videos under a folder, newest first
    python -m project.app_api describe FOLDER      one video's storyboard, as the creator reads it
    python -m project.app_api thumbnail FOLDER KEY a small picture of the scene with that key: its path, or null
    python -m project.app_api serve               the same and the app's changes, kept running for the app
    python -m project.app_api open FOLDER          a built video's project, shown in OpenShot

Each command prints one JSON value; a failure prints {"error": "..."} and exits 1. `serve` reads one request
per line, {"id", "method", "params"}, and answers each on a line of its own, {"id", "result"} or {"id", "error"}.
`open` prints its steps as a build does, and a failure's reason on stderr.
"""
import hashlib
import json
import subprocess
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from project import app_think, produce, thinkers
from project.cutpoints import kept_pieces, trim_edges
from project.editors import DEFAULT, EDITORS
from project.media import IMAGE_SUFFIXES, _find_tool
from project.validate import ValidationError, validate
from project import storyboard_edit
from project.storyboard_edit import EditError, said

THUMB_WIDTH = 176       # twice the 88 px a scene's frame is drawn at


def _read(folder: Path, name: str) -> dict | None:
    path = folder / name
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from None


def _report(folder: Path) -> dict | None:
    """The last build's report, if it is of the storyboard and brief as they are now. File times say
    nothing: a storyboard changed during a build is older than that build's report."""
    try:
        report = _read(folder, produce.REPORT_FILE)
    except ValueError:      # half written
        return None
    return report if report and report.get("of") == produce.source_digest(folder) else None


def _title(folder: Path) -> str:
    """The approved plan's title, else its draft's, else the folder's name."""
    for name in (produce.BRIEF_FILE, app_think.PLAN_DRAFT):
        try:
            title = (_read(folder, name) or {}).get("title")
        except (ValueError, AttributeError):      # half written, or not an object
            continue
        if title:
            return title
    return folder.name


def _plan(folder: Path) -> tuple[dict | None, bool]:
    """The plan: its draft while there is one, else the approved brief; and whether it is the draft."""
    draft = _read(folder, app_think.PLAN_DRAFT)
    return (draft, True) if draft is not None else (_read(folder, produce.BRIEF_FILE), False)


def _unopened(folder: Path, plan: dict | None) -> list[int]:
    """The numbers of the plan's facts whose page Frameflow could not open when it last checked them."""
    pages = _read(folder, app_think.UNOPENED) or []
    facts = (plan or {}).get("facts", [])
    return [n for n, fact in enumerate(facts, start=1) if fact.get("url") in pages]


def _given(inputs: dict) -> dict:
    """The creator's idea and material, by file name, as the prompt step lists them."""
    def names(kind: str) -> list[str]:
        return [Path(item["path"]).name for item in inputs.get(kind, [])]

    return {"prompt": inputs.get("prompt"),
            "material": {"footage": [f["name"] for f in inputs.get("footage", [])], "assets": names("assets"),
                         "music": names("music"), "looks": names("looks"),
                         "script": inputs.get("script") is not None}}


def videos(root: Path) -> list[dict]:
    """The videos under `root`: every folder with its inputs or a plan, newest first."""
    if not root.is_dir():
        return []

    def changed(folder: Path) -> float:
        files = (folder / produce.STORYBOARD_FILE, folder / produce.INPUTS_FILE, folder / app_think.PLAN_DRAFT)
        return next(f for f in files if f.is_file()).stat().st_mtime

    folders = sorted((f for f in root.iterdir()
                      if (f / produce.INPUTS_FILE).is_file() or (f / app_think.PLAN_DRAFT).is_file()),
                     key=changed, reverse=True)
    return [{"folder": str(f), "title": _title(f), "has_storyboard": (f / produce.STORYBOARD_FILE).is_file(),
             "built": _report(f) is not None, "cover": _cover(f)} for f in folders]


def _covered_by(scene: dict) -> dict | None:
    """The B-roll over a footage scene from its start to its end, as covering it with a picture lays it."""
    visual = scene["visual"]
    if visual["type"] != "footage":
        return None
    span = visual["end"] - visual["start"]
    return next((b for b in scene.get("broll", []) if "when" not in b and b.get("duration", span) >= span - 0.01),
                None)


def scene_keys(board: dict) -> list[str]:
    """A name for each scene that stays with it as scenes move: its picture's digest, and how many earlier
    scenes share that picture. A cover is part of the picture, so a covered scene's thumbnail is fetched anew."""
    keys, seen = [], {}
    for scene in board["scenes"]:
        cover = _covered_by(scene)
        picture = [scene["visual"], cover["path"]] if cover else scene["visual"]
        digest = hashlib.sha256(json.dumps(picture, sort_keys=True).encode()).hexdigest()[:12]
        keys.append(f"{digest}-{seen.get(digest, 0)}")
        seen[digest] = seen.get(digest, 0) + 1
    return keys


def _cover(folder: Path) -> str | None:
    """The key of a video's first scene, for its picture in the list of videos."""
    try:
        board = _read(folder, produce.STORYBOARD_FILE)
        return scene_keys(board)[0] if board and board.get("scenes") else None
    except (ValueError, KeyError, TypeError):      # a storyboard half written, or not yet a storyboard
        return None


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _recording(visual: dict, inputs: dict) -> dict | None:
    return produce._match(visual["source"], inputs["footage"], "name")


def _source(scene: dict) -> str:
    visual, cover = scene["visual"], _covered_by(scene)
    if cover:
        return f"{Path(cover['path']).name} over your recording {_clock(visual['start'])}–{_clock(visual['end'])}"
    if visual["type"] == "footage":
        return f"Your recording {_clock(visual['start'])}–{_clock(visual['end'])}"
    if visual["type"] == "asset":
        return Path(visual["path"]).name
    return {"title": "Title", "composition": "Graphic"}.get(visual["type"], f"Generated {visual.get('kind', '')}".strip())


def _over(scene: dict) -> list[str]:
    return ([f"Caption: {scene['caption']}"] if scene.get("caption") else []) + \
        [f"Card: {card['text']}" for card in scene.get("cards", [])] + \
        [f"B-roll: {Path(b['path']).name}" for b in scene.get("broll", [])]


def describe(folder: Path) -> dict:
    """One video's storyboard as the creator reads it, with the last build's report when it is current;
    the plan: its draft while there is one, else the approved brief, and its facts Frameflow could not open;
    and the creator's prompt and material."""
    board = _read(folder, produce.STORYBOARD_FILE)
    plan, plan_is_draft = _plan(folder)
    if board is None:
        return {"title": _title(folder), "scenes": [], "no_storyboard": True, "plan": plan,
                "plan_is_draft": plan_is_draft, "plan_unopened": _unopened(folder, plan),
                **_given(_read(folder, produce.INPUTS_FILE) or {})}
    try:
        validate(board, "storyboard")
    except ValidationError as e:
        raise ValueError(f"{folder / produce.STORYBOARD_FILE} needs fixing: {e}") from None
    brief = _read(folder, produce.BRIEF_FILE) or {}
    inputs = _read(folder, produce.INPUTS_FILE) or {"footage": [], "assets": [], "music": []}
    report = _report(folder)
    built = report is not None
    watch = (report or {}).get("preview")
    preview = folder / watch if isinstance(watch, str) else None      # not a skipped one's reason
    # A build leaves the video's OpenShot project, which stays when the storyboard changes after it.
    ever_built = bool(brief.get("title")) and produce.project_path(folder, brief).is_file()
    scenes, pauses = [], {}     # each recording's pauses, read once
    for n, (scene, key) in enumerate(zip(board["scenes"], scene_keys(board)), start=1):
        visual = scene["visual"]
        span = report["scenes"][n - 1] if report and n <= len(report["scenes"]) else None
        if span:
            seconds = round(span["end"] - span["start"], 6)
        elif visual["type"] == "footage" and not scene.get("narration"):    # as the build will cut its long pauses
            if visual["source"] not in pauses:
                pauses[visual["source"]] = storyboard_edit._timing(folder, _recording(visual, inputs)).get("pauses", [])
            seconds = round(sum(b - a for a, b in kept_pieces(
                *trim_edges(visual["start"], visual["end"], pauses[visual["source"]], 30),
                pauses[visual["source"]], 30)), 6)
        else:
            seconds = scene.get("duration")
        scenes.append({"number": n, "kind": visual["type"], "says": said(scene, folder, inputs),
                       "seconds": seconds, "start": span["start"] if span else None,
                       "source": _source(scene), "over": _over(scene),
                       "text": visual.get("text"),       # a title's words on screen; no other visual has any
                       "key": key, "narration": scene.get("narration"), "caption": scene.get("caption"),
                       "cards": scene.get("cards", []), "broll": scene.get("broll", [])})
    can_undo, can_redo = storyboard_edit.history(folder)
    look = board.get("look")
    return {"title": brief.get("title") or folder.name, "aspect": brief.get("aspect"),
            "target_seconds": brief.get("target_seconds"), "built": built, "ever_built": ever_built,
            "sections": [dict(s, confirmed=s.get("confirmed", False)) for s in board.get("sections", [])],
            "scenes": scenes, "report": report, "version": storyboard_edit.version(folder),
            "preview": str(preview.resolve()) if preview and preview.is_file() else None,
            "can_undo": can_undo, "can_redo": can_redo, "plan": plan, "plan_is_draft": plan_is_draft,
            "plan_unopened": _unopened(folder, plan), **_given(inputs),
            "video": {"spoken_captions": bool(board.get("spoken_captions")), "has_music": "music" in board,
                      "cut_to_beat": bool(board.get("music", {}).get("cut_to_beat")),
                      "look": Path(look["path"]).name if look else None}}


def thumbnail(folder: Path, key: str) -> Path | None:
    """A small JPEG of the picture of the scene with this key, made once: a frame of its recording or clip,
    or its image. None for a title or a graphic, for a key no scene has, and when the file is not there."""
    board = _read(folder, produce.STORYBOARD_FILE)
    inputs = _read(folder, produce.INPUTS_FILE) or {"footage": [], "assets": [], "music": []}
    keys = scene_keys(board) if board else []
    if key not in keys:
        return None
    scene = board["scenes"][keys.index(key)]
    cover = _covered_by(scene)
    visual = {"type": "asset", "path": cover["path"]} if cover else scene["visual"]
    if visual["type"] == "footage":
        recording = _recording(visual, inputs)
        source, at = recording and Path(recording["source"]), min(visual["start"] + 0.3, visual["end"])
    elif visual["type"] == "asset":
        asset = produce._match(visual["path"], inputs["assets"], "path")
        source, at = Path(asset["path"] if asset else visual["path"]), visual.get("start", 0.0) + 0.3
    else:
        return None
    if not source or not source.is_file():
        return None
    digest = hashlib.sha256(json.dumps([visual, str(source)], sort_keys=True).encode()).hexdigest()[:12]
    out = folder / "app_cache" / "thumbs" / f"{digest}.jpg"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    seek = [] if source.suffix.lower() in IMAGE_SUFFIXES else ["-ss", f"{at:.3f}"]
    result = subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y", *seek, "-i", str(source), "-frames:v", "1",
                             "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "4", str(out)], capture_output=True)
    return out if result.returncode == 0 and out.is_file() else None


def looks(folder: Path) -> list[str]:
    """The names of the looks a video can use: the creator's own LUTs, then OpenShot's."""
    inputs = _read(folder, produce.INPUTS_FILE) or {}
    return [Path(look["path"]).name for look in produce._looks(inputs)]


def open_project(folder: Path) -> None:
    """Show a built video's project in OpenShot: in Frameflow's open window, or a new one."""
    print("==> Opening it in OpenShot")
    brief = _read(folder, produce.BRIEF_FILE)
    project = produce.project_path(folder, brief) if brief else None
    if project is None or not project.is_file():
        raise SystemExit("Build the video first: there is no OpenShot project yet.")
    if not EDITORS[DEFAULT].open(project):
        raise SystemExit(f"OpenShot was not found. Open {project} yourself.")


def _changed(folder: Path, change) -> dict:
    """A change made through the app, answered with the storyboard after it, or why it was not made."""
    try:
        notes = change() or []
    except EditError as e:
        return {"refused": str(e), "changed": e.changed}
    return {"described": describe(folder), "notes": notes}


def _answer(method: str, params: dict):
    folder = Path(params["folder"]) if "folder" in params else None
    if method == "videos":
        return videos(Path(params["root"]))
    if method == "describe":
        return describe(folder)
    if method == "thumbnail":
        picture = thumbnail(folder, params["key"])
        return str(picture) if picture else None
    if method == "looks":
        return looks(folder)
    if method == "edit":
        return _changed(folder, lambda: storyboard_edit.edit(folder, params["op"], params["version"],
                                                             params.get("chosen", [])))
    if method == "thinkers":
        return thinkers.found_agents()
    if method == "new_video":
        return str(app_think.new_folder(Path(params["root"]), params["prompt"]))
    if method == "edit_plan":
        app_think.edit_plan(folder, params["fields"])
        return describe(folder)
    if method in ("undo", "redo"):
        return _changed(folder, lambda: getattr(storyboard_edit, method)(folder, params["version"]))
    raise ValueError(f"unknown method {method!r}")


def serve(lines=sys.stdin, out=sys.stdout) -> None:
    """Answer the app's requests until its end of the pipe closes. Pictures are made on two threads of their
    own, so a thumbnail never holds up a change; everything else is answered in the order it came."""
    lock = threading.Lock()

    def reply(request_id, **answer) -> None:
        with lock:
            out.write(json.dumps({"id": request_id, **answer}, ensure_ascii=False) + "\n")
            out.flush()

    def run(request: dict) -> None:
        try:
            reply(request.get("id"), result=_answer(request["method"], request.get("params") or {}))
        except Exception as e:      # the app shows the message; the traceback is for whoever reads stderr
            traceback.print_exc(file=sys.stderr)
            reply(request.get("id"), error=str(e) or type(e).__name__)

    with ThreadPoolExecutor(max_workers=2) as pictures:
        for line in lines:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                reply(None, error=f"not a request: {e}")
                continue
            if request.get("method") == "thumbnail":
                pictures.submit(run, request)
            else:
                run(request)


def main(argv: list[str]) -> int:
    if argv == ["serve"]:
        serve()
        return 0
    if len(argv) == 2 and argv[0] == "open":     # its SystemExit says why on stderr, as a build's error does
        open_project(Path(argv[1]))
        return 0
    try:
        command, path, *rest = argv
        if command == "videos":
            answer = videos(Path(path))
        elif command == "describe":
            answer = describe(Path(path))
        elif command == "thumbnail":
            picture = thumbnail(Path(path), rest[0])
            answer = str(picture) if picture else None
        else:
            raise ValueError(f"unknown command {command!r}: videos, describe or thumbnail")
    except Exception as e:      # an app shows this line; a traceback would tell the creator nothing
        print(json.dumps({"error": str(e) or type(e).__name__}))
        return 1
    print(json.dumps(answer, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    # Requests and answers are UTF-8 whatever the PC's code page: a name typed in Hindi must arrive as typed.
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
