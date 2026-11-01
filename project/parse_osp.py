#!/usr/bin/env python3
"""OpenShot .osp -> IR parser (the read direction of the OpenShot bridge).

An .osp is JSON. Each layer is a track - a higher layer draws on top - and each
clip says where it sits on the timeline (`position`) and which span of its
source it plays (`start`/`end`), all in seconds. OpenShot writes media paths
relative to the project file, so they are resolved against its folder here.

Usage:
    python -m project.parse_osp <project.osp> [-o out.ir.json]
"""
import argparse
import json
import math
from pathlib import Path

from project import openshot_build
from project.openshot_template import (CLIP_DEFAULTS, COLOR_MAP, CURVES, SCALE_CROP, SCALE_FIT, keyframe,
                                       location_units)
from project.sidecar import merge_sidecar, read_sidecar
from project.validate import validate

SCHEMA_VERSION = "0.2.0"
_PRECISION = 6


class ParseError(Exception):
    pass


def _source(clip: dict, project_dir: Path) -> str:
    path = (clip.get("reader") or {}).get("path")
    if not path:
        raise ParseError(f"clip {clip.get('id')!r} has no media path")
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (project_dir / candidate).resolve()
    return candidate.as_posix()


# A point as OpenShot's menus write it: Bezier, with automatic handles.
_POINT_STYLE = {k: v for k, v in keyframe(0.0)["Points"][0].items() if k != "co"}


def _curve(curve: dict, fps: float, clip: dict) -> tuple[float, float, float] | None:
    """(level, fade-in seconds, fade-out seconds) of an alpha or volume keyframe.

    Recognises what OpenShot's Fade and Volume menus write: a steady level,
    optionally rising from nothing at the clip's first frame and falling to
    nothing at its last. Keyframes count source frames from 1. None for any
    other curve - a hand-drawn one has no place in the IR yet.
    """
    points = sorted(curve.get("Points") or [], key=lambda p: p["co"]["X"])
    if not points or any({k: v for k, v in p.items() if k != "co"} != _POINT_STYLE for p in points):
        return None
    xy = [(p["co"]["X"], p["co"]["Y"]) for p in points]
    first = round(clip["start"] * fps) + 1
    last = round(clip["end"] * fps) + 1
    fade_in = fade_out = 0.0
    if len(xy) > 1 and xy[0][1] == 0 and abs(xy[0][0] - first) < 0.5:
        fade_in = (xy[1][0] - xy[0][0]) / fps
        xy = xy[1:]
    if len(xy) > 1 and xy[-1][1] == 0 and abs(xy[-1][0] - last) < 0.5:
        fade_out = (xy[-1][0] - xy[-2][0]) / fps
        xy = xy[:-1]
    level = xy[0][1]
    if any(y != level for _, y in xy):
        return None
    return level, fade_in, fade_out


def _levels(clip: dict, fps: float) -> dict | None:
    """The clip's opacity, volume and fades as IR fields, or None if either
    curve is one the IR cannot hold."""
    alpha = _curve(clip.get("alpha", CLIP_DEFAULTS["alpha"]), fps, clip)
    volume = _curve(clip.get("volume", CLIP_DEFAULTS["volume"]), fps, clip)
    # ponytail: a muted clip (volume 0) has no volume_db; add a mute field when one is needed.
    if alpha is None or volume is None or volume[0] <= 0:
        return None
    fields: dict = {}
    if alpha[0] != 1:
        fields["opacity"] = round(alpha[0], _PRECISION)
    if volume[0] != 1:
        fields["volume_db"] = round(20 * math.log10(volume[0]), _PRECISION)
    for key, picture, sound in (("fade_in", alpha[1], volume[1]), ("fade_out", alpha[2], volume[2])):
        fade = {k: round(v, _PRECISION) for k, v in (("picture", picture), ("sound", sound)) if v > 0}
        if fade:
            fields[key] = fade
    return fields


def _offset(curve: dict, unit: float, fps: float) -> float | list[dict] | None:
    """A location curve as an IR offset: a number when it holds still, keyframes
    when it moves, None for a curve whose shape was drawn by hand."""
    names = {code: name for name, code in CURVES.items()}
    keys = []
    for point in sorted(curve.get("Points") or [], key=lambda p: p["co"]["X"]):
        name = names.get(point.get("interpolation", 0))
        if name is None or (name == "smooth" and any(
                point.get(k, v) != v for k, v in _POINT_STYLE.items() if k != "interpolation")):
            return None
        keys.append({"at": round((point["co"]["X"] - 1) / fps, _PRECISION),
                     "value": round(point["co"]["Y"] / unit, _PRECISION),
                     **({"curve": name} if name != "smooth" else {})})
    if not keys:
        return None
    return keys[0]["value"] if len(keys) == 1 else keys


def _framing(clip: dict, width: int, height: int, fps: float) -> dict | None:
    """The clip's fill and position as IR fields: nothing for a clip left as
    OpenShot places it, None for framing the IR cannot hold yet."""
    default = CLIP_DEFAULTS["location_x"]
    location = (clip.get("location_x", default), clip.get("location_y", default))
    scale = clip.get("scale", SCALE_FIT)
    if scale == SCALE_FIT and location == (default, default):
        return {}
    reader = clip.get("reader") or {}
    if (scale != SCALE_CROP or clip.get("location_coordinate_system", "auto") != "auto"
            or not reader.get("width") or not reader.get("height")):
        return None
    position = {}
    for axis, curve, unit in zip("xy", location, location_units(width, height, reader["width"], reader["height"])):
        offset = _offset(curve, unit, fps)
        if offset is None:
            return None
        if offset != 0:
            position[axis] = offset
    return {"transform": {"fill": True, **({"position": position} if position else {})}}


# How OpenShot saves the path of a LUT it ships with.
_OWN_LUTS = "@colors/"


def _lut(effect: dict, project_dir: Path, fps: float, clip: dict) -> dict | None:
    """A Color Map / Lookup effect as an IR LUT, or None for any other effect, or
    for one changed in a way the IR cannot hold: only its LUT file and a steady
    intensity may differ from what OpenShot gives a new one."""
    if (effect.get("type") != "ColorMap" or set(effect) - set(COLOR_MAP) - {"id"}
            or any(effect.get(k) != v for k, v in COLOR_MAP.items() if k not in ("lut_path", "intensity"))):
        return None
    level = _curve(effect.get("intensity", COLOR_MAP["intensity"]), fps, clip)
    path = effect.get("lut_path") or ""
    install = openshot_build.install_dir()
    if level is None or level[1] or level[2] or (path.startswith(_OWN_LUTS) and install is None):
        return None
    if path.startswith(_OWN_LUTS):
        path = (install / "colors" / path[len(_OWN_LUTS):]).as_posix()
    elif path and not Path(path).is_absolute():
        path = (project_dir / path).resolve().as_posix()
    params = {"path": Path(path).as_posix() if path else ""}
    if level[0] != 1:
        params["intensity"] = round(level[0], _PRECISION)
    return {"type": "lut", "params": params}


def _parse_clip(clip: dict, n: int, project_dir: Path, fps: float, width: int, height: int) -> dict:
    start, end = clip["start"], clip["end"]
    if end <= start:
        raise ParseError(f"clip {clip.get('id')!r} has non-positive length")
    effects = [e for e in (_lut(x, project_dir, fps, clip) for x in clip.get("effects") or []) if e]
    # Clip ids are positional, as the MLT parser's are, so the rest of the
    # pipeline sees the same shape whichever editor the project came from.
    return {
        "id": f"clip{n}",
        "source": _source(clip, project_dir),
        "source_in": round(start, _PRECISION),
        "source_out": round(end, _PRECISION),
        "timeline_start": round(clip["position"], _PRECISION),
        "timeline_duration": round(end - start, _PRECISION),
        # Curves and effects the IR cannot hold are reported by unsupported_content, not here.
        **(_levels(clip, fps) or {}),
        **(_framing(clip, width, height, fps) or {}),
        **({"effects": effects} if effects else {}),
    }


def parse_osp(path: Path | str, use_sidecar: bool = True) -> dict:
    """Read an OpenShot project into the Frameflow IR.

    If a sidecar is present it supplies what OpenShot has nowhere to store
    (provenance, track types); the .osp still wins on timeline structure.
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    fps_fraction = data.get("fps") or {}
    if not fps_fraction.get("num") or not fps_fraction.get("den"):
        raise ParseError("project does not declare a usable frame rate")
    fps = fps_fraction["num"] / fps_fraction["den"]

    layers = sorted(data.get("layers") or [], key=lambda l: l["number"])
    if not layers:
        raise ParseError("no layers; this is not a timeline project")

    project_dir = path.resolve().parent
    tracks = []
    for index, layer in enumerate(layers, start=1):
        on_layer = sorted((c for c in data.get("clips", []) if c.get("layer") == layer["number"]),
                          key=lambda c: c["position"])
        tracks.append({
            # What OpenShot shows: the track's label, or "Track N" when it has none.
            "id": layer.get("label") or f"Track {index}",
            "type": "video",
            "clips": [_parse_clip(c, n, project_dir, fps, int(data["width"]), int(data["height"]))
                      for n, c in enumerate(on_layer, start=1)],
        })

    known = {layer["number"] for layer in layers}
    stray = [c.get("id") for c in data.get("clips", []) if c.get("layer") not in known]
    if stray:
        raise ParseError(f"clip(s) on a layer the project does not declare: {', '.join(map(str, stray))}")

    ir = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "name": path.stem,
            "width": int(data["width"]),
            "height": int(data["height"]),
            "fps": fps,
            # OpenShot has nowhere to record provenance; the sidecar restores it.
            "source_frame_rate_mode": "cfr",
        },
        "tracks": tracks,
    }
    if use_sidecar:
        ir = merge_sidecar(ir, read_sidecar(path))
    validate(ir, "ir")
    return ir


# What a clip may differ in from an untouched one: where it sits and what it
# plays. parse_osp reads these and compile_osp writes them back.
_PER_CLIP = {"id", "layer", "position", "start", "end", "file_id", "title", "image",
             "reader", "duration"}


def unsupported_content(path: Path | str) -> list[str]:
    """Everything in the project that parsing and recompiling would lose.

    An allowlist, as for Shotcut: a clip whose settings differ from what
    OpenShot gives an untouched clip - zoomed, rotated, sped up, muted, moved
    while fitting the frame, a hand-drawn opacity, volume or position curve -
    or that carries an effect other than a LUT at a steady intensity would be
    rewritten without it. Each item is a sentence a creator can act on.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    fps = data["fps"]["num"] / data["fps"]["den"]
    layers = sorted(data.get("layers") or [], key=lambda l: l["number"])
    names = {l["number"]: l.get("label") or f"Track {i}" for i, l in enumerate(layers, start=1)}
    clips = data.get("clips") or []
    found: list[str] = []

    for layer in layers:
        if layer.get("lock"):
            found.append(f"track {names[layer['number']]} is locked")

    for number, name in names.items():
        on_layer = sorted((c for c in clips if c.get("layer") == number), key=lambda c: c["position"])
        for n, clip in enumerate(on_layer, start=1):
            where = f"clip {n} on {name}"
            reader_type = (clip.get("reader") or {}).get("type")
            if reader_type != "FFmpegReader":
                found.append(f"a clip of type {reader_type or 'unknown'}, {where}")
            for effect in clip.get("effects") or []:
                if _lut(effect, Path(path).resolve().parent, fps, clip) is None:
                    found.append(f"the {effect.get('class_name') or effect.get('type') or 'unnamed'} "
                                 f"effect on {where}")
            # Fades, steady levels and the framing of a filled clip carry over as IR
            # fields; other curves do not.
            carried = {"effects"} | ({"alpha", "volume"} if _levels(clip, fps) is not None else set())
            if _framing(clip, int(data["width"]), int(data["height"]), fps) is not None:
                carried |= {"scale", "location_x", "location_y"}
            changed = [k for k, v in CLIP_DEFAULTS.items() if k not in carried and clip.get(k) != v]
            changed += [k for k in clip if k not in CLIP_DEFAULTS and k not in _PER_CLIP]
            if changed:
                found.append(f"changed {', '.join(k.replace('_', ' ') for k in changed)} on {where}")

    # OpenShot keeps transitions in the project's own effects list.
    for transition in data.get("effects") or []:
        kind = transition.get("class_name") or transition.get("type") or "unnamed"
        found.append(f"a {kind} transition on {names.get(transition.get('layer'), 'the timeline')}")

    if data.get("markers"):
        found.append(f"{len(data['markers'])} marker(s) on the timeline")
    used = {c.get("file_id") for c in clips}
    unused = [f for f in data.get("files") or [] if f.get("id") not in used]
    if unused:
        found.append(f"{len(unused)} file(s) in Project Files that are not on the timeline")
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse an OpenShot project into Frameflow IR.")
    parser.add_argument("osp")
    parser.add_argument("-o", "--output", help="write IR JSON here instead of stdout")
    args = parser.parse_args()

    ir = parse_osp(args.osp)
    text = json.dumps(ir, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
