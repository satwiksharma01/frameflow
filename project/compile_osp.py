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
from project.media import analyze, probe
from project.openshot_template import (CLIP_DEFAULTS, COLOR_MAP, CURVES, SCALE_CROP, build_root, keyframe,
                                       layer, location_units, ratio)
from project.sidecar import write_sidecar
from project.validate import validate


def _compilable_tracks(ir: dict) -> list[dict]:
    """Every track, in IR order - bottom to top, as OpenShot's layers are.

    OpenShot has no audio tracks as such: an audio track is a layer of sound
    files, which draw nothing, so it may sit anywhere in the stack. A clip with
    no source is refused: it is a caption or generated visual with no file to
    point a reader at (hyperframes.render_generated gives it one first).
    """
    tracks = ir["tracks"]
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


def _framing(clip: dict, reader: dict, width: int, height: int, fps: float) -> dict:
    """A filled clip's scale mode and location curves. Keyframes count source frames from 1."""
    transform = clip.get("transform") or {}
    if not transform.get("fill"):
        return {}
    framing: dict = {"scale": SCALE_CROP}
    for axis, unit in zip("xy", location_units(width, height, reader["width"], reader["height"])):
        offset = transform.get("position", {}).get(axis, 0.0)
        if isinstance(offset, list):
            framing[f"location_{axis}"] = {"Points": [
                {**keyframe(k["value"] * unit, x=float(round(k["at"] * fps) + 1))["Points"][0],
                 "interpolation": CURVES[k.get("curve", "smooth")]} for k in offset]}
        else:
            framing[f"location_{axis}"] = keyframe(offset * unit)
    return framing


def _effects(clip: dict, clip_id: str, project_dir: Path) -> list[dict]:
    """The clip's effects as OpenShot's own: a LUT is its Color Map / Lookup effect."""
    effects = []
    for n, effect in enumerate(clip.get("effects", []), start=1):
        if effect["type"] != "lut":
            raise NotImplementedError(f"clip {clip['id']!r}: the {effect['type']!r} effect is not compiled yet")
        path = effect["params"]["path"]
        effects.append({**json.loads(json.dumps(COLOR_MAP)), "id": f"{clip_id}E{n}",
                        # An empty path is OpenShot's "None": the look switched off.
                        "lut_path": resource_path(path, project_dir) if path else "",
                        "intensity": keyframe(effect["params"].get("intensity", 1.0))})
    return effects


def _audio_reader(path: str, source: str, fps: float) -> tuple[dict, float]:
    """A sound file's reader, with the fields libopenshot gives one itself.

    Unlike a video's, these are not optional: a sound file's reader without
    its stream index, timebase, channel layout and frame count plays silence
    (checked by rendering through libopenshot 1.0.1).
    """
    data = probe(source)
    stream = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
    if stream is None:
        raise ValueError(f"{source} has no audio stream")
    duration = float(stream.get("duration") or data["format"]["duration"])
    channels = int(stream.get("channels", 2))
    tb_num, tb_den = (int(x) for x in stream.get("time_base", "1/48000").split("/"))
    fps_num, fps_den = fps_to_fraction(fps)
    return {
        "type": "FFmpegReader",
        "path": path,
        "has_video": False,
        "has_audio": True,
        "has_single_image": False,
        "duration": duration,
        "acodec": stream.get("codec_name", ""),
        "sample_rate": int(stream.get("sample_rate", 48000)),
        "channels": channels,
        "channel_layout": 4 if channels == 1 else 3,       # libopenshot's LAYOUT_MONO, LAYOUT_STEREO
        "audio_stream_index": int(stream["index"]),
        "audio_timebase": {"num": tb_num, "den": tb_den},
        "video_stream_index": -1,
        "fps": {"num": fps_num, "den": fps_den},
        "video_length": sec_to_frames(duration, fps),
    }, duration


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
            path = resource_path(clip["source"], project_dir)
            if track["type"] == "audio":
                reader, duration = _audio_reader(path, clip["source"], fps)
                media_type = "audio"
            else:
                info = analyze(clip["source"])
                reader, duration, media_type = _reader(path, info), info.duration_seconds, "video"
            file_id = f"FFFILE{len(files) + 1:04d}"
            files.append({**reader, "media_type": media_type, "id": file_id})
            # Frames at the project's rate, as the MLT compiler counts them.
            sources[clip["source"]] = (file_id, reader, sec_to_frames(duration, fps))

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
            clip_id = f"FFCLIP{len(clips) + 1:04d}"
            clips.append({
                **json.loads(json.dumps(CLIP_DEFAULTS)),
                "id": clip_id,
                "layer": layer(index, track["id"])["number"],
                "position": start_f / fps,
                "start": in_f / fps,
                "end": (in_f + length_f) / fps,
                "duration": reader["duration"],
                "file_id": file_id,
                "title": Path(clip["source"]).name,
                "reader": reader,
                **_levels(clip, in_f, length_f, fps),
                **_framing(clip, reader, project["width"], project["height"], fps),
                "effects": _effects(clip, clip_id, project_dir),
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
