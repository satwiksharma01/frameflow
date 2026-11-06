#!/usr/bin/env python3
"""Captions that pop in word by word as they are said.

The words come from Whisper's timings for a recording, or from the voice that
read the narration. They are grouped into short lines that never cross a cut,
and each line is a clip on the Captions track, so the creator can move, trim
or delete one like any other clip.

All the lines are drawn by one HyperFrames render, back to back in a single
transparent .mov, and each clip plays its own span of it. A render costs about
25 s to start up, so rendering each line on its own would take hours on a long
video.
"""
import hashlib
import json
from pathlib import Path

from project import hyperframes
from project.operations import main_index
from project.reconcile import merge_spans, source_key, subtract_spans

TRACK_ID = "Captions"
BREAK_SECONDS = 0.35    # a pause this long between words starts a new line
TAIL_SECONDS = 0.3      # a line stays up this long after its last word,
HOLD_SECONDS = 0.5      # or until the next line, if that starts this soon after
LONGEST_WORD = 1.5      # Whisper can stretch one word over seconds of noise
SHORTEST_LINE = 0.3     # a line up for less flickers, so it takes the word before it

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width={w},height={h}"><title>captions</title>
<style>
{font_face}*{{box-sizing:border-box;margin:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;background:transparent}}
#root{{width:{w}px;height:{h}px;position:relative}}
.line{{position:absolute;left:50%;top:{y}px;transform:translate(-50%,-50%);width:max-content;max-width:{max_w}px;
  display:none;text-align:center;font-family:{family};font-weight:900;
  font-size:{size}px;line-height:1.15;color:{text};-webkit-text-stroke:{stroke}px {outline};paint-order:stroke fill;
  text-shadow:0 {shadow}px {blur}px rgba(0,0,0,.55)}}
.line span{{display:inline-block;margin:0 {gap}px}}
</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="{d}" data-width="{w}" data-height="{h}" data-fps="{fps}">
<div id="lines" class="clip" data-start="0" data-duration="{d}" data-track-index="0"></div></div>
<script>
// [line start, line end, [[word start, word], ...]], in seconds of this render.
const LINES = {lines}, D = {d}, POP = 0.12, EPS = {eps}, HIGHLIGHT = "{highlight}", TEXT = "{text}";
const box = document.getElementById("lines");
const els = LINES.map(([, , words]) => {{
  const line = document.createElement("div");
  line.className = "line";
  for (const [, word] of words) {{
    const span = document.createElement("span");
    span.textContent = word;
    line.appendChild(span);
  }}
  box.appendChild(line);
  return line;
}});
let now = 0;
function show(t) {{
  LINES.forEach(([start, end, words], i) => {{
    const on = t >= start - EPS && t < end - EPS;
    els[i].style.display = on ? "block" : "none";
    if (!on) return;
    const said = words.filter(([at]) => t >= at - EPS).length;
    words.forEach(([at], j) => {{
      const span = els[i].children[j], k = Math.min(1, Math.max(0, (t - at) / POP));
      span.style.opacity = j < said ? 1 : 0;
      span.style.transform = "scale(" + (0.7 + 0.3 * (1 - Math.pow(1 - k, 3))) + ")";
      span.style.color = j === said - 1 ? HIGHLIGHT : TEXT;
    }});
  }});
}}
const timeline = {{
  seek(t) {{ now = t; show(t); return timeline; }},
  time() {{ return now; }}, duration() {{ return D; }}, totalDuration() {{ return D; }},
  progress() {{ return now / D; }}, pause() {{ return timeline; }}, play() {{ return timeline; }},
  paused() {{ return true; }}, isActive() {{ return false; }},
}};
window.__timelines = {{ main: timeline }};
timeline.seek(0);
</script></body></html>
"""


def run(words: list[dict], source_in: float, source_out: float, at: float) -> dict:
    """The words said between source_in and source_out, moved to play from `at` on the timeline.
    A run is what a line may not cross: one clip of a cut, or one scene."""
    shift = at - source_in
    return {"start": at, "end": at + source_out - source_in,
            "words": [{"start": w["start"] + shift, "end": min(w["end"], source_out) + shift, "text": w["text"]}
                      for w in words if source_in <= w["start"] < source_out]}


def runs_from_cut(ir: dict, words: dict[str, list[dict]]) -> list[dict]:
    """A run for every main-track clip of a recording with word timings, keyed by source_key."""
    clips = sorted(ir["tracks"][main_index(ir)]["clips"], key=lambda c: c["timeline_start"])
    return [run(words[source_key(c["source"])], c["source_in"], c["source_out"], c["timeline_start"])
            for c in clips if source_key(c["source"]) in words]


def lines(runs: list[dict], fps: float, max_chars: int) -> list[dict]:
    """Short lines of words, in frames: {"start", "end", "words": [(frame, text), ...]}."""
    found = []
    for r in runs:
        groups: list[list[dict]] = []
        for w in r["words"]:
            g = groups[-1] if groups else None
            if (g and w["start"] - g[-1]["end"] < BREAK_SECONDS and g[-1]["text"][-1] not in ".?!"
                    and len(" ".join(x["text"] for x in g + [w])) <= max_chars):
                g.append(w)
            else:
                groups.append([w])
        for i in range(1, len(groups)):
            before, g = groups[i - 1], groups[i]
            following = groups[i + 1][0]["start"] if i + 1 < len(groups) else r["end"]
            if (following - g[0]["start"] < SHORTEST_LINE and len(before) > 1
                    and before[-1]["start"] - before[0]["start"] >= SHORTEST_LINE
                    and before[-1]["text"][-1] not in ".?!" and g[0]["start"] - before[-1]["end"] < HOLD_SECONDS
                    and len(" ".join(x["text"] for x in before[-1:] + g)) <= max_chars):
                g.insert(0, before.pop())
        stop = round(r["end"] * fps)
        for i, g in enumerate(groups):
            start = round(g[0]["start"] * fps)
            following = round(groups[i + 1][0]["start"] * fps) if i + 1 < len(groups) else stop
            last = g[-1]
            end = round((min(last["end"], last["start"] + LONGEST_WORD) + TAIL_SECONDS) * fps)
            if following - end < HOLD_SECONDS * fps:
                end = following
            end = min(end, following, stop)
            if end > start:
                found.append({"start": start, "end": end,
                              "words": [(round(w["start"] * fps), w["text"]) for w in g]})
    return found


def page(found: list[dict], width: int, height: int, fps: float,
         kit: dict = hyperframes.BRAND, at: float | None = None) -> tuple[str, list[int]]:
    """One composition showing every line back to back, in the brand kit's style, and the
    frame each line starts at in it. `at` puts the lines' middle that far down the frame instead."""
    rows, offsets, offset = [], [], 0
    for line in found:
        offsets.append(offset)
        rows.append([offset / fps, (offset + line["end"] - line["start"]) / fps,
                     [[(f - line["start"] + offset) / fps, text.upper() if kit["uppercase_captions"] else text]
                      for f, text in line["words"]]])
        offset += line["end"] - line["start"]
    unit = min(width, height) / 1080
    portrait = height > width
    font_face, family = hyperframes.brand_css(kit, '"Arial Black",Arial,Helvetica,sans-serif')
    html = _PAGE.format(
        w=width, h=height, fps=hyperframes._rate(fps), d=round(offset / fps, 6), eps=0.5 / fps,
        lines=json.dumps(rows, ensure_ascii=False).replace("</", "<\\/"), highlight=kit["accent"],
        text=kit["text"], font_face=font_face, family=family, outline=hyperframes.contrast(kit["text"]),
        # Portrait: above the app's buttons and text at the bottom of a reel.
        y=round(height * (at if at is not None else 0.68 if portrait else 0.84)), max_w=round(width * 0.86),
        size=round((84 if portrait else 72) * unit), stroke=round(10 * unit), shadow=round(6 * unit),
        blur=round(14 * unit), gap=round(8 * unit))
    return html, offsets


def add(ir: dict, runs: list[dict], folder: Path, at: float | None = None) -> int:
    """Render captions for these runs onto the Captions track, `at` that far down the frame if
    given. Changes `ir` in place; returns how many lines there are."""
    project = ir["project"]
    fps, width, height = project["fps"], project["width"], project["height"]
    # What fits on one line at the font size page() picks, measured in Arial Black capitals.
    found = lines(runs, fps, 14 if width <= height else 28)
    if not found:
        return 0
    kit = hyperframes.brand()
    html, offsets = page(found, width, height, fps, kit, at)
    composition = folder / hyperframes.GRAPHICS_DIR / "captions" / hashlib.sha256(html.encode()).hexdigest()[:16]
    composition.mkdir(parents=True, exist_ok=True)
    (composition / "index.html").write_text(html, encoding="utf-8")
    hyperframes.brand_files(kit, composition)
    movie = hyperframes.render_cached(composition, folder, fps).resolve().as_posix()

    track = next((t for t in ir["tracks"] if t["id"] == TRACK_ID), None)
    if track is None:
        track = {"id": TRACK_ID, "type": "captions", "clips": []}
        ir["tracks"].append(track)
    for line, offset in zip(found, offsets):
        length = line["end"] - line["start"]
        track["clips"].append({
            "id": "", "source": movie, "source_in": round(offset / fps, 6),
            "source_out": round((offset + length) / fps, 6), "timeline_start": round(line["start"] / fps, 6),
            "timeline_duration": round(length / fps, 6), "generator": "hyperframes",
            "text": " ".join(text for _, text in line["words"])})
    track["clips"].sort(key=lambda c: c["timeline_start"])
    for n, clip in enumerate(track["clips"], start=1):
        clip["id"] = f"clip{n}"
    return len(found)


def follow_cut(before: dict, after: dict, words: dict[str, list[dict]], folder: Path) -> dict[str, int]:
    """After an edit changed the main track, put the captions back in sync with it.

    Each line moves to where its moment of the recording now plays; a line
    whose moment was removed goes with it, and one now running into a cut stops
    there. Lines the creator moved, trimmed or deleted by hand are moved, kept
    trimmed or stay deleted. Speech that plays without a line - put back by the
    edit, or left over from a line that went or was cut short - gets new lines
    from `words`. Changes `after` in place; returns how many lines moved, went
    and were added.
    """
    tracks = [t for t in after["tracks"] if t["type"] == "captions" and t["clips"]]
    counts = {"moved": 0, "removed": 0, "added": 0}
    if not tracks:
        return counts
    old = before["tracks"][main_index(before)]["clips"]
    new = after["tracks"][main_index(after)]["clips"]
    lost: dict[str, list] = {}       # recording spans whose words this edit left without a line
    shown: dict[str, list] = {}      # recording spans a line still shows
    for track in tracks:
        kept = []
        for clip in track["clips"]:
            under = next((c for c in old if c["timeline_start"] <= clip["timeline_start"]
                          < c["timeline_start"] + c["timeline_duration"]), None)
            if under is None:                     # over a gap: nothing to follow
                kept.append(clip)
                continue
            key = source_key(under["source"])
            moment = under["source_in"] + clip["timeline_start"] - under["timeline_start"]
            target = next((c for c in new if source_key(c["source"]) == key
                           and c["source_in"] <= moment < c["source_out"]), None)
            if target is None:
                counts["removed"] += 1
                lost.setdefault(key, []).append((moment, moment + clip["timeline_duration"]))
                continue
            start = round(target["timeline_start"] + moment - target["source_in"], 6)
            room = round(target["timeline_start"] + target["timeline_duration"] - start, 6)
            if clip["timeline_duration"] > room:
                lost.setdefault(key, []).append((moment + room, moment + clip["timeline_duration"]))
                if "source_out" in clip:
                    clip["source_out"] = round(clip["source_out"] - (clip["timeline_duration"] - room), 6)
                clip["timeline_duration"] = room
            shown.setdefault(key, []).append((moment, moment + clip["timeline_duration"]))
            counts["moved"] += clip["timeline_start"] != start
            clip["timeline_start"] = start
            kept.append(clip)
        track["clips"] = sorted(kept, key=lambda c: c["timeline_start"])
        for n, clip in enumerate(track["clips"], start=1):
            clip["id"] = f"clip{n}"

    runs = []
    for key in {source_key(c["source"]) for c in new} & set(words):
        had = merge_spans([(c["source_in"], c["source_out"]) for c in old if source_key(c["source"]) == key])
        lines_lost = subtract_spans(merge_spans(lost.get(key, [])), merge_spans(shown.get(key, [])))
        for c in new:
            if source_key(c["source"]) != key:
                continue
            span = [(c["source_in"], c["source_out"])]
            put_back = subtract_spans(span, had)
            left_over = subtract_spans(span, subtract_spans(span, lines_lost))     # span within lines_lost
            for s, e in put_back + left_over:
                runs.append(run(words[key], s, e, c["timeline_start"] + s - c["source_in"]))
    counts["added"] = add(after, sorted(runs, key=lambda r: r["start"]), folder) if runs else 0
    return counts
