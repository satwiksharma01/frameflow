#!/usr/bin/env python3
"""B-roll: the creator's own images and clips over the main track.

What is said carries on underneath, so a B-roll clip's own sound is turned
right down. Each one fills the frame, because a clip fitted inside it would let
the speaker show around it, and an image gets the same slow push in as an image
scene. They sit on a B-roll track just above the main track, below graphics and
captions, as ordinary clips the creator can move, trim or delete.
"""
import hashlib
from pathlib import Path

from project.cutpoints import frame_align
from project.media import IMAGE_SUFFIXES, MediaError, analyze, still_to_clip

TRACK_ID = "B-roll"
# Inaudible, but still a level OpenShot and Frameflow read back (a true mute is not one yet).
MUTED_DB = -60.0


def place(ir: dict, items: list[dict], main: int) -> list[str]:
    """Put each item - {"label", "path", "at" (timeline seconds), "duration", "start"} - on the
    B-roll track above track `main`, stopping at the end of the video. Changes `ir` in place;
    returns what was wrong instead. Images keep their own path until make_stills."""
    fps = ir["project"]["fps"]
    end = max(c["timeline_start"] + c["timeline_duration"] for c in ir["tracks"][main]["clips"])
    track = next((t for t in ir["tracks"] if t["type"] == "broll"), None)
    if track is None:
        track = {"id": TRACK_ID, "type": "broll", "clips": []}
        ir["tracks"].insert(main + 1, track)
    problems = []
    for item in items:
        path, label = Path(item["path"]), item["label"]
        at = round(frame_align(item["at"], fps), 6)
        length = round(frame_align(min(item["duration"], end - at), fps), 6)
        clash = [c for c in track["clips"]
                 if c["timeline_start"] < at + length and at < c["timeline_start"] + c["timeline_duration"]]
        if clash:
            problems.append(f"{label}: it would overlap the B-roll already at "
                            f"{clash[0]['timeline_start']:.2f}s on the timeline; move or shorten it")
            continue
        clip = {"id": "", "source": path.resolve().as_posix(), "source_in": 0.0, "source_out": length,
                "timeline_start": at, "timeline_duration": length}
        if path.suffix.lower() in IMAGE_SUFFIXES:
            if not path.is_file():
                problems.append(f"{label}: {path} is not there")
                continue
        else:
            try:
                info = analyze(path)
            except MediaError:
                problems.append(f"{label}: {path} is not there, or is not a video")
                continue
            start = round(frame_align(item.get("start", 0.0), fps), 6)
            if start + length > info.duration_seconds + 1e-3:
                problems.append(f"{label}: {path.name} has {max(0.0, info.duration_seconds - start):.1f}s "
                                f"from {start:.1f}s, but it needs {length:.1f}s")
                continue
            clip.update(source_in=start, source_out=round(start + length, 6))
            if info.has_audio:
                clip["volume_db"] = MUTED_DB
        clip["transform"] = {"fill": True}
        track["clips"].append(clip)
    track["clips"].sort(key=lambda c: c["timeline_start"])
    for n, clip in enumerate(track["clips"], start=1):
        clip["id"] = f"clip{n}"
    if not track["clips"]:
        ir["tracks"].remove(track)
    return problems


def make_stills(ir: dict, folder: Path) -> None:
    """Turn every image on the B-roll track into a clip with a slow push in, cached in stills/.
    Changes `ir` in place."""
    project = ir["project"]
    for track in ir["tracks"]:
        if track["type"] != "broll":
            continue
        for clip in track["clips"]:
            if Path(clip["source"]).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            length = clip["timeline_duration"]
            key = f"{clip['source']}|{project['width']}x{project['height']}|{project['fps']}|{length}"
            mp4 = folder / "stills" / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.mp4"
            if not mp4.exists():
                still_to_clip(clip["source"], mp4, project["width"], project["height"], project["fps"], length)
            clip.update(source=mp4.resolve().as_posix(), source_in=0.0, source_out=length)
