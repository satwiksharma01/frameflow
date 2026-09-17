"""Edit plan -> IR: the kept spans, laid end to end on one video track.

Deterministic on purpose. The model decides what to keep; turning that into a
timeline involves no judgement, so it happens in code the model never touches.
"""
from pathlib import Path

from project.validate import validate

SCHEMA_VERSION = "0.2.0"
_PRECISION = 6


def edit_plan_to_ir(plan: dict, source: Path | str, width: int, height: int, fps: float,
                    source_frame_rate_mode: str, name: str, source_duration: float) -> dict:
    validate(plan, "edit_plan")
    keeps = sorted((d for d in plan["decisions"] if d["action"] == "keep"), key=lambda d: d["start"])

    clips = []
    cursor = 0.0
    for d in keeps:
        # Plan validation tolerates a little arithmetic slack at the end of the
        # source; that slack must not reach the timeline as frames that don't exist.
        end = min(d["end"], source_duration)
        duration = round(end - d["start"], _PRECISION)
        clips.append({
            "id": f"clip{len(clips) + 1}",
            "source": Path(source).resolve().as_posix(),
            "source_in": round(d["start"], _PRECISION),
            "source_out": round(d["start"] + duration, _PRECISION),
            "timeline_start": round(cursor, _PRECISION),
            "timeline_duration": duration,
        })
        cursor += duration

    ir = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "name": name,
            "width": width,
            "height": height,
            "fps": fps,
            "source_frame_rate_mode": source_frame_rate_mode,
        },
        "tracks": [{"id": "V1", "type": "video", "clips": clips}],
    }
    validate(ir, "ir")
    return ir
