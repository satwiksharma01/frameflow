#!/usr/bin/env python3
"""Move planned cut points to the safest nearby place in the audio.

The editor decides *what* to cut from a transcript, so its boundaries are
approximate - transcript timings drift, and a model reading them has no way to
know where a word actually ends. This module does the part that needs
measurement rather than judgement: it slides each boundary into the nearest
real pause and lands it on a frame.

Two facts make this necessary rather than cosmetic:
  - A cut that misses the pause clips a word. In testing, a boundary 0.08s
    late kept the "ac" of "actually" and played as "contact".
  - MLT can only cut on frame boundaries, and each boundary loses up to a
    frame of audio at each side, so a pause under about three frames has no
    safe cut point at all. Those are reported rather than silently used: on a
    real recording an 80ms gap (2.4 frames at 30fps) could not be cut cleanly.
"""
from dataclasses import dataclass

# How far from the planned boundary to look for a pause. Wide enough to absorb
# transcript drift, narrow enough that a cut never lands in a different sentence.
SEARCH_WINDOW_SECONDS = 0.6

# Silence left on the speech side of a cut. Flush cuts sound panicked.
PAD_SECONDS = 0.25


@dataclass
class SnapNote:
    index: int
    planned: float
    final: float
    status: str  # snapped | unchanged | no-pause | tight
    detail: str

    @property
    def moved_ms(self) -> int:
        return round((self.final - self.planned) * 1000)


def frame_align(seconds: float, fps: float) -> float:
    return round(seconds * fps) / fps


def find_pause(pauses: list[dict], t: float, window: float = SEARCH_WINDOW_SECONDS) -> dict | None:
    """The pause a cut at `t` most likely belongs in.

    A pause containing `t` always wins; otherwise the nearest one within the
    window, preferring the longer of two equally close candidates.
    """
    containing = [p for p in pauses if p["start"] <= t <= p["end"]]
    if containing:
        return max(containing, key=lambda p: p["end"] - p["start"])

    def distance(p: dict) -> float:
        return p["start"] - t if p["start"] > t else t - p["end"]

    nearby = [p for p in pauses if distance(p) <= window]
    if not nearby:
        return None
    return min(nearby, key=lambda p: (round(distance(p), 3), -(p["end"] - p["start"])))


def _target_in_pause(pause: dict, before: str, after: str) -> float:
    """Where in the pause the cut belongs, given what sits either side."""
    if before == "keep" and after == "remove":
        return pause["start"] + PAD_SECONDS   # let the kept speech breathe out
    if before == "remove" and after == "keep":
        return pause["end"] - PAD_SECONDS     # breathe in before the kept speech
    return (pause["start"] + pause["end"]) / 2


def snap_plan(plan: dict, pauses: list[dict], fps: float,
              window: float = SEARCH_WINDOW_SECONDS) -> tuple[dict, list[SnapNote]]:
    """Return a copy of the plan with every internal boundary snapped, plus notes."""
    decisions = [dict(d) for d in plan["decisions"]]
    frame = 1.0 / fps
    notes: list[SnapNote] = []

    for i in range(len(decisions) - 1):
        planned = decisions[i]["end"]
        pause = find_pause(pauses, planned, window)

        if pause is None:
            notes.append(SnapNote(i, planned, planned, "no-pause",
                                  f"no measured pause within {window:.2f}s - left as planned, "
                                  f"so this cut may land mid-word"))
            continue

        length = pause["end"] - pause["start"]
        target = _target_in_pause(pause, decisions[i]["action"], decisions[i + 1]["action"])
        # Stay at least a frame inside the pause: a boundary loses up to a frame
        # of audio, and the frames either side carry the neighbouring words.
        low, high = pause["start"] + frame, pause["end"] - frame
        final = frame_align(min(max(target, low), high) if low <= high
                            else (pause["start"] + pause["end"]) / 2, fps)

        floor = decisions[i]["start"] + frame
        ceiling = decisions[i + 1]["end"] - frame
        if not (floor <= final <= ceiling):
            notes.append(SnapNote(i, planned, planned, "unchanged",
                                  "snapping would leave a neighbouring span with no frames"))
            continue

        decisions[i]["end"] = final
        decisions[i + 1]["start"] = final

        if length < 3 * frame:
            notes.append(SnapNote(i, planned, final, "tight",
                                  f"pause is only {length * 1000:.0f}ms - under three frames at "
                                  f"{fps:g}fps, so after losing up to a frame at each side there "
                                  f"is no safe cut point here"))
        elif abs(final - planned) > 0.001:
            notes.append(SnapNote(i, planned, final, "snapped",
                                  f"moved into a {length * 1000:.0f}ms pause"))

    snapped = dict(plan)
    snapped["decisions"] = decisions
    return snapped, notes
