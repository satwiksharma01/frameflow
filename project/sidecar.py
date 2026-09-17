#!/usr/bin/env python3
"""Frameflow metadata that cannot live inside the .mlt file.

Milestone 2 established empirically that Shotcut rewrites a project on save
and drops properties it does not recognise: custom `frameflow:*` properties
written by our compiler came back stripped (2 present before the save, 0
after). So anything MLT has no native concept of has to live beside the
project rather than inside it.

What MLT cannot represent, and therefore lives here:
  - source_frame_rate_mode: whether sources are natively CFR or were
    normalized from VFR. Losing this silently downgrades a normalized project
    to "cfr" and throws away the provenance the VFR work exists to track.
  - track semantics: MLT knows video and audio. It has no notion of a broll,
    graphics or captions track.
  - the last-known IR, so the next edit can be diffed against what Claude last
    wrote rather than guessing what the human changed.

The .mlt remains the source of truth for timeline structure - the human edits
it directly, so it must win on clips and timing.
"""
import json
from pathlib import Path

SIDECAR_SUFFIX = ".frameflow.json"


def sidecar_path(mlt_path: Path | str) -> Path:
    """foo.mlt -> foo.frameflow.json"""
    return Path(mlt_path).with_suffix(SIDECAR_SUFFIX)


def write_sidecar(mlt_path: Path | str, ir: dict) -> Path:
    path = sidecar_path(mlt_path)
    path.write_text(json.dumps(ir, indent=2) + "\n", encoding="utf-8")
    return path


def read_sidecar(mlt_path: Path | str) -> dict | None:
    path = sidecar_path(mlt_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def merge_sidecar(parsed_ir: dict, sidecar_ir: dict | None) -> dict:
    """Restore the semantics MLT could not carry.

    Timeline structure from `parsed_ir` always wins: the human edited the .mlt,
    so it is authoritative about what clips exist and where. Only fields MLT
    has nowhere to store are taken from the sidecar.
    """
    if not sidecar_ir:
        return parsed_ir

    merged = json.loads(json.dumps(parsed_ir))
    sidecar_project = sidecar_ir.get("project", {})
    if "source_frame_rate_mode" in sidecar_project:
        merged["project"]["source_frame_rate_mode"] = sidecar_project["source_frame_rate_mode"]
    if "name" in sidecar_project:
        merged["project"]["name"] = sidecar_project["name"]

    types_by_track_id = {
        track["id"]: track["type"] for track in sidecar_ir.get("tracks", [])
    }
    for track in merged["tracks"]:
        if track["id"] in types_by_track_id:
            track["type"] = types_by_track_id[track["id"]]

    return merged
