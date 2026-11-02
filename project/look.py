#!/usr/bin/env python3
"""Look at the result: frames rendered through OpenShot's own engine after a
build, checked the way verify_cuts listens to every join.

  - Black frames: the picture without its captions, just after every cut on
    the main track, in the middle of every clip there, and wherever the main
    track is empty - a gap a title does not fill shows as black.
  - Captions off screen: each caption line drawn alone, in its last frame,
    when all its words are up (in its middle, a line moved right half off the
    frame still fitted). One that reaches the frame's edge runs off it; one
    that shows nothing is off the screen altogether.
  - Graphics over a face: each title, card or lower third drawn alone, in its
    middle, against the faces OpenCV finds in the picture under it there.

Only what is wrong is reported; the creator decides what to do about it.
"""
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from project import openshot_build
from project.change_agent import _clock
from project.operations import main_index

DARK = 24               # a pixel with no channel above this is black, as are drawn pixels below it
BLACK_SHARE = 0.995     # a frame this much black is a black frame; a title on black is not
EDGE = 2                # pixels: a caption drawn this close to the frame's edge runs off it
COVERED = 0.1           # a graphic over this much of a face covers it: a lower third over a mouth was 18%
_PICTURE = ("video", "screen", "broll", "graphics", "captions")


class LookError(Exception):
    pass


@dataclass
class Look:
    at: float           # seconds into the video
    kind: str           # "black", "caption" or "graphic"
    clip: dict
    why: str = ""       # for a black frame: where it is


def is_black(frame: np.ndarray) -> bool:
    return (frame.max(axis=2) <= DARK).mean() >= BLACK_SHARE


def edges(frame: np.ndarray) -> list[str]:
    """Which edges of the frame something drawn reaches."""
    drawn = frame.max(axis=2) > DARK
    return [side for side, strip in (("left", drawn[:, :EDGE]), ("right", drawn[:, -EDGE:]),
                                     ("top", drawn[:EDGE]), ("bottom", drawn[-EDGE:])) if strip.any()]


def covered(frame: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """How much of box (x, y, width, height) has something drawn on it."""
    x, y, w, h = box
    return float((frame[y:y + h, x:x + w].max(axis=2) > DARK).mean())


def where(ir: dict) -> list[Look]:
    """Every moment to look at, and what for."""
    main = main_index(ir)
    clips = sorted(ir["tracks"][main]["clips"], key=lambda c: c["timeline_start"]) if main is not None else []
    end = max((c["timeline_start"] + c["timeline_duration"] for t in ir["tracks"] if t["type"] in _PICTURE
               for c in t["clips"]), default=0.0)
    looks = []
    for n, clip in enumerate(clips):
        if n:
            looks.append(Look(clip["timeline_start"], "black", clip, "just after a cut"))
        looks.append(Look(clip["timeline_start"] + clip["timeline_duration"] / 2, "black", clip))
    covered_until, gaps = 0.0, []
    for clip in clips + [{"timeline_start": end, "timeline_duration": 0.0}]:
        if clip["timeline_start"] - covered_until > 0.5 / ir["project"]["fps"]:
            gaps.append((covered_until, clip["timeline_start"]))
        covered_until = max(covered_until, clip["timeline_start"] + clip["timeline_duration"])
    looks += [Look((a + b) / 2, "black", {}, "where the main track has nothing") for a, b in gaps]
    for track in ir["tracks"]:
        # A graphic is all there in its middle; a caption only in its last frame, its words popping in as said.
        if track["type"] == "graphics":
            looks += [Look(c["timeline_start"] + c["timeline_duration"] / 2, "graphic", c) for c in track["clips"]]
        elif track["type"] == "captions":
            looks += [Look(c["timeline_start"] + c["timeline_duration"] - 1 / ir["project"]["fps"], "caption", c)
                      for c in track["clips"]]
    return looks


def _faces(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    import cv2
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    side = gray.shape[0] // 16
    return [tuple(int(v) for v in f) for f in detector.detectMultiScale(gray, 1.1, 5, minSize=(side, side))]


def check(project: Path | str, ir: dict) -> tuple[list[str], int]:
    """(what is wrong in the picture, how many frames were looked at) for an OpenShot project built
    from `ir`. Raises LookError when OpenShot's engine is not there to draw it."""
    import cv2
    if openshot_build.install_dir() is None:
        raise LookError("OpenShot is not installed")
    project = Path(project).resolve()
    # compile_osp gives each track a layer, bottom up, in the IR's order.
    layers = sorted(layer["number"] for layer in json.loads(project.read_text(encoding="utf-8"))["layers"])
    by_type: dict[str, list[int]] = {}
    for track, number in zip(ir["tracks"], layers):
        by_type.setdefault(track["type"], []).append(number)
    # A black picture is black under a caption too, so captions are left out of it.
    drawn = {"black": [n for t, n in zip(ir["tracks"], layers) if t["type"] != "captions"],
             "caption": by_type.get("captions"), "graphic": by_type.get("graphics")}
    under = [n for kind in ("video", "screen", "broll") for n in by_type.get(kind, [])]
    fps = ir["project"]["fps"]
    looks = where(ir)
    with tempfile.TemporaryDirectory() as tmp:
        jobs = []
        for n, lk in enumerate(looks):
            frame = int(lk.at * fps + 1e-6) + 1
            jobs.append({"frame": frame, "layers": drawn[lk.kind], "out": f"{tmp}/{n}.png"})
            if lk.kind == "graphic":
                jobs.append({"frame": frame, "layers": under, "out": f"{tmp}/{n}-under.png"})
        (Path(tmp) / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
        result = openshot_build.run_script(Path(__file__).parent / "openshot_frames.py", str(project),
                                           str(Path(tmp) / "jobs.json"), cwd=project.parent)
        if result.returncode != 0:
            raise LookError(f"OpenShot could not draw the project's frames: {result.stderr[-2000:]}")
        problems = []
        for n, lk in enumerate(looks):
            frame = cv2.imread(f"{tmp}/{n}.png")
            if frame is None:
                raise LookError(f"OpenShot drew no frame at {_clock(lk.at)}")
            label = f' "{lk.clip["text"]}"' if lk.clip.get("text") else ""
            if lk.kind == "black" and is_black(frame):
                problems.append(f"{_clock(lk.at)}: black" + (f", {lk.why}" if lk.why else ""))
            elif lk.kind == "caption" and not (frame.max(axis=2) > DARK).any():
                problems.append(f"{_clock(lk.at)}: the caption{label} shows nothing; it is off the screen")
            elif lk.kind == "caption" and edges(frame):
                problems.append(f"{_clock(lk.at)}: the caption{label} runs off the {' and '.join(edges(frame))} edge")
            elif lk.kind == "graphic":
                picture = cv2.imread(f"{tmp}/{n}-under.png")
                worst = max((covered(frame, box) for box in (_faces(picture) if picture is not None else [])),
                            default=0.0)
                if worst >= COVERED:
                    problems.append(f"{_clock(lk.at)}: the graphic{label} covers {worst:.0%} of a face")
    return problems, len(jobs)


def report(project: Path | str, ir: dict) -> None:
    """Look at a project just built and say what is wrong, as a build's step."""
    print("==> Looking at the picture", flush=True)
    try:
        problems, looked = check(project, ir)
    except LookError as e:
        print(f"    skipped: {e}")
        return
    print(f"    {looked} frames looked at" + ("; nothing wrong" if not problems else ""))
    for problem in problems:
        print(f"    ! {problem}")
