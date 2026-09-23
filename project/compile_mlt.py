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
import os
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


def _compilable_tracks(ir: dict) -> list[dict]:
    """Every track the compiler can emit, in IR order - which is bottom to top.

    Two kinds are refused rather than guessed at. An audio track needs
    Shotcut's shotcut:audio convention and no video blend, and unlike the rest
    of this scaffolding that convention has never been checked against a
    project Shotcut actually wrote. A clip with no source is a caption or a
    generated visual, which needs a producer this compiler cannot build.
    """
    tracks = ir["tracks"]

    audio = [t["id"] for t in tracks if t["type"] == "audio"]
    if audio:
        raise NotImplementedError(
            f"audio tracks are not compiled yet: {', '.join(audio)}. Shotcut marks one "
            "with shotcut:audio and gives it no video transition, but that convention "
            "has not been verified against a project Shotcut wrote, and this module "
            "does not guess at conventions - see shotcut_template's docstring."
        )

    sourceless = [c["id"] for t in tracks for c in t["clips"] if "source" not in c]
    if sourceless:
        raise NotImplementedError(
            f"clips with no source media are not compiled yet: {', '.join(sourceless)}. "
            "Captions and generated graphics need a producer this compiler cannot build."
        )

    if not any(t["clips"] for t in tracks):
        raise ValueError("no track has any clips - nothing to compile")
    return tracks


def resource_path(source: str | Path, project_dir: Path | None) -> str:
    """How the .mlt should refer to a source file.

    MLT resolves a relative resource against the directory holding the .mlt,
    not the working directory - verified against the engine with a broken-path
    control, since melt exits 0 either way. So a relative reference keeps
    working when the whole tree is moved or renamed, which an absolute one
    does not ("projects break when files move" is a real editing pain point).

    Sources on another drive cannot be expressed relatively at all, and those
    stay absolute. Shotcut writes absolute paths in its own saves, so a human
    save may well convert these back; that costs nothing we had before.
    """
    absolute = Path(source).resolve()
    if project_dir is None:
        return absolute.as_posix()
    try:
        relative = os.path.relpath(absolute, Path(project_dir).resolve())
    except ValueError:      # different drive on Windows
        return absolute.as_posix()
    return Path(relative).as_posix()


def _add_producers(mlt: ET.Element, tracks: list[dict], fps: float,
                   project_dir: Path | None) -> tuple[dict[str, str], dict[str, int]]:
    """One producer per distinct source, shared by every track that uses it.

    Sharing matters: B-roll cut from the same file as the main track, or the
    same clip reused twice, must not probe or declare that file twice.
    """
    ordered: list[str] = []
    for track in tracks:
        for clip in track["clips"]:
            if clip["source"] not in ordered:
                ordered.append(clip["source"])

    producer_ids, source_frames = {}, {}
    for index, source in enumerate(ordered):
        path = Path(source)
        frames = sec_to_frames(analyze(path).duration_seconds, fps)
        producer_id = f"producer{index}"
        producer_ids[source], source_frames[source] = producer_id, frames

        producer = ET.SubElement(
            mlt, "producer", {"id": producer_id, "in": "0", "out": str(frames - 1)}
        )
        ET.SubElement(producer, "property", {"name": "resource"}).text = resource_path(
            path, project_dir)
        ET.SubElement(producer, "property", {"name": "mlt_service"}).text = "avformat"
        ET.SubElement(producer, "property", {"name": "length"}).text = str(frames)
    return producer_ids, source_frames


def _fill_playlist(playlist: ET.Element, track: dict, fps: float,
                   producer_ids: dict[str, str], source_frames: dict[str, int]) -> int:
    """Write the track's clips and the gaps between them; return where it ends."""
    cursor = 0
    for clip in sorted(track["clips"], key=lambda c: c["timeline_start"]):
        start_f = sec_to_frames(clip["timeline_start"], fps)
        if start_f > cursor:
            ET.SubElement(playlist, "blank", {"length": str(start_f - cursor)})
            cursor = start_f

        frames = source_frames[clip["source"]]
        in_f = sec_to_frames(clip.get("source_in", 0.0), fps)
        # Derive the out point from the timeline length rather than rounding
        # source_out independently, so the entry can never be a frame longer
        # or shorter than the slot it occupies.
        length_f = sec_to_frames(clip["timeline_duration"], fps)
        out_f = in_f + length_f - 1
        if length_f <= 0:
            raise ValueError(f"clip {clip['id']!r} rounds to zero frames at {fps} fps")
        if out_f == frames:
            # Rounding in and length separately can land one frame past the
            # end for a clip that runs to the end of the source - which most
            # first cuts do. One frame is rounding, not an authoring error.
            out_f -= 1
            length_f -= 1
        if out_f > frames - 1:
            raise ValueError(
                f"clip {clip['id']!r} ends at source frame {out_f}, beyond the "
                f"{frames} frames of {clip['source']}"
            )
        ET.SubElement(playlist, "entry", {
            "producer": producer_ids[clip["source"]], "in": str(in_f), "out": str(out_f),
        })
        cursor += length_f
    return cursor


def build_mlt(ir: dict, project_dir: Path | None = None) -> ET.Element:
    """Compile the IR. With project_dir, sources are referenced relative to it.

    Relative resources are correct for the MLT engine but NOT known to be
    correct for Shotcut, which writes absolute paths and gates path handling on
    shotcut:projectFolder. compile_file therefore leaves this off by default.
    """
    validate(ir, "ir")

    project = ir["project"]
    fps = project["fps"]
    width, height = project["width"], project["height"]
    num, den = fps_to_fraction(fps)
    g = math.gcd(width, height)
    dar_num, dar_den = width // g, height // g

    tracks = _compilable_tracks(ir)
    mlt = build_root(width, height, num, den, dar_num, dar_den)
    producer_ids, source_frames = _add_producers(mlt, tracks, fps, project_dir)

    playlist_ids, total_frames = [], 0
    for index, track in enumerate(tracks):
        playlist_id = f"playlist{index}"
        playlist = ET.SubElement(mlt, "playlist", {"id": playlist_id})
        ET.SubElement(playlist, "property", {"name": "shotcut:video"}).text = "1"
        ET.SubElement(playlist, "property", {"name": "shotcut:name"}).text = track["id"]
        # MLT has no concept of our track semantics (video vs broll vs graphics),
        # so carry it as a custom property rather than losing it on round-trip.
        ET.SubElement(playlist, "property", {"name": TRACK_TYPE_PROPERTY}).text = track["type"]
        total_frames = max(
            total_frames, _fill_playlist(playlist, track, fps, producer_ids, source_frames)
        )
        playlist_ids.append(playlist_id)

    # Span the longest track, not the first: an upper layer that outlasts the
    # one below it would otherwise run past the end of the project.
    add_background(mlt, total_frames)
    add_tractor(mlt, total_frames, playlist_ids, project["source_frame_rate_mode"],
                project_folder=project_dir is not None)
    return mlt


def compile_file(ir_path: Path | str, output_path: Path | str,
                 relative_paths: bool = False) -> Path:
    """Compile an IR file to an .mlt.

    relative_paths makes the project portable - the folder can be moved or
    renamed - but is off by default because Shotcut has not been shown to read
    such a project. The MLT engine does; see the round-trip and move tests.
    """
    ir = json.loads(Path(ir_path).read_text(encoding="utf-8"))
    project_dir = Path(output_path).resolve().parent if relative_paths else None
    tree = ET.ElementTree(build_mlt(ir, project_dir=project_dir))
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
