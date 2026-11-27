#!/usr/bin/env python3
"""The agent's eyes on a clip: where it cuts, what it looks like across its length, how good it looks
moment by moment, and where someone speaks.

A study is made once per clip and kept beside the video's other files, so the agent looks at one sheet
of frames instead of the whole clip, and opens a closer look only where it needs one. Nothing here calls
a model to describe a picture: the agent does that from the sheet.

    python -m project.eyes study <clip> <out dir>
    python -m project.eyes sheet <clip> --from S --to E [--per-second N] [--out PATH]
    python -m project.eyes install          (the speech model, 2.3 MB)
"""
import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np

from project import vad
from project.media import _find_tool, probe
from project.validate import validate

SCENE_THRESHOLD = 0.3   # ffmpeg's scene score above which a frame starts a new shot
MAX_FRAMES = 60         # frames on a clip's sheet at most
MIN_STEP = 0.5          # seconds between frames at least
SOFT_SHARE = 0.4        # sharper than this share of the clip's median sharpness, or soft
DARK = 40               # mean luma under this is dark
BLOWN = 220             # and over this, blown out
SHAKY = 30.0            # mean change between frames (0-255, at 64 px wide) over this is shaky
STUDY = "study.json"
SHEET = "sheet.jpg"


class EyesError(Exception):
    pass


def stamp(path: Path) -> dict:
    """A recording as it was given: where, its size and when it last changed, to tell it again unchanged."""
    path, stat = path.resolve(), path.stat()
    return {"path": path.as_posix(), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def step_for(duration: float, frames: int = MAX_FRAMES, least: float = MIN_STEP) -> float:
    return max(least, duration / frames)


def _times(duration: float, step: float) -> list[float]:
    """Every `step` seconds from the start, and at least the first frame."""
    return [round(i * step, 3) for i in range(max(1, math.ceil(duration / step - 1e-9)))]


def cuts(clip: Path) -> list[float]:
    """Where a new shot starts, in seconds, by ffmpeg's scene score."""
    result = subprocess.run([_find_tool("ffmpeg"), "-hide_banner", "-i", str(clip), "-filter:v",
                             f"select='gt(scene,{SCENE_THRESHOLD})',showinfo", "-f", "null", "-"],
                            capture_output=True, text=True, errors="replace")
    return [round(float(t), 3) for t in re.findall(r"pts_time:([\d.]+)", result.stderr)]


def frames_at(clip: Path, times: list[float]) -> list[np.ndarray]:
    """The clip's frames at these seconds, upright as a player shows them."""
    import cv2
    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        raise EyesError(f"cannot read the frames of {clip}")
    frames: list[np.ndarray] = []
    try:
        for t in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = capture.read()
            if not ok:
                if not frames:
                    raise EyesError(f"no frame at {t:.1f}s in {clip}")
                frame = frames[-1].copy()       # just past the last frame: the last one again
            frames.append(frame)
    finally:
        capture.release()
    return frames


def measures(frames: list[np.ndarray]) -> list[dict]:
    """How sharp, how bright and how much changed since the frame before, for each frame."""
    import cv2
    found, before = [], None
    for frame in frames:
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(grey, (64, max(1, round(64 * grey.shape[0] / grey.shape[1]))))
        motion = 0.0 if before is None else float(np.abs(small.astype(np.int16) - before.astype(np.int16)).mean())
        before = small
        found.append({"sharp": round(float(cv2.Laplacian(grey, cv2.CV_64F).var()), 1),
                      "bright": round(float(grey.mean()), 1), "motion": round(motion, 2)})
    return found


def flags(samples: list[dict], start: float, end: float) -> list[str]:
    """What is wrong with most of the frames from `start` to `end`: soft, dark, blown or shaky."""
    inside = [s for s in samples if start - 1e-6 <= s["t"] <= end + 1e-6]
    if not inside:
        return []
    median = float(np.median([s["sharp"] for s in samples]))

    def most(wrong) -> bool:
        return 2 * sum(1 for s in inside if wrong(s)) > len(inside)

    found = []
    if median > 0 and most(lambda s: s["sharp"] < SOFT_SHARE * median):
        found.append("soft")
    if most(lambda s: s["bright"] < DARK):
        found.append("dark")
    if most(lambda s: s["bright"] > BLOWN):
        found.append("blown")
    if most(lambda s: s["motion"] > SHAKY):
        found.append("shaky")
    return found


def draw_sheet(frames: list[np.ndarray], labels: list[str], out: Path, across: int = 10, width: int = 240) -> Path:
    """The frames tiled `across` a row, each with its label in its corner."""
    import cv2
    font, scale = cv2.FONT_HERSHEY_SIMPLEX, 0.5
    tiles = []
    for frame, label in zip(frames, labels):
        tile = cv2.resize(frame, (width, max(1, round(frame.shape[0] * width / frame.shape[1]))))
        (w, h), base = cv2.getTextSize(label, font, scale, 1)
        cv2.rectangle(tile, (0, 0), (w + 8, h + base + 8), (0, 0, 0), -1)
        cv2.putText(tile, label, (4, h + 4), font, scale, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(tile)
    height = max(t.shape[0] for t in tiles)
    blank = np.zeros((height, width, 3), np.uint8)
    tiles = [np.vstack([t, blank[:height - t.shape[0]]]) if t.shape[0] < height else t for t in tiles]
    rows = [np.hstack(tiles[i:i + across] + [blank] * (across - len(tiles[i:i + across])))
            for i in range(0, len(tiles), across)]
    ok, encoded = cv2.imencode(".jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise EyesError(f"could not draw {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encoded.tobytes())      # not cv2.imwrite, which fails on paths it cannot encode
    return out


def closer(clip: Path, start: float, end: float, out: Path, per_second: float = 4.0) -> Path:
    """A sheet of one stretch of the clip, `per_second` frames a second: a closer look where the clip's sheet
    is too coarse to see when something happens."""
    step = 1 / per_second
    times = [round(start + i * step, 3) for i in range(max(1, math.ceil((end - start) / step - 1e-9)))]
    return draw_sheet(frames_at(Path(clip), times), [f"{t:.1f}s" for t in times], Path(out))


def moment_problems(name: str, moments: list[dict], duration: float) -> list[str]:
    """What is wrong with the agent's moments of one clip, each naming the clip and the moment."""
    problems = []
    for n, m in enumerate(moments, start=1):
        if m["end"] <= m["start"]:
            problems.append(f"{name}, moment {n}: it ends at {m['end']} s, not after it starts at {m['start']} s")
        if m["start"] < 0 or m["end"] > duration + 0.05:
            problems.append(f"{name}, moment {n}: {m['start']}-{m['end']} s is outside the clip, which is "
                            f"{duration:.2f} s long")
        if n > 1 and m["start"] < moments[n - 2]["end"] - 1e-6:
            problems.append(f"{name}, moment {n}: it starts at {m['start']} s, before moment {n - 1} ends at "
                            f"{moments[n - 2]['end']} s; moments go in order without overlapping")
    return problems


def shot_lines(name: str, study: dict, moments: list[dict] | None) -> list[str]:
    """The clip in the shot list: a line per moment, or one line from its study when it has no moments."""
    if moments:
        return [f"- {name} {m['start']:.1f}–{m['end']:.1f} s · " + " · ".join(
                    [m["framing"], m["what"], *([m["notes"]] if m.get("notes") else []),
                     ", ".join(flags(study["samples"], m["start"], m["end"])) or "sharp"])
                for m in moments]
    found = ", ".join(flags(study["samples"], 0.0, study["duration"])) or "sharp"
    return [f"- {name}, {study['duration']:.1f} s · {len(study['cuts'])} cut(s) · "
            f"speech {study['speech_seconds']:.1f} s · {found}"]


def study(clip: Path, out_dir: Path, speech: list[dict] | None = None) -> dict:
    """The clip's study, written to `out_dir` with its sheet; one already there for the same file is kept.
    `speech`, when given, is where someone speaks as already measured (a recording's transcript), not measured again."""
    clip, out_dir = Path(clip), Path(out_dir)
    given = stamp(clip)
    kept = out_dir / STUDY
    if kept.is_file():
        old = json.loads(kept.read_text(encoding="utf-8"))
        if old.get("stamp") == given and (old.get("speech_measured") or (speech is None and not vad.installed())):
            return old      # made again once the speech model is there to measure what it could not
    info = probe(clip)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise EyesError(f"{clip} has no picture to study")
    duration = float(info["format"]["duration"])
    step = step_for(duration)
    times = _times(duration, step)
    frames = frames_at(clip, times)
    out_dir.mkdir(parents=True, exist_ok=True)
    draw_sheet(frames, [f"{t:.1f}s" for t in times], out_dir / SHEET)
    sound = any(s.get("codec_type") == "audio" for s in streams)
    heard = speech if speech is not None else vad.speech(clip) if sound and vad.installed() else []
    found = {"source": clip.resolve().as_posix(), "stamp": given, "duration": round(duration, 3),
             "width": int(frames[0].shape[1]), "height": int(frames[0].shape[0]),
             "fps": round(float(Fraction(video.get("r_frame_rate", "0/1"))), 3) if video.get("r_frame_rate") != "0/0" else 0.0,
             "cuts": cuts(clip), "step": round(step, 3),
             "samples": [{"t": t, **m} for t, m in zip(times, measures(frames))],
             "speech": heard, "speech_seconds": round(sum(r["end"] - r["start"] for r in heard), 3),
             "speech_measured": speech is not None or vad.installed() or not sound, "sheet": SHEET}
    validate(found, "study")
    kept.write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Study a clip for the agent's eyes.")
    command = parser.add_subparsers(dest="command", required=True)
    one = command.add_parser("study", help="cuts, a sheet of frames, quality and speech, into a folder")
    one.add_argument("clip", type=Path)
    one.add_argument("out", type=Path)
    command.add_parser("install", help="fetch the speech model (Silero VAD, 2.3 MB)")
    look = command.add_parser("sheet", help="a closer look: a sheet of one stretch of a clip")
    look.add_argument("clip", type=Path)
    look.add_argument("--from", dest="start", type=float, required=True, help="seconds")
    look.add_argument("--to", dest="end", type=float, required=True, help="seconds")
    look.add_argument("--per-second", type=float, default=4.0, help="frames a second (4)")
    look.add_argument("--out", type=Path, help="where to write it (by default the system's temporary folder, "
                                                 "never beside the clip)")
    args = parser.parse_args()
    try:
        if args.command == "install":
            print(vad.install())
        elif args.command == "sheet":
            out = args.out or Path(tempfile.gettempdir()) / f"closer-{args.clip.stem}-{args.start:g}-{args.end:g}.jpg"
            print(closer(args.clip, args.start, args.end, out, args.per_second))
        else:
            found = study(args.clip, args.out)
            print(f"{args.clip.name}: {found['duration']:.1f}s, {len(found['cuts'])} cut(s), "
                  f"{len(found['samples'])} frames on {args.out / SHEET}, {found['speech_seconds']:.1f}s of speech")
    except (EyesError, vad.VadError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
