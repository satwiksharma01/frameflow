#!/usr/bin/env python3
"""Validation for Frameflow documents (IR, transcript, edit plan).

Two layers:
  1. JSON Schema - shape, types, required fields, enums.
  2. Semantic checks - constraints JSON Schema cannot express, such as
     source_out > source_in and non-overlapping clips within a track.

Usage:
    python -m project.validate <file.json> --kind ir|transcript|edit_plan
"""
import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).parent / "schema"
SCHEMA_FILES = {
    "ir": "ir.schema.json",
    "transcript": "transcript.schema.json",
    "edit_plan": "edit_plan.schema.json",
}

# Far below one frame at any realistic frame rate, so it cannot mask a real
# error, but tolerant of float representation noise.
_EPSILON = 1e-4


class ValidationError(Exception):
    pass


def load_schema(kind: str) -> dict:
    if kind not in SCHEMA_FILES:
        raise ValueError(f"unknown document kind {kind!r}; expected one of {sorted(SCHEMA_FILES)}")
    return json.loads((SCHEMA_DIR / SCHEMA_FILES[kind]).read_text(encoding="utf-8"))


def _check_schema(document: dict, kind: str) -> None:
    validator = Draft202012Validator(load_schema(kind))
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if errors:
        lines = []
        for err in errors:
            location = "/".join(str(p) for p in err.path) or "<root>"
            lines.append(f"  at {location}: {err.message}")
        raise ValidationError(f"{kind} failed schema validation:\n" + "\n".join(lines))


def _check_ir_semantics(ir: dict) -> None:
    problems = []
    for track in ir["tracks"]:
        clips = track["clips"]
        for clip in clips:
            label = f"track {track['id']!r} clip {clip['id']!r}"
            if "source_in" in clip:
                span = clip["source_out"] - clip["source_in"]
                if span <= 0:
                    problems.append(
                        f"{label}: source_out ({clip['source_out']}) must be greater than "
                        f"source_in ({clip['source_in']})"
                    )
                elif abs(span - clip["timeline_duration"]) > _EPSILON:
                    problems.append(
                        f"{label}: timeline_duration ({clip['timeline_duration']}) does not match "
                        f"source span ({span}); speed changes are not supported in schema 0.2.0"
                    )

        ordered = sorted(clips, key=lambda c: c["timeline_start"])
        for earlier, later in zip(ordered, ordered[1:]):
            earlier_end = earlier["timeline_start"] + earlier["timeline_duration"]
            if earlier_end - later["timeline_start"] > _EPSILON:
                problems.append(
                    f"track {track['id']!r}: clip {earlier['id']!r} ends at {earlier_end} but "
                    f"clip {later['id']!r} starts at {later['timeline_start']}; clips on one track "
                    f"may not overlap"
                )

    if problems:
        raise ValidationError("ir failed semantic validation:\n" + "\n".join(f"  {p}" for p in problems))


# Edit plans come from a model reasoning over transcript timestamps, so allow
# small arithmetic slack at boundaries - but not enough to hide a skipped span.
_PLAN_BOUNDARY_TOLERANCE = 0.05


def _check_edit_plan_semantics(plan: dict) -> None:
    """Decisions must cover the whole source, in order, with no gaps or overlaps.

    Requiring full coverage means every second is explicitly kept or removed,
    so nothing can be dropped silently - an omitted span is an error, not an
    implicit cut.
    """
    problems = []
    decisions = plan["decisions"]
    duration = plan["source_duration_seconds"]

    for i, d in enumerate(decisions):
        if d["end"] <= d["start"]:
            problems.append(f"decision {i}: end ({d['end']}) must be greater than start ({d['start']})")

    if decisions[0]["start"] > _PLAN_BOUNDARY_TOLERANCE:
        problems.append(f"decisions start at {decisions[0]['start']}s; the first must start at 0")

    for i, (earlier, later) in enumerate(zip(decisions, decisions[1:]), start=1):
        gap = later["start"] - earlier["end"]
        if gap > _PLAN_BOUNDARY_TOLERANCE:
            problems.append(
                f"decision {i}: gap from {earlier['end']}s to {later['start']}s is not covered; "
                f"every span must be explicitly kept or removed"
            )
        elif gap < -_PLAN_BOUNDARY_TOLERANCE:
            problems.append(
                f"decision {i}: starts at {later['start']}s, overlapping the previous decision "
                f"which ends at {earlier['end']}s; decisions must be in order and not overlap"
            )

    if abs(decisions[-1]["end"] - duration) > _PLAN_BOUNDARY_TOLERANCE:
        problems.append(
            f"decisions end at {decisions[-1]['end']}s but the source is {duration}s long; "
            f"the last decision must end at the source duration"
        )

    if not any(d["action"] == "keep" for d in decisions):
        problems.append("no decision keeps anything; a first cut needs at least one kept span")

    if problems:
        raise ValidationError("edit_plan failed semantic validation:\n" + "\n".join(f"  {p}" for p in problems))


def validate(document: dict, kind: str) -> None:
    """Raise ValidationError if the document is invalid."""
    _check_schema(document, kind)
    if kind == "ir":
        _check_ir_semantics(document)
    elif kind == "edit_plan":
        _check_edit_plan_semantics(document)


def validate_file(path: Path | str, kind: str) -> dict:
    """Load, validate and return the document."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(document, kind)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Frameflow document.")
    parser.add_argument("file")
    parser.add_argument("--kind", required=True, choices=sorted(SCHEMA_FILES))
    args = parser.parse_args()

    try:
        validate_file(args.file, args.kind)
    except ValidationError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
    print(f"[PASS] {args.file} is a valid {args.kind} document")


if __name__ == "__main__":
    main()
