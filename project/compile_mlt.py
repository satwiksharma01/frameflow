#!/usr/bin/env python3
"""IR -> MLT XML compiler.

Migrated from phase0/ir_to_mlt.py for schema 0.2.0. Differences:
  - Reads source_in/source_out + timeline_start/timeline_duration rather than
    a single in/out pair, so clips can be positioned independently of their
    source media.
  - Emits <blank> entries for gaps between clips on a track.
  - Validates the IR before compiling, and probes the source for its duration
    instead of taking duration/fps as hand-passed CLI arguments.

The Shotcut-specific scaffolding (title marker, main_bin, black background
track, mix/qtblend transitions) is unchanged from Phase 0 and is required -
see the MLT structural requirements in the backend schema notes.

Usage:
    python -m project.compile_mlt <ir_project.json> <output.mlt>
"""
import argparse
import json
import math
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from project.media import analyze
from project.shotcut_template import (
    TRACK_TYPE_PROPERTY,
    add_background,
    add_tractor,
    build_root,
)
from project.sidecar import write_sidecar
from project.validate import validate

COMMON_RATES = {
    24000 / 1001: (24000, 1001),
    24.0: (24, 1),
    25.0: (25, 1),
    30000 / 1001: (30000, 1001),
    30.0: (30, 1),
    50.0: (50, 1),
    60000 / 1001: (60000, 1001),
    60.0: (60, 1),
}


def fps_to_fraction(fps: float) -> tuple[int, int]:
    for rate, frac in COMMON_RATES.items():
        if abs(fps - rate) < 0.01:
            return frac
    f = Fraction(fps).limit_denominator(1_000_000)
    return f.numerator, f.denominator


def sec_to_frames(seconds: float, fps: float) -> int:
    return round(seconds * fps)


def _single_video_track(ir: dict) -> dict:
    tracks = ir["tracks"]
    if len(tracks) != 1 or tracks[0]["type"] != "video":
        raise NotImplementedError(
            "the compiler currently supports exactly one track, of type 'video'. "
            "The schema models broll/graphics/captions/audio tracks, but compiling "
            "them needs multi-track compositing that is not built yet."
        )
    track = tracks[0]
    if not track["clips"]:
        raise ValueError("video track has no clips - nothing to compile")
    return track


def build_mlt(ir: dict) -> ET.Element:
    validate(ir, "ir")

    project = ir["project"]
    fps = project["fps"]
    width, height = project["width"], project["height"]
    num, den = fps_to_fraction(fps)
    g = math.gcd(width, height)
    dar_num, dar_den = width // g, height // g

    track = _single_video_track(ir)
    clips = sorted(track["clips"], key=lambda c: c["timeline_start"])

    sources = {c["source"] for c in clips}
    if len(sources) != 1:
        raise NotImplementedError("the compiler currently supports exactly one source file")
    source_path = Path(sources.pop())
    source_frames = sec_to_frames(analyze(source_path).duration_seconds, fps)

    mlt = build_root(width, height, num, den, dar_num, dar_den)

    producer = ET.SubElement(
        mlt, "producer", {"id": "producer0", "in": "0", "out": str(source_frames - 1)}
    )
    ET.SubElement(producer, "property", {"name": "resource"}).text = source_path.resolve().as_posix()
    ET.SubElement(producer, "property", {"name": "mlt_service"}).text = "avformat"
    ET.SubElement(producer, "property", {"name": "length"}).text = str(source_frames)

    playlist = ET.SubElement(mlt, "playlist", {"id": "playlist0"})
    ET.SubElement(playlist, "property", {"name": "shotcut:video"}).text = "1"
    ET.SubElement(playlist, "property", {"name": "shotcut:name"}).text = track["id"]
    # MLT has no concept of our track semantics (video vs broll vs graphics),
    # so carry it as a custom property rather than losing it on round-trip.
    ET.SubElement(playlist, "property", {"name": TRACK_TYPE_PROPERTY}).text = track["type"]

    cursor = 0
    for clip in clips:
        start_f = sec_to_frames(clip["timeline_start"], fps)
        if start_f > cursor:
            ET.SubElement(playlist, "blank", {"length": str(start_f - cursor)})
            cursor = start_f

        in_f = sec_to_frames(clip["source_in"], fps)
        # Derive the out point from the timeline length rather than rounding
        # source_out independently, so the entry can never be a frame longer
        # or shorter than the slot it occupies.
        length_f = sec_to_frames(clip["timeline_duration"], fps)
        out_f = in_f + length_f - 1
        if length_f <= 0:
            raise ValueError(f"clip {clip['id']!r} rounds to zero frames at {fps} fps")
        if out_f == source_frames:
            # Rounding in and length separately can land one frame past the
            # end for a clip that runs to the end of the source - which most
            # first cuts do. One frame is rounding, not an authoring error.
            out_f -= 1
            length_f -= 1
        if out_f > source_frames - 1:
            raise ValueError(
                f"clip {clip['id']!r} ends at source frame {out_f}, beyond the source's "
                f"{source_frames} frames"
            )
        ET.SubElement(playlist, "entry", {
            "producer": "producer0", "in": str(in_f), "out": str(out_f),
        })
        cursor += length_f

    add_background(mlt, cursor)
    add_tractor(mlt, cursor, ["playlist0"], project["source_frame_rate_mode"])
    return mlt


def compile_file(ir_path: Path | str, output_path: Path | str) -> Path:
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8"))
    tree = ET.ElementTree(build_mlt(ir))
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    # Shotcut strips our custom properties when it rewrites the project, so
    # the metadata MLT cannot hold is written beside the file instead.
    write_sidecar(output_path, ir)
    return Path(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a Frameflow IR into an MLT project.")
    parser.add_argument("ir_project")
    parser.add_argument("output")
    args = parser.parse_args()
    print(f"wrote {compile_file(args.ir_project, args.output)}")


if __name__ == "__main__":
    main()
