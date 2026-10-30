#!/usr/bin/env python3
"""IR -> OpenShot .osp compiler.

The project skeleton and every clip's default properties come from
openshot_template, which was read off a project OpenShot itself saved. What
varies per project - layers, files, clip timings - is filled in here.

A clip's `reader` block only needs to name the file: libopenshot re-reads
codec, size and duration from the media itself when it opens the clip. The
fields written beside the path are the ones ffprobe can state for certain.

Usage:
    python -m project.compile_osp <ir_project.json> <output.osp>
"""
import argparse
import json
from pathlib import Path

from project.compile_mlt import fps_to_fraction, resource_path, sec_to_frames
from project.media import analyze
from project.openshot_template import CLIP_DEFAULTS, build_root, keyframe, layer, ratio
from project.sidecar import write_sidecar
from project.validate import validate


def _compilable_tracks(ir: dict) -> list[dict]:
    """Every track, in IR order - bottom to top, as OpenShot's layers are.

    Refused rather than guessed at, for the same reasons as the MLT compiler:
    an audio track has not been checked against a project OpenShot wrote, and
    a clip with no source is a caption or generated visual with no file to
    point a reader at.
    """
    tracks = ir["tracks"]
    audio = [t["id"] for t in tracks if t["type"] == "audio"]
    if audio:
        raise NotImplementedError(
            f"audio tracks are not compiled for OpenShot yet: {', '.join(audio)}. "
            "How OpenShot represents one has not been checked against a project it saved."
        )
    sourceless = [c["id"] for t in tracks for c in t["clips"] if "source" not in c]
    if sourceless:
        raise NotImplementedError(
            f"clips with no source media are not compiled yet: {', '.join(sourceless)}. "
            "Captions and generated graphics need a media file for OpenShot to read."
        )
    if not any(t["clips"] for t in tracks):
        raise ValueError("no track has any clips - nothing to compile")
    return tracks


def _reader(path: str, info) -> dict:
    fps_num, fps_den = fps_to_fraction(info.nominal_fps)
    return {
        "type": "FFmpegReader",
        "path": path,
        "has_video": True,
        "has_audio": info.has_audio,
        "has_single_image": False,
        "width": info.width,
        "height": info.height,
        "fps": {"num": fps_num, "den": fps_den},
        "duration": info.duration_seconds,
        "video_length": sec_to_frames(info.duration_seconds, info.nominal_fps),
        "pixel_ratio": {"num": 1, "den": 1},
        "display_ratio": ratio(info.width, info.height),
    }


def _curve(level: float, fade_in: float, fade_out: float,
           first: int, last: int, fps: float) -> dict:
    """An alpha or volume keyframe as OpenShot's Fade menu writes it: in source
    frames counted from 1, from nothing at the first frame, to nothing at the last."""
    if not fade_in and not fade_out:
        return keyframe(level)
    # Fades longer than the clip share it, as OpenShot's own Fade In and Out does.
    squeeze = min(1.0, (last - first) / ((fade_in + fade_out) * fps))
    points = []
    if fade_in:
        points += [(first, 0.0), (first + fade_in * fps * squeeze, level)]
    if fade_out:
        points += [(last - fade_out * fps * squeeze, level), (last, 0.0)]
    return {"Points": [keyframe(y, x=float(x))["Points"][0] for x, y in points]}


def _levels(clip: dict, in_f: int, length_f: int, fps: float) -> dict:
    first, last = in_f + 1, in_f + length_f + 1
    fade_in, fade_out = clip.get("fade_in", {}), clip.get("fade_out", {})
    return {
        "alpha": _curve(clip.get("opacity", 1.0), fade_in.get("picture", 0),
                        fade_out.get("picture", 0), first, last, fps),
        "volume": _curve(10 ** (clip.get("volume_db", 0.0) / 20), fade_in.get("sound", 0),
                         fade_out.get("sound", 0), first, last, fps),
    }


def build_osp(ir: dict, project_dir: Path) -> dict:
    """Compile the IR. Sources are written relative to project_dir where they
    can be, as OpenShot writes them itself."""
    validate(ir, "ir")
    project = ir["project"]
    fps = project["fps"]
    fps_num, fps_den = fps_to_fraction(fps)
    tracks = _compilable_tracks(ir)

    # One file entry per distinct source, shared by every clip cut from it.
    files, sources = [], {}
    for track in tracks:
        for clip in track["clips"]:
            if clip["source"] in sources:
                continue
            info = analyze(clip["source"])
            reader = _reader(resource_path(clip["source"], project_dir), info)
            file_id = f"FFFILE{len(files) + 1:04d}"
            files.append({**reader, "media_type": "video", "id": file_id})
            # Frames at the project's rate, as the MLT compiler counts them.
            sources[clip["source"]] = (file_id, reader,
                                       sec_to_frames(info.duration_seconds, fps))

    clips, end = [], 0.0
    for index, track in enumerate(tracks):
        for clip in sorted(track["clips"], key=lambda c: c["timeline_start"]):
            file_id, reader, frames = sources[clip["source"]]
            start_f = sec_to_frames(clip["timeline_start"], fps)
            in_f = sec_to_frames(clip.get("source_in", 0.0), fps)
            # The out point comes from the timeline length, not source_out
            # rounded on its own, so a clip fills exactly its slot.
            length_f = sec_to_frames(clip["timeline_duration"], fps)
            if length_f <= 0:
                raise ValueError(f"clip {clip['id']!r} rounds to zero frames at {fps} fps")
            if in_f + length_f == frames + 1:
                # Rounding in and length separately can land one frame past
                # the end of a clip that runs to the end of its source.
                length_f -= 1
            if in_f + length_f > frames:
                raise ValueError(
                    f"clip {clip['id']!r} ends at source frame {in_f + length_f}, beyond the "
                    f"{frames} frames of {clip['source']}"
                )
            clips.append({
                **json.loads(json.dumps(CLIP_DEFAULTS)),
                "id": f"FFCLIP{len(clips) + 1:04d}",
                "layer": layer(index, track["id"])["number"],
                "position": start_f / fps,
                "start": in_f / fps,
                "end": (in_f + length_f) / fps,
                "duration": reader["duration"],
                "file_id": file_id,
                "title": Path(clip["source"]).name,
                "reader": reader,
                **_levels(clip, in_f, length_f, fps),
            })
            end = max(end, (start_f + length_f) / fps)

    osp = build_root(project["width"], project["height"], fps_num, fps_den, end)
    osp["files"] = files
    osp["clips"] = clips
    osp["layers"] = [layer(index, track["id"]) for index, track in enumerate(tracks)]
    return osp


def compile_file(ir_path: Path | str, output_path: Path | str) -> Path:
    """Compile an IR file to an .osp, with the sidecar beside it."""
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8"))
    output_path = Path(output_path)
    osp = build_osp(ir, output_path.resolve().parent)
    output_path.write_text(json.dumps(osp, indent=2) + "\n", encoding="utf-8")
    # OpenShot has nowhere to keep provenance or track types, so they live
    # beside the project, exactly as they do for Shotcut.
    write_sidecar(output_path, ir)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a Frameflow IR into an OpenShot project.")
    parser.add_argument("ir_project")
    parser.add_argument("output")
    args = parser.parse_args()
    print(f"wrote {compile_file(args.ir_project, args.output)}")


if __name__ == "__main__":
    main()
