#!/usr/bin/env python3
"""What did the human change since Frameflow last wrote the project?

The first half of reconciliation (TRD, "Sync design"). Two inputs:

  last_known  the IR Frameflow last wrote, kept in the sidecar
  current     the IR parsed from the .mlt, which the human may have edited

MLT cannot carry clip identity and Shotcut renumbers every clip on save, so
identity is inferred: a clip in `current` is the same clip as one in
`last_known` when both come from the same file and their source ranges
overlap. That is enough to tell a deletion from an addition, a trim from a
move, and a split from two unrelated clips.

Two views of the same comparison, because they answer different questions:

  - clip changes (deleted, added, trimmed, split, merged, moved) - what to
    tell the creator and the editor about what happened
  - span changes (removed, restored) - which parts of the recording the human
    took out or put back, which is what an operation must not quietly undo

The comparison runs in whole frames. The sidecar holds exact seconds while a
parsed project holds frame-rounded ones, so comparing seconds would report a
sliver of human "editing" at every boundary that nobody made.

Only the main track - the first video track - is compared: it is the track a
first cut writes and the one operations edit. Other tracks are reported by
count until something writes them (Phase 4).

Protection lasts one round. Once Frameflow writes again, the human's edits
become the new baseline; remembering human decisions across many rounds is
creator memory (Phase 9).

Usage:
    python -m project.reconcile <project.mlt>
"""
import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

Span = tuple[int, int]            # [start, end) in frames
Seconds = tuple[float, float]


def main_track(ir: dict) -> dict | None:
    return next((t for t in ir["tracks"] if t["type"] == "video"), None)


def source_key(source: str) -> str:
    """One spelling per file: Shotcut and our compiler may write the same path differently."""
    return os.path.normcase(str(Path(source).resolve()))


def merge_spans(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_spans(spans: list[Span], remove: list[Span]) -> list[Span]:
    result: list[Span] = []
    for start, end in spans:
        pieces = [(start, end)]
        for r_start, r_end in remove:
            next_pieces = []
            for p_start, p_end in pieces:
                if r_end <= p_start or r_start >= p_end:
                    next_pieces.append((p_start, p_end))
                    continue
                if p_start < r_start:
                    next_pieces.append((p_start, r_start))
                if r_end < p_end:
                    next_pieces.append((r_end, p_end))
            pieces = next_pieces
        result.extend(pieces)
    return result


@dataclass(frozen=True)
class _Clip:
    source: str      # source_key
    name: str        # file name, for reports
    span: Span


def _clips(ir: dict, fps: float) -> list[_Clip]:
    """Main-track clips in timeline order, source ranges in frames."""
    track = main_track(ir)
    if track is None:
        return []
    ordered = sorted((c for c in track["clips"] if "source" in c),
                     key=lambda c: c["timeline_start"])
    return [_Clip(source_key(c["source"]), Path(c["source"]).name,
                  (round(c["source_in"] * fps), round(c["source_out"] * fps)))
            for c in ordered]


def _coverage(clips: list[_Clip]) -> dict[str, list[Span]]:
    covered: dict[str, list[Span]] = {}
    for clip in clips:
        covered.setdefault(clip.source, []).append(clip.span)
    return {source: merge_spans(spans) for source, spans in covered.items()}


def _overlaps(a: _Clip, b: _Clip) -> bool:
    return a.source == b.source and min(a.span[1], b.span[1]) > max(a.span[0], b.span[0])


def _longest_increasing(seq: list[int]) -> set[int]:
    """The values in one longest strictly increasing subsequence.

    Clips outside it are the fewest that must have moved to explain the new
    order - so a deletion that ripples everything after it is not reported as
    every later clip moving.
    """
    if not seq:
        return set()
    best, prev = [1] * len(seq), [-1] * len(seq)
    for i in range(len(seq)):
        for k in range(i):
            if seq[k] < seq[i] and best[k] + 1 > best[i]:
                best[i], prev[i] = best[k] + 1, k
    i, kept = max(range(len(seq)), key=best.__getitem__), set()
    while i != -1:
        kept.add(seq[i])
        i = prev[i]
    return kept


@dataclass
class ClipChange:
    kind: str                 # deleted | added | trimmed | split | merged | moved
    name: str
    before: list[Seconds]
    after: list[Seconds]

    def describe(self) -> str:
        def spans(items):
            return " + ".join(f"{s:.2f}-{e:.2f}s" for s, e in items)
        if self.kind == "deleted":
            return f"deleted {spans(self.before)} of {self.name}"
        if self.kind == "added":
            return f"added {spans(self.after)} of {self.name}"
        if self.kind == "trimmed":
            return f"trimmed {spans(self.before)} to {spans(self.after)} of {self.name}"
        if self.kind == "split":
            return f"split {spans(self.before)} of {self.name} into {spans(self.after)}"
        if self.kind == "merged":
            return f"joined {spans(self.before)} of {self.name} into {spans(self.after)}"
        return f"moved {spans(self.after)} of {self.name} to a new position"


@dataclass
class HumanChanges:
    known: bool                                   # False with no sidecar to compare against
    removed: dict[str, list[Seconds]] = field(default_factory=dict)
    restored: dict[str, list[Seconds]] = field(default_factory=dict)
    clips: list[ClipChange] = field(default_factory=list)
    unchanged: int = 0
    other_tracks: str | None = None
    names: dict[str, str] = field(default_factory=dict)

    @property
    def any(self) -> bool:
        return bool(self.removed or self.restored or self.clips or self.other_tracks)

    def overlapping(self, which: str, source: str, start: float, end: float) -> list[Seconds]:
        """Spans of `which` ("removed" or "restored") that [start, end) touches."""
        spans = getattr(self, which).get(source_key(source), [])
        return [(s, e) for s, e in spans if min(e, end) - max(s, start) > 1e-6]

    def lines(self) -> list[str]:
        if not self.known:
            return ["No record of what Frameflow last wrote (no sidecar), so the human's "
                    "changes cannot be told apart from the original cut."]
        if not self.any:
            return ["No changes since Frameflow last wrote this project."]
        lines = [change.describe() for change in self.clips]
        if self.other_tracks:
            lines.append(self.other_tracks)
        if self.unchanged:
            lines.append(f"{self.unchanged} clip(s) unchanged")
        return lines


def reconcile(last_known: dict | None, current: dict) -> HumanChanges:
    if last_known is None:
        return HumanChanges(known=False)

    fps = current["project"]["fps"]     # one rate for both, so frames compare
    old, new = _clips(last_known, fps), _clips(current, fps)
    names = {c.source: c.name for c in old + new}

    def seconds(span: Span) -> Seconds:
        return (round(span[0] / fps, 3), round(span[1] / fps, 3))

    old_links = {i: [j for j, n in enumerate(new) if _overlaps(o, n)] for i, o in enumerate(old)}
    new_links = {j: [i for i, o in enumerate(old) if _overlaps(o, n)] for j, n in enumerate(new)}

    changes: list[ClipChange] = []
    one_to_one: list[tuple[int, int]] = []
    unchanged = 0
    for i, links in old_links.items():
        clip = old[i]
        if not links:
            changes.append(ClipChange("deleted", clip.name, [seconds(clip.span)], []))
        elif len(links) > 1:
            changes.append(ClipChange("split", clip.name, [seconds(clip.span)],
                                      [seconds(new[j].span) for j in links]))
        elif len(new_links[links[0]]) == 1:
            j = links[0]
            one_to_one.append((i, j))
            if new[j].span != clip.span:
                changes.append(ClipChange("trimmed", clip.name, [seconds(clip.span)],
                                          [seconds(new[j].span)]))
            else:
                unchanged += 1

    for j, links in new_links.items():
        clip = new[j]
        if not links:
            changes.append(ClipChange("added", clip.name, [], [seconds(clip.span)]))
        elif len(links) > 1:
            changes.append(ClipChange("merged", clip.name,
                                      [seconds(old[i].span) for i in links], [seconds(clip.span)]))

    in_new_order = [i for i, _ in sorted(one_to_one, key=lambda pair: pair[1])]
    stayed = _longest_increasing(in_new_order)
    for i, j in one_to_one:
        if i not in stayed:
            changes.append(ClipChange("moved", new[j].name, [seconds(old[i].span)],
                                      [seconds(new[j].span)]))
            if new[j].span == old[i].span:
                unchanged -= 1

    before, after = _coverage(old), _coverage(new)
    removed = {s: [seconds(x) for x in subtract_spans(spans, after.get(s, []))]
               for s, spans in before.items()}
    restored = {s: [seconds(x) for x in subtract_spans(spans, before.get(s, []))]
                for s, spans in after.items()}

    old_extra = sum(1 for t in last_known["tracks"] if t["clips"]) - (1 if old else 0)
    new_extra = sum(1 for t in current["tracks"] if t["clips"]) - (1 if new else 0)
    other = None
    if new_extra != old_extra:
        other = f"content tracks besides the main one: {old_extra} -> {new_extra}"

    return HumanChanges(
        known=True,
        removed={s: v for s, v in removed.items() if v},
        restored={s: v for s, v in restored.items() if v},
        clips=changes,
        unchanged=max(unchanged, 0),
        other_tracks=other,
        names=names,
    )


def main() -> None:
    from project.parse_mlt import parse_mlt
    from project.sidecar import read_sidecar

    parser = argparse.ArgumentParser(description="Report what changed since Frameflow last wrote a project.")
    parser.add_argument("mlt")
    args = parser.parse_args()
    changes = reconcile(read_sidecar(args.mlt), parse_mlt(args.mlt))
    for line in changes.lines():
        print(f"  {line}")


if __name__ == "__main__":
    main()
