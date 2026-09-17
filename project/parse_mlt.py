#!/usr/bin/env python3
"""MLT -> IR parser (the read direction of the project bridge).

Must cope with two dialects of the same format:
  - What our compiler writes: <producer> elements, integer frame in/out.
  - What Shotcut writes when a human saves: <chain> elements, timecode in/out
    ("00:00:25.692"), plus its own metadata properties.

Both appear in practice - the second one every time a creator touches the
project - so neither is a special case.

Usage:
    python -m project.parse_mlt <project.mlt> [-o out.ir.json]
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from project.shotcut_template import (
    BACKGROUND_PLAYLIST_ID,
    PROVENANCE_PROPERTY,
    TRACK_TYPE_PROPERTY,
)
from project.sidecar import merge_sidecar, read_sidecar
from project.validate import validate

SCHEMA_VERSION = "0.2.0"
_PRECISION = 6


class ParseError(Exception):
    pass


def _properties(element: ET.Element) -> dict[str, str]:
    return {
        p.get("name"): (p.text or "")
        for p in element.findall("property")
        if p.get("name")
    }


def parse_time(value: str | None, fps: float) -> int:
    """MLT time value -> frame count. Accepts frames or timecode."""
    if value is None or not value.strip():
        return 0
    text = value.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 4:  # HH:MM:SS:FF
            hours, minutes, seconds, frames = parts
            whole = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * fps
            return int(round(whole)) + int(frames)
        if len(parts) == 3:  # HH:MM:SS.mmm
            hours, minutes, seconds = parts
            total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            return int(round(total * fps))
        raise ParseError(f"unrecognised MLT time value {value!r}")
    return int(round(float(text)))


def _seconds(frames: int, fps: float) -> float:
    return round(frames / fps, _PRECISION)


def _media_elements(mlt: ET.Element) -> dict[str, dict]:
    """Every <producer>/<chain> that refers to real media, keyed by id."""
    media = {}
    for tag in ("producer", "chain"):
        for element in mlt.findall(tag):
            element_id = element.get("id")
            if not element_id:
                continue
            props = _properties(element)
            media[element_id] = {
                "resource": props.get("resource", ""),
                "service": props.get("mlt_service", ""),
            }
    return media


def _is_background(playlist: ET.Element, playlist_id: str, media: dict[str, dict]) -> bool:
    if playlist_id == BACKGROUND_PLAYLIST_ID:
        return True
    entries = playlist.findall("entry")
    return bool(entries) and all(
        media.get(e.get("producer", ""), {}).get("service") == "color" for e in entries
    )


def _parse_track(playlist: ET.Element, playlist_id: str, media: dict[str, dict],
                 fps: float) -> dict:
    props = _properties(playlist)
    track_type = props.get(TRACK_TYPE_PROPERTY)
    if not track_type:
        track_type = "audio" if props.get("shotcut:audio") == "1" else "video"

    clips = []
    cursor = 0
    for child in playlist:
        if child.tag == "blank":
            cursor += parse_time(child.get("length"), fps)
            continue
        if child.tag != "entry":
            continue

        producer_id = child.get("producer", "")
        source = media.get(producer_id, {}).get("resource", "")
        if not source:
            raise ParseError(f"entry references unknown producer {producer_id!r}")

        in_frames = parse_time(child.get("in"), fps)
        out_frames = parse_time(child.get("out"), fps)
        length = out_frames - in_frames + 1
        if length <= 0:
            raise ParseError(f"entry for producer {producer_id!r} has non-positive length")

        # Clip ids are positional: MLT has nowhere to record ours, so identity
        # across a round trip is inferred from order, not preserved.
        clips.append({
            "id": f"clip{len(clips) + 1}",
            "source": source,
            "source_in": _seconds(in_frames, fps),
            "source_out": _seconds(out_frames + 1, fps),
            "timeline_start": _seconds(cursor, fps),
            "timeline_duration": _seconds(length, fps),
        })
        cursor += length

    return {
        "id": props.get("shotcut:name") or playlist_id,
        "type": track_type,
        "clips": clips,
    }


def parse_mlt(path: Path | str, use_sidecar: bool = True) -> dict:
    """Read an MLT project into the Frameflow IR.

    If a sidecar is present it supplies the semantics MLT cannot store
    (provenance, track types); the .mlt still wins on timeline structure.
    """
    root = ET.parse(path).getroot()

    profile = root.find("profile")
    if profile is None:
        raise ParseError("no <profile> element; cannot determine resolution or frame rate")
    fps = int(profile.get("frame_rate_num", 0)) / int(profile.get("frame_rate_den", 1))
    if fps <= 0:
        raise ParseError("profile does not declare a usable frame rate")

    tractors = root.findall("tractor")
    if not tractors:
        raise ParseError("no <tractor> element; this is not a timeline project")
    tractor = tractors[-1]

    media = _media_elements(root)
    playlists = {p.get("id"): p for p in root.findall("playlist") if p.get("id")}

    tracks = []
    for track_element in tractor.findall("track"):
        playlist_id = track_element.get("producer", "")
        playlist = playlists.get(playlist_id)
        if playlist is None or _is_background(playlist, playlist_id, media):
            continue
        tracks.append(_parse_track(playlist, playlist_id, media, fps))

    if not tracks:
        raise ParseError("no content tracks found (only a background track?)")

    ir = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "name": Path(path).stem,
            "width": int(profile.get("width")),
            "height": int(profile.get("height")),
            "fps": fps,
            # Absent when Shotcut has rewritten the file and dropped our custom
            # property; "cfr" is the safe assumption because a project that
            # reached Shotcut was already normalized upstream.
            "source_frame_rate_mode": _properties(tractor).get(PROVENANCE_PROPERTY) or "cfr",
        },
        "tracks": tracks,
    }
    if use_sidecar:
        ir = merge_sidecar(ir, read_sidecar(path))
    validate(ir, "ir")
    return ir


def quantize_ir(ir: dict) -> dict:
    """Express every time in whole frames, for round-trip comparison.

    A timeline is discrete, so seconds -> frames -> seconds is only lossless at
    frame granularity. Comparing quantized forms states that honestly instead
    of demanding float equality the format cannot provide.
    """
    fps = ir["project"]["fps"]
    return {
        "project": {
            "width": ir["project"]["width"],
            "height": ir["project"]["height"],
            "fps": round(fps, _PRECISION),
        },
        "tracks": [
            {
                "type": track["type"],
                "clips": [
                    {
                        "source": Path(clip["source"]).name,
                        "source_in": round(clip["source_in"] * fps),
                        "timeline_start": round(clip["timeline_start"] * fps),
                        "timeline_duration": round(clip["timeline_duration"] * fps),
                    }
                    for clip in track["clips"]
                ],
            }
            for track in ir["tracks"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse an MLT project into Frameflow IR.")
    parser.add_argument("mlt")
    parser.add_argument("-o", "--output", help="write IR JSON here instead of stdout")
    args = parser.parse_args()

    ir = parse_mlt(args.mlt)
    text = json.dumps(ir, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
