#!/usr/bin/env python3
"""IR JSON -> MLT XML compiler (Phase 0 spike).

Scope is deliberately narrow: one source file, one video track, cuts only
(no B-roll, captions, transitions or effects). This is the riskiest
mechanism in the whitepaper's architecture - prove it in isolation before
adding anything else.

Usage:
    python ir_to_mlt.py <ir_project.json> <source_duration_seconds> <fps> <output.mlt>
"""
import json
import math
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

# Shotcut's project loader only opens a file as an editable timeline project
# if it recognizes this exact title marker; otherwise it treats the file as
# a plain media resource and loads it into the Source player instead of the
# Timeline. Confirmed empirically by diffing against a project Shotcut saved
# itself (phase0/shotcut_reference.mlt) - see also the `shotcut` tractor
# property and the main_bin/background scaffolding below, which Shotcut's
# own writer always includes.
SHOTCUT_TITLE = "Shotcut version 26.8.1"

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
    # Not a standard broadcast rate - likely a measured average from a
    # variable-frame-rate source (e.g. screen capture). Reconstruct with a
    # much larger denominator bound so we don't silently round a VFR average
    # onto an unrelated clean fraction.
    f = Fraction(fps).limit_denominator(1_000_000)
    return f.numerator, f.denominator


def sec_to_frames(seconds: float, fps: float) -> int:
    return round(seconds * fps)


def build_mlt(ir: dict, fps: float, source_duration_s: float) -> ET.Element:
    project = ir["project"]
    width, height = project["width"], project["height"]
    num, den = fps_to_fraction(fps)
    g = math.gcd(width, height)
    dar_num, dar_den = width // g, height // g

    mlt = ET.Element(
        "mlt",
        {
            "LC_NUMERIC": "C",
            "version": "7.9.0",
            "title": SHOTCUT_TITLE,
            "producer": "main_bin",
        },
    )
    ET.SubElement(
        mlt,
        "profile",
        {
            "description": "frameflow-phase0-auto",
            "width": str(width),
            "height": str(height),
            "progressive": "1",
            "sample_aspect_num": "1",
            "sample_aspect_den": "1",
            "display_aspect_num": str(dar_num),
            "display_aspect_den": str(dar_den),
            "frame_rate_num": str(num),
            "frame_rate_den": str(den),
            "colorspace": "709",
        },
    )

    main_bin = ET.SubElement(mlt, "playlist", {"id": "main_bin"})
    ET.SubElement(main_bin, "property", {"name": "xml_retain"}).text = "1"

    video_track = next(t for t in ir["tracks"] if t["type"] == "video")
    clips = video_track["clips"]
    if not clips:
        raise ValueError("no clips in video track - nothing to compile")

    source_paths = {c["source"] for c in clips}
    if len(source_paths) != 1:
        raise NotImplementedError("phase0 spike supports exactly one source file")
    source_path = Path(source_paths.pop()).resolve().as_posix()
    source_frames = sec_to_frames(source_duration_s, fps)

    producer = ET.SubElement(
        mlt, "producer", {"id": "producer0", "in": "0", "out": str(source_frames - 1)}
    )
    ET.SubElement(producer, "property", {"name": "resource"}).text = source_path
    ET.SubElement(producer, "property", {"name": "mlt_service"}).text = "avformat"
    ET.SubElement(producer, "property", {"name": "length"}).text = str(source_frames)

    playlist = ET.SubElement(mlt, "playlist", {"id": "playlist0"})
    ET.SubElement(playlist, "property", {"name": "shotcut:video"}).text = "1"
    ET.SubElement(playlist, "property", {"name": "shotcut:name"}).text = "V1"
    total_frames = 0
    for clip in clips:
        in_f = sec_to_frames(clip["in"], fps)
        out_f = sec_to_frames(clip["out"], fps) - 1
        if out_f <= in_f:
            raise ValueError(
                f"clip {clip.get('id')} has non-positive duration after frame rounding"
            )
        if out_f > source_frames - 1:
            raise ValueError(
                f"clip {clip.get('id')} out-point ({out_f}) exceeds source length ({source_frames} frames)"
            )
        ET.SubElement(
            playlist, "entry", {"producer": "producer0", "in": str(in_f), "out": str(out_f)}
        )
        total_frames += out_f - in_f + 1
    total_out = total_frames - 1

    # Shotcut always renders track 0 over a full-length black background and
    # composites the real content on track 1+, even for a single-track
    # project - the reference file confirms this is boilerplate, not
    # optional.
    black = ET.SubElement(mlt, "producer", {"id": "black", "in": "0", "out": str(total_out)})
    ET.SubElement(black, "property", {"name": "length"}).text = str(total_frames)
    ET.SubElement(black, "property", {"name": "eof"}).text = "pause"
    ET.SubElement(black, "property", {"name": "resource"}).text = "0"
    ET.SubElement(black, "property", {"name": "mlt_service"}).text = "color"
    ET.SubElement(black, "property", {"name": "mlt_image_format"}).text = "rgba"

    background = ET.SubElement(mlt, "playlist", {"id": "background"})
    ET.SubElement(background, "entry", {"producer": "black", "in": "0", "out": str(total_out)})

    tractor = ET.SubElement(
        mlt,
        "tractor",
        {
            "id": "tractor0",
            "title": SHOTCUT_TITLE,
            "in": "0",
            "out": str(total_out),
        },
    )
    ET.SubElement(tractor, "property", {"name": "shotcut"}).text = "1"
    ET.SubElement(tractor, "property", {"name": "shotcut:projectAudioChannels"}).text = "2"
    ET.SubElement(tractor, "track", {"producer": "background"})
    ET.SubElement(tractor, "track", {"producer": "playlist0"})
    mix = ET.SubElement(tractor, "transition", {"id": "transition0"})
    ET.SubElement(mix, "property", {"name": "a_track"}).text = "0"
    ET.SubElement(mix, "property", {"name": "b_track"}).text = "1"
    ET.SubElement(mix, "property", {"name": "mlt_service"}).text = "mix"
    ET.SubElement(mix, "property", {"name": "always_active"}).text = "1"
    ET.SubElement(mix, "property", {"name": "sum"}).text = "1"
    blend = ET.SubElement(tractor, "transition", {"id": "transition1"})
    ET.SubElement(blend, "property", {"name": "a_track"}).text = "0"
    ET.SubElement(blend, "property", {"name": "b_track"}).text = "1"
    ET.SubElement(blend, "property", {"name": "mlt_service"}).text = "qtblend"
    ET.SubElement(blend, "property", {"name": "always_active"}).text = "1"

    return mlt


def main() -> None:
    if len(sys.argv) != 5:
        print(
            "usage: ir_to_mlt.py <ir_project.json> <source_duration_seconds> <fps> <output.mlt>"
        )
        sys.exit(1)
    ir_path, duration_s, fps, out_path = sys.argv[1:5]
    ir = json.loads(Path(ir_path).read_text())
    mlt = build_mlt(ir, float(fps), float(duration_s))
    tree = ET.ElementTree(mlt)
    ET.indent(tree, space="  ")
    tree.write(out_path, encoding="utf-8", xml_declaration=True)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
