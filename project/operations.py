#!/usr/bin/env python3
"""Operations: changes to a project the creator already has.

Phase 7a.2. A first cut submits a whole plan; everything after that is an
operation against the timeline the creator currently has. Regenerating the
project for every change would throw away what the human did in Shotcut, and
each later feature (B-roll, captions) would have to be rebuilt as operations
the day incremental editing arrived - door 4 in the roadmap's register.

The editor addresses the recording, not the timeline: remove or restore a
span of source time, read from the transcript. Code works out which clips
that trims, splits, deletes or extends. It is the principle that made the
first cut work - the model decides what, code decides how - and it spares the
model clip-id bookkeeping it is unreliable at. No operation names a clip, so
the timeline can be renumbered freely afterwards.

Rules the code enforces rather than trusting the editor to follow:

  - Boundaries go through the same pause placement as a first cut, because a
    span read off a transcript is only approximately where the words are.
  - A boundary in a pause under three frames is rejected. The first cut can
    only warn about one; here the editor is in a loop and can pick a better
    boundary, which is the refusal finding 5 asked for.
  - An operation that would undo the creator's own edit - restoring what they
    removed in Shotcut, or removing what they put back - is rejected unless it
    carries override_human_edit. Human edits win by default. The check runs on
    the span the editor asked for, not the placed one: placement nudges
    boundaries through silence, and nudging through silence is not an undo.
  - No operation may leave a fragment shorter than a first cut's shortest
    kept span. A flash frame is never what anyone asked for.

Operations touch the main track only. Clips on other tracks keep their
timeline positions; the caller reports that rather than hiding it.
"""
import copy
from dataclasses import dataclass, field
from pathlib import Path

from project.cutpoints import find_pause, frame_align, is_tight, place_in_pause
from project.editor_agent import MIN_KEEP_SECONDS
from project.reconcile import HumanChanges, merge_spans, source_key, subtract_spans
from project.validate import ValidationError, validate

_CLIP_KEYS = ("id", "source", "source_in", "source_out", "timeline_start", "timeline_duration")


@dataclass
class Operation:
    """One operation, resolved against the timeline and placed in the audio."""
    index: int
    action: str
    source: str                          # the path exactly as the timeline has it
    requested: tuple[float, float]
    start: float
    end: float
    reason: str
    confidence: str = "high"
    override: str | None = None
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        verb = "removed" if self.action == "remove" else "restored"
        text = f"{verb} {self.start:.2f}-{self.end:.2f}s of {Path(self.source).name}"
        if (round(self.start, 2), round(self.end, 2)) != tuple(round(t, 2) for t in self.requested):
            text += f" (asked for {self.requested[0]:.2f}-{self.requested[1]:.2f}s, placed in the pauses)"
        text += f": {self.reason}"
        if self.override:
            text += f" [overrides your own edit: {self.override}]"
        if self.confidence == "low":
            text += " [unsure]"
        return text


def main_index(ir: dict) -> int | None:
    return next((i for i, t in enumerate(ir["tracks"]) if t["type"] == "video"), None)


def _place(t: float, pauses: list[dict] | None, fps: float,
           before: str, after: str) -> tuple[float, str | None, str | None]:
    """(where the boundary lands, a note, a problem)."""
    if pauses is None:
        return frame_align(t, fps), None, None
    pause = find_pause(pauses, t)
    if pause is None:
        return frame_align(t, fps), f"no measured pause near {t:.2f}s, so it may land mid-word", None
    if is_tight(pause, fps):
        ms = round((pause["end"] - pause["start"]) * 1000)
        return t, None, (f"the pause near {t:.2f}s is only {ms}ms - under three frames at {fps:g}fps "
                         f"no frame-aligned cut there keeps the neighbouring words whole. Move this "
                         f"boundary to a longer pause")
    return place_in_pause(pause, before, after, fps), None, None


def resolve(doc: dict, ir: dict, changes: HumanChanges,
            pauses: dict[str, list[dict]] | None = None,
            durations: dict[str, float] | None = None) -> tuple[list[Operation], list[str]]:
    """Check operations against the timeline and place their boundaries.

    `pauses` and `durations` are keyed by reconcile.source_key. A source with
    no pauses gets frame-aligned boundaries only; one with no duration leaves
    the upper bound to the compiler.
    """
    try:
        validate(doc, "operations")
    except ValidationError as e:
        return [], [str(e)]

    fps = ir["project"]["fps"]
    pauses, durations = pauses or {}, durations or {}
    main = main_index(ir)
    if main is None:
        return [], ["the project has no video track to edit"]

    recordings: dict[str, dict[str, str]] = {}          # file name -> {key: path}
    for clip in ir["tracks"][main]["clips"]:
        recordings.setdefault(Path(clip["source"]).name, {})[source_key(clip["source"])] = clip["source"]

    operations, problems = [], []
    for n, raw in enumerate(doc["operations"], start=1):
        label = f"operation {n} ({raw['action']} {raw['start']}-{raw['end']}s)"
        if raw["end"] <= raw["start"]:
            problems.append(f"{label}: end must be after start")
            continue

        if "source" in raw:
            matches = recordings.get(Path(raw["source"]).name, {})
        elif len(recordings) == 1:
            matches = next(iter(recordings.values()))
        else:
            problems.append(f"{label}: the main track uses {len(recordings)} recordings "
                            f"({', '.join(sorted(recordings))}); name one in \"source\"")
            continue
        if len(matches) != 1:
            problems.append(f"{label}: " + (
                f"{raw['source']!r} is not a recording on the main track; use one of "
                f"{', '.join(sorted(recordings))}" if not matches else
                f"more than one recording is called {raw['source']!r}"))
            continue
        key, source = next(iter(matches.items()))

        start_req, end_req = raw["start"], raw["end"]
        duration = durations.get(key)
        if duration is not None:
            if start_req >= duration:
                problems.append(f"{label}: the recording is only {duration:.2f}s long")
                continue
            end_req = min(end_req, duration)

        # Remove: kept material before the span, removed inside it. Restore: the reverse.
        outside, inside = ("keep", "remove") if raw["action"] == "remove" else ("remove", "keep")
        start, start_note, start_problem = _place(start_req, pauses.get(key), fps, outside, inside)
        end, end_note, end_problem = _place(end_req, pauses.get(key), fps, inside, outside)
        placement = [p for p in (start_problem, end_problem) if p]
        if placement:
            problems.extend(f"{label}: {p}" for p in placement)
            continue
        if end - start < 1 / fps:
            problems.append(f"{label}: placed in the nearest pauses, nothing is left between the "
                            f"two boundaries; widen the span")
            continue

        undoes = "removed" if raw["action"] == "restore" else "restored"
        undone = changes.overlapping(undoes, source, start_req, end_req, at_least=1 / fps)
        if undone and "override_human_edit" not in raw:
            spans = ", ".join(f"{s:.2f}-{e:.2f}s" for s, e in undone)
            did = "took out" if undoes == "removed" else "put back"
            problems.append(
                f"{label}: the creator {did} {spans} themselves in the editor since Frameflow "
                f"last wrote this project, and their edits win. Only do this if the instruction "
                f"explicitly asks to undo it - then set override_human_edit to say which part of "
                f"the instruction asks")
            continue

        operations.append(Operation(
            n, raw["action"], source, (raw["start"], raw["end"]), start, end, raw["reason"],
            raw.get("confidence", "high"), raw.get("override_human_edit"),
            [note for note in (start_note, end_note) if note]))
    return operations, problems


def _pieces(track: dict, fps: float) -> list[dict]:
    """Main-track clips as editable pieces, each remembering the gap before it."""
    pieces, previous_end = [], 0.0
    for clip in sorted(track["clips"], key=lambda c: c["timeline_start"]):
        gap = clip["timeline_start"] - previous_end
        pieces.append({
            "source": clip["source"], "in": clip["source_in"], "out": clip["source_out"],
            "gap": gap if gap > 0.5 / fps else 0.0, "by": None,
            "extra": {k: v for k, v in clip.items() if k not in _CLIP_KEYS},
        })
        previous_end = clip["timeline_start"] + clip["timeline_duration"]
    return pieces


def _store(track: dict, pieces: list[dict]) -> None:
    clips, cursor = [], 0.0
    for n, piece in enumerate(pieces, start=1):
        cursor += piece["gap"]
        duration = round(piece["out"] - piece["in"], 6)
        clips.append({
            "id": f"clip{n}", "source": piece["source"], **piece["extra"],
            "source_in": round(piece["in"], 6), "source_out": round(piece["in"] + duration, 6),
            "timeline_start": round(cursor, 6), "timeline_duration": duration,
        })
        cursor += duration
    track["clips"] = clips


def _remove(pieces: list[dict], op: Operation) -> tuple[list[dict], bool]:
    key, result, carry, touched = source_key(op.source), [], 0.0, False
    for piece in pieces:
        if source_key(piece["source"]) != key or piece["out"] <= op.start or piece["in"] >= op.end:
            result.append(dict(piece, gap=piece["gap"] + carry))
            carry = 0.0
            continue
        touched = True
        left = (piece["in"], op.start) if piece["in"] < op.start else None
        right = (op.end, piece["out"]) if piece["out"] > op.end else None
        if not left and not right:
            carry += piece["gap"]            # the clip is gone; the gap before it stays
            continue
        for n, (start, end) in enumerate(x for x in (left, right) if x):
            result.append(dict(piece, **{"in": start, "out": end, "by": op.index,
                                         "gap": piece["gap"] + carry if n == 0 else 0.0}))
        carry = 0.0
    return result, touched


def _restore(pieces: list[dict], op: Operation, fps: float) -> tuple[list[dict], bool]:
    key = source_key(op.source)
    mine = [(p["in"], p["out"]) for p in pieces if source_key(p["source"]) == key]
    missing = [(s, e) for s, e in subtract_spans([(op.start, op.end)], merge_spans(mine))
               if e - s > 0.5 / fps]
    joins = 0.5 / fps
    for start, end in missing:
        same = [i for i, p in enumerate(pieces) if source_key(p["source"]) == key]
        before = [i for i in same if pieces[i]["out"] <= start + joins]
        after = [i for i in same if pieces[i]["in"] >= end - joins]
        # In recording order: right after the material that precedes it.
        at = (max(before, key=lambda i: pieces[i]["out"]) + 1 if before
              else min(after, key=lambda i: pieces[i]["in"]) if after else len(pieces))

        previous = pieces[at - 1] if at > 0 else None
        if previous and source_key(previous["source"]) == key and abs(previous["out"] - start) < joins:
            previous.update({"out": end, "by": op.index})
            target, at = previous, at - 1
        else:
            target = {"source": op.source, "in": start, "out": end, "gap": 0.0,
                      "by": op.index, "extra": {}}
            pieces.insert(at, target)
        following = pieces[at + 1] if at + 1 < len(pieces) else None
        if (following and source_key(following["source"]) == key and following["gap"] == 0.0
                and abs(following["in"] - end) < joins):
            target["out"] = following["out"]
            pieces.pop(at + 1)
    return pieces, bool(missing)


def apply(ir: dict, operations: list[Operation]) -> tuple[dict, list[str]]:
    """The project after the operations, and anything wrong with the result."""
    new = copy.deepcopy(ir)
    fps = new["project"]["fps"]
    track = new["tracks"][main_index(new)]
    pieces, problems = _pieces(track, fps), []

    for op in operations:
        if op.action == "remove":
            pieces, changed = _remove(pieces, op)
            if not changed:
                problems.append(f"operation {op.index}: nothing between {op.start:.2f}s and "
                                f"{op.end:.2f}s is in the cut, so there is nothing to remove")
        else:
            pieces, changed = _restore(pieces, op, fps)
            if not changed:
                problems.append(f"operation {op.index}: {op.start:.2f}-{op.end:.2f}s is already "
                                f"in the cut, so there is nothing to restore")

    if not pieces:
        problems.append("these operations remove everything from the main track")
    for piece in pieces:
        length = piece["out"] - piece["in"]
        if piece["by"] is not None and length < MIN_KEEP_SECONDS - 1e-9:
            problems.append(
                f"operation {piece['by']} leaves {length:.2f}s of {piece['in']:.2f}-"
                f"{piece['out']:.2f}s in the cut, a flash frame; cover it or remove less")

    _store(track, pieces)
    return new, problems


def check(doc: dict, ir: dict, changes: HumanChanges,
          pauses: dict[str, list[dict]] | None = None,
          durations: dict[str, float] | None = None) -> list[str]:
    """Every problem the editor needs to fix, or an empty list if the operations are accepted."""
    operations, problems = resolve(doc, ir, changes, pauses, durations)
    if problems:
        return problems
    return apply(ir, operations)[1]
