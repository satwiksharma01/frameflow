#!/usr/bin/env python3
"""Score an edit plan against a hand-written reference plan.

Every other test in this repo checks plumbing: that a document validates, that
a project round-trips, that a provider loop retries. None of them can tell you
whether the *edit* got worse. Cut-point snapping, the editor's guidance, the
silence thresholds and the model itself all move edit quality without moving a
single existing test, so changing any of them is currently a guess.

This is the missing measurement. A reference plan is one a human wrote for a
recording whose flaws are known; scoring a generated plan against it gives
three numbers that mean something:

  - Agreement - of the time the reference keeps, how much did we keep, and of
    the time we kept, how much should have been kept? Recall below 1 means we
    cut something the human wanted; precision below 1 means we left something
    in. Both matter, and they fail in opposite directions, so F1 alone is not
    enough to read.

  - Boundary accuracy - how far each reference cut point is from the nearest
    generated one. Two plans can agree on every editorial call and still differ
    by a quarter second at every join, which is the difference between a clean
    cut and a clipped word.

  - Placement - how many generated cut points sit outside any measured pause.
    After snapping (`project/cutpoints.py`) this should be zero; if it is not,
    snapping did not run or could not find a pause.

Deliberately plan-level. Whether a cut clips a word in the *render* is a
different question, answered by `project/verify_cuts.py` against real audio.

Usage:
    python -m project.score_plan <generated.json> <reference.json> [--pauses timing.json]
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

# Two cut points this close describe the same cut. Wider than a frame at 60fps
# (17ms), narrower than the 0.25s of breathing room a snap adds, so it cannot
# call a padded boundary and an unpadded one the same.
BOUNDARY_TOLERANCE_SECONDS = 0.1

# A boundary at 0 or at the source duration is not a cut, it is the edge of the
# recording. Only interior boundaries are placed by an editor.
_EDGE_EPSILON = 1e-6


def _kept_spans(plan: dict) -> list[tuple[float, float]]:
    return [(d["start"], d["end"]) for d in plan["decisions"] if d["action"] == "keep"]


def _overlap_seconds(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """Total time covered by both. Plans are validated gapless and non-overlapping,
    so a pairwise sweep is exact; the lists are tens of entries, not thousands."""
    total = 0.0
    for start_a, end_a in a:
        for start_b, end_b in b:
            lo, hi = max(start_a, start_b), min(end_a, end_b)
            if hi > lo:
                total += hi - lo
    return total


def interior_boundaries(plan: dict) -> list[float]:
    """The cut points an editor actually chose, excluding the two recording edges."""
    duration = plan["source_duration_seconds"]
    points = set()
    for d in plan["decisions"]:
        points.add(d["start"])
        points.add(d["end"])
    return sorted(p for p in points if _EDGE_EPSILON < p < duration - _EDGE_EPSILON)


def load_pauses(path: Path | str) -> list[dict]:
    """Pauses from either a timing map (`pauses`) or a transcript (`silences`).

    Snapping works against the fine micro-pauses in timing.json; a transcript
    only carries pauses of half a second or more. Accepting both means a plan
    from before the timing map existed can still be scored, just against a
    coarser signal.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pauses = data.get("pauses") or data.get("silences")
    if pauses is None:
        raise ValueError(f"{path} has neither 'pauses' nor 'silences'")
    return pauses


def _in_any_pause(t: float, pauses: list[dict]) -> bool:
    return any(p["start"] <= t <= p["end"] for p in pauses)


def score(generated: dict, reference: dict, pauses: list[dict] | None = None,
          tolerance: float = BOUNDARY_TOLERANCE_SECONDS) -> dict:
    """Compare a generated plan against a reference. Higher is better throughout."""
    gen_kept, ref_kept = _kept_spans(generated), _kept_spans(reference)
    gen_seconds = sum(e - s for s, e in gen_kept)
    ref_seconds = sum(e - s for s, e in ref_kept)
    shared = _overlap_seconds(gen_kept, ref_kept)

    precision = shared / gen_seconds if gen_seconds else 0.0
    recall = shared / ref_seconds if ref_seconds else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    gen_points, ref_points = interior_boundaries(generated), interior_boundaries(reference)
    distances = [min((abs(r - g) for g in gen_points), default=float("inf")) for r in ref_points]
    matched = sum(1 for d in distances if d <= tolerance)
    finite = [d for d in distances if d != float("inf")]

    result = {
        "kept_seconds": {"generated": round(gen_seconds, 3), "reference": round(ref_seconds, 3),
                         "shared": round(shared, 3)},
        "agreement": {"precision": round(precision, 4), "recall": round(recall, 4),
                      "f1": round(f1, 4)},
        "boundaries": {
            "generated": len(gen_points),
            "reference": len(ref_points),
            "matched_within_tolerance": matched,
            "tolerance_seconds": tolerance,
            "median_distance_seconds": round(statistics.median(finite), 4) if finite else None,
            "max_distance_seconds": round(max(finite), 4) if finite else None,
        },
    }

    if pauses is not None:
        outside = [round(p, 3) for p in gen_points if not _in_any_pause(p, pauses)]
        result["placement"] = {"cut_points_outside_a_pause": len(outside), "where": outside}
    return result


def format_report(result: dict) -> str:
    kept, agree, bounds = result["kept_seconds"], result["agreement"], result["boundaries"]
    lines = [
        f"kept        {kept['generated']:.2f}s vs reference {kept['reference']:.2f}s "
        f"({kept['shared']:.2f}s shared)",
        f"agreement   precision {agree['precision']:.3f}  recall {agree['recall']:.3f}  "
        f"F1 {agree['f1']:.3f}",
        f"boundaries  {bounds['matched_within_tolerance']}/{bounds['reference']} matched "
        f"within {bounds['tolerance_seconds']}s ({bounds['generated']} generated)",
    ]
    if bounds["median_distance_seconds"] is not None:
        lines.append(f"            median off by {bounds['median_distance_seconds'] * 1000:.0f}ms, "
                     f"worst {bounds['max_distance_seconds'] * 1000:.0f}ms")
    if "placement" in result:
        placement = result["placement"]
        if not bounds["generated"]:
            lines.append("placement   no cut points to place")
        elif placement["cut_points_outside_a_pause"]:
            lines.append(f"placement   {placement['cut_points_outside_a_pause']} cut point(s) "
                         f"outside any measured pause: {placement['where']}")
        else:
            lines.append("placement   every cut point sits inside a measured pause")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score an edit plan against a reference plan.")
    parser.add_argument("generated")
    parser.add_argument("reference")
    parser.add_argument("--pauses", help="timing.json or transcript.json, to check cut placement")
    parser.add_argument("--json", action="store_true", help="print the raw scores")
    parser.add_argument("--min-f1", type=float,
                        help="exit non-zero if agreement F1 falls below this")
    args = parser.parse_args()

    generated = json.loads(Path(args.generated).read_text(encoding="utf-8"))
    reference = json.loads(Path(args.reference).read_text(encoding="utf-8"))
    pauses = load_pauses(args.pauses) if args.pauses else None

    result = score(generated, reference, pauses)
    print(json.dumps(result, indent=2) if args.json else format_report(result))

    if args.min_f1 is not None and result["agreement"]["f1"] < args.min_f1:
        sys.exit(f"\nF1 {result['agreement']['f1']:.3f} is below the required {args.min_f1}")


if __name__ == "__main__":
    main()
