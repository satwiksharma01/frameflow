#!/usr/bin/env python3
"""Keep the speaker in a vertical crop.

A 9:16 crop of a landscape recording shows a narrow window of it. This finds
the face over time and turns it into a few smooth moves of that window - the
way a camera operator reframes when someone leans, not a follow that wobbles
with every detection. The moves are keyframes on each clip's position, in
seconds of the recording, so the creator can change them in OpenShot and an
edit keeps them.

Faces come from OpenCV's frontal-face detector, which ships with OpenCV, on
frames sampled four times a second. The window is kept inside the recording's
picture, measured with FFmpeg's cropdetect, so black bars recorded into the
file never come into view.
"""
import statistics
import subprocess
from collections import Counter
from pathlib import Path

from project.media import _find_tool, analyze
from project.operations import main_index

SAMPLE_FPS = 4
ANALYSIS_WIDTH = 640
SMOOTH_SECONDS = 2.0    # detections are a median over this long, to ignore misses and nods
DEAD_ZONE = 0.25        # of the window's width the face may drift from its middle before it moves
HOLD_SECONDS = 2.0      # the window holds still at least this long after a move
MOVE_SECONDS = 0.6      # how long a move takes


def picture_area(video: Path | str) -> tuple[int, int]:
    """The left and right edges of the recording's picture, in source pixels,
    leaving out black bars recorded into the file."""
    result = subprocess.run(
        [_find_tool("ffmpeg"), "-hide_banner", "-i", str(video), "-vf", "fps=1,cropdetect=limit=24:round=2:reset=0",
         "-f", "null", "-"], capture_output=True, text=True, errors="replace")
    crops = [line.split("crop=")[1].split()[0] for line in result.stderr.splitlines() if "crop=" in line]
    width = analyze(video).width
    if not crops:
        return 0, width
    w, _, x, _ = (int(v) for v in Counter(crops).most_common(1)[0][0].split(":"))
    return x, x + w


def face_centres(video: Path | str) -> list[tuple[float, float | None]]:
    """(seconds, the face's centre in source pixels) at SAMPLE_FPS; None where no face is found."""
    import cv2
    import numpy as np

    info = analyze(video)
    height = round(info.height * ANALYSIS_WIDTH / info.width / 2) * 2
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    process = subprocess.Popen(
        [_find_tool("ffmpeg"), "-v", "error", "-i", str(video), "-vf",
         f"fps={SAMPLE_FPS},scale={ANALYSIS_WIDTH}:{height},format=gray", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE)
    centres, size, n = [], ANALYSIS_WIDTH * height, 0
    while len(chunk := process.stdout.read(size)) == size:
        frame = np.frombuffer(chunk, np.uint8).reshape(height, ANALYSIS_WIDTH)
        faces = detector.detectMultiScale(frame, 1.1, 5, minSize=(height // 10, height // 10))
        x = None
        if len(faces):
            fx, _, fw, _ = max(faces, key=lambda f: f[2] * f[3])       # the nearest person
            x = float((fx + fw / 2) * info.width / ANALYSIS_WIDTH)
        centres.append((n / SAMPLE_FPS, x))
        n += 1
    process.wait()
    return centres


def crop_keys(centres: list[tuple[float, float | None]], frame: tuple[int, int],
              source: tuple[int, int], area: tuple[int, int]) -> list[dict]:
    """Keyframes for the picture's offset (fractions of the frame's width, as the
    IR keeps positions) that keep the face in the window and move only when it
    has drifted out of the middle of it."""
    (width, height), (source_w, source_h), (left, right) = frame, source, area
    scale = max(width / source_w, height / source_h)
    half = width / scale / 2                                   # the window's half-width, in source pixels
    lowest, highest = left + half, right - half
    if lowest > highest:                                       # the picture is narrower than the window
        lowest = highest = (left + right) / 2

    def offset(centre: float) -> float:
        """Where the picture goes, so the window is centred on `centre`."""
        return round(float(source_w / 2 - min(max(centre, lowest), highest)) * scale / width, 6)

    seen = [(t, x) for t, x in centres if x is not None]
    if not seen:
        return [{"at": 0.0, "value": offset((left + right) / 2)}]
    window = round(SMOOTH_SECONDS * SAMPLE_FPS / 2)
    xs = [x for _, x in seen]
    smoothed = [(t, statistics.median(xs[max(0, i - window):i + window + 1])) for i, (t, _) in enumerate(seen)]

    # Stretches where the face stays near where it has been, each framed on the
    # middle of where the face was in it - not wherever it happened to start.
    holds = [(smoothed[0][0], [smoothed[0][1]])]
    for t, x in smoothed[1:]:
        start, xs_held = holds[-1]
        if abs(x - statistics.median(xs_held)) > DEAD_ZONE * 2 * half and t - start >= HOLD_SECONDS:
            holds.append((t, [x]))
        else:
            xs_held.append(x)

    keys = [{"at": 0.0, "value": offset(statistics.median(holds[0][1]))}]
    for t, xs_held in holds[1:]:
        value = offset(statistics.median(xs_held))
        if value != keys[-1]["value"]:                 # both ends of the picture look the same
            keys += [{"at": round(t, 6), "value": keys[-1]["value"]},
                     {"at": round(t + MOVE_SECONDS, 6), "value": value}]
    return keys


def _value(keys: list[dict], t: float) -> float:
    """The offset at time t, moving in a straight line between keyframes."""
    before = [k for k in keys if k["at"] <= t]
    after = [k for k in keys if k["at"] > t]
    if not before or not after:
        return (before or after)[-1 if before else 0]["value"]
    a, b = before[-1], after[0]
    return round(a["value"] + (b["value"] - a["value"]) * (t - a["at"]) / (b["at"] - a["at"]), 6)


def clip_offset(keys: list[dict], start: float, end: float) -> float | list[dict]:
    """The keyframes for one clip playing start..end of the recording: one value
    if the window holds still there, otherwise keyframes from its first frame."""
    inside = [k for k in keys if start < k["at"] < end]
    path = [{"at": start, "value": _value(keys, start)}] + inside
    if _value(keys, end) != path[-1]["value"]:
        path.append({"at": end, "value": _value(keys, end)})
    if len({k["value"] for k in path}) == 1:
        return path[0]["value"]
    return path


def follow(ir: dict, keys: list[dict]) -> int:
    """Give every filled main-track clip the window's moves for its span. Changes
    `ir` in place; returns how many clips move during their span."""
    moving = 0
    for clip in ir["tracks"][main_index(ir)]["clips"]:
        transform = clip.get("transform")
        if not (transform and transform.get("fill")):
            continue
        x = clip_offset(keys, clip["source_in"], clip["source_out"])
        moving += isinstance(x, list)
        if x:
            transform["position"] = {"x": x}
        else:
            transform.pop("position", None)
    return moving
