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
import re
from dataclasses import dataclass

# How far from the planned boundary to look for a pause. Wide enough to absorb
# transcript drift, narrow enough that a cut never lands in a different sentence.
SEARCH_WINDOW_SECONDS = 0.6

# Silence left on the speech side of a cut. Flush cuts sound panicked.
PAD_SECONDS = 0.25

# A pause inside a heard scene longer than this is cut down to PAD_SECONDS either side, so a long scene keeps its pace.
LONG_PAUSE_SECONDS = 0.75


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


def tokenize(text: str) -> list[str]:
    """The words of `text` as Frameflow compares them: lower case, punctuation gone."""
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w]


def span_of(words: list[dict], pauses: list[dict], phrase: str, fps: float, near: float | None = None,
            length: float | None = None) -> tuple[float, float] | None:
    """Where `phrase` is said in a recording (`words` and `pauses` are its timing), as a span whose edges sit in
    the pauses around it: breathing in before the first word, and a quarter second after the last. Of several
    places, the one whose first word starts nearest `near`. None when the phrase is not said."""
    want = tokenize(phrase)
    if not want:
        raise ValueError(f"{phrase.strip()!r} has no words Frameflow can search for yet")
    said = [(i, t) for i, w in enumerate(words) for t in tokenize(w["text"])]
    runs = [(said[k][0], said[k + len(want) - 1][0]) for k in range(len(said) - len(want) + 1)
            if [t for _, t in said[k:k + len(want)]] == want]
    if not runs:
        return None
    first, last = min(runs, key=lambda run: abs(words[run[0]]["start"] - near)) if near is not None else runs[0]
    begins, ends = words[first]["start"], words[last]["end"]
    before = words[first - 1]["end"] if first > 0 else 0.0
    after = words[last + 1]["start"] if last + 1 < len(words) else None

    # The pause that ends where the first word begins, and the one that begins where the last word ends.
    opening = [p for p in pauses if before - 1e-6 <= p["end"] <= begins + 1e-6]
    closing = [p for p in pauses if ends - 1e-6 <= p["start"] <= (after if after is not None else float("inf")) + 1e-6]
    if opening:
        start = place_in_pause(max(opening, key=lambda p: p["end"]), "remove", "keep", fps)
    else:
        start = frame_align((before + begins) / 2, fps) if first > 0 else 0.0
    if closing:
        end = place_in_pause(min(closing, key=lambda p: p["start"]), "keep", "remove", fps)
    elif after is not None:
        end = frame_align((ends + after) / 2, fps)
    else:
        end = frame_align(ends + PAD_SECONDS, fps)
    if length is not None:
        end = min(end, length)
    return start, end


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


def place_in_pause(pause: dict, before: str, after: str, fps: float) -> float:
    """The frame-aligned point in `pause` for a cut between `before` and `after`."""
    frame = 1.0 / fps
    target = _target_in_pause(pause, before, after)
    # Stay at least a frame inside the pause: a boundary loses up to a frame
    # of audio, and the frames either side carry the neighbouring words.
    low, high = pause["start"] + frame, pause["end"] - frame
    return frame_align(min(max(target, low), high) if low <= high
                       else (pause["start"] + pause["end"]) / 2, fps)


def kept_pieces(start: float, end: float, pauses: list[dict], fps: float) -> list[tuple[float, float]]:
    """The stretches of [start, end] that play: each long pause wholly inside it is cut down to the breath
    either side, as first-cut leaves one. A pause over an edge is the span's own business."""
    pieces, at = [], start
    for p in pauses:
        if start < p["start"] and p["end"] < end and p["end"] - p["start"] > LONG_PAUSE_SECONDS:
            pieces.append((at, place_in_pause(p, "keep", "remove", fps)))
            at = place_in_pause(p, "remove", "keep", fps)
    return pieces + [(at, end)]


def trim_edges(start: float, end: float, pauses: list[dict], fps: float) -> tuple[float, float]:
    """[start, end] with a long pause at either edge cut where a cut inside the span would resume or stop, a
    breath from the words, whatever plays beside it. A span inside one pause is left whole rather than emptied."""
    def long_at(t: float) -> dict | None:
        return next((p for p in pauses if p["start"] <= t <= p["end"] and p["end"] - p["start"] > LONG_PAUSE_SECONDS),
                    None)
    first, last = long_at(start), long_at(end)
    trimmed = (place_in_pause(first, "remove", "keep", fps) if first else start,
               place_in_pause(last, "keep", "remove", fps) if last else end)
    return trimmed if trimmed[0] < trimmed[1] else (start, end)


def is_tight(pause: dict, fps: float) -> bool:
    """Under three frames: after losing up to a frame at each side, no safe cut point is left."""
    return pause["end"] - pause["start"] < 3 * (1.0 / fps)


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
        final = place_in_pause(pause, decisions[i]["action"], decisions[i + 1]["action"], fps)

        floor = decisions[i]["start"] + frame
        ceiling = decisions[i + 1]["end"] - frame
        if not (floor <= final <= ceiling):
            notes.append(SnapNote(i, planned, planned, "unchanged",
                                  "snapping would leave a neighbouring span with no frames"))
            continue

        decisions[i]["end"] = final
        decisions[i + 1]["start"] = final

        if is_tight(pause, fps):
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
