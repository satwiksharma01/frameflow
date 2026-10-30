#!/usr/bin/env python3
"""Graphics made by HyperFrames, as clips the creator can still move and trim.

A clip with `"generator": "hyperframes"` and no source is rendered here to a
transparent ProRes 4444 .mov (HyperFrames' `--format mov`), which then sits on
its own track like any other media. The project stays editable: the creator
moves, trims or deletes the graphic in their editor like footage.

What is rendered:
  - `generator_params.composition`: a HyperFrames project folder the AI wrote
    (its index.html), rendered as it is, at the project's frame rate.
  - otherwise a text card showing the clip's `text`, sized to the project.

Renders are cached by content in the project's graphics/ folder, so building
the same project again does not render again.
"""
import hashlib
import html
import shutil
import subprocess
from pathlib import Path

from project.compile_mlt import fps_to_fraction

VERSION = "0.8.199"
GRAPHICS_DIR = "graphics"


def _rate(fps: float) -> str:
    """HyperFrames refuses "30.0": a whole rate, or an exact fraction like 30000/1001."""
    num, den = fps_to_fraction(fps)
    return str(num) if den == 1 else f"{num}/{den}"

# The built-in card animates without GSAP: HyperFrames seeks any object in
# window.__timelines, and GSAP's license is not one Frameflow can ship under.
_CARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width={w},height={h}"><title>card</title>
<style>
*{{box-sizing:border-box;margin:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;background:transparent;font-family:Arial,Helvetica,sans-serif}}
#root{{width:{w}px;height:{h}px;position:relative}}
#card{{position:absolute;left:50%;bottom:{bottom}px;max-width:{max_w}px;padding:{pad_y}px {pad_x}px;
  border-radius:{radius}px;background:rgba(16,24,39,.78);color:#fff;font-size:{size}px;font-weight:700;
  line-height:1.2;text-align:center;opacity:0;transform:translateX(-50%)}}
</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="{d}" data-width="{w}" data-height="{h}" data-fps="{fps}">
<div id="card" class="clip" data-start="0" data-duration="{d}" data-track-index="0">{text}</div></div>
<script>
const card = document.getElementById("card"), D = {d}, IN = 0.4, OUT = 0.3;
let now = 0;
function show(t) {{
  const k = Math.max(0, Math.min(1, t / IN, (D - t) / OUT));
  const ease = 1 - Math.pow(1 - k, 3);
  card.style.opacity = ease;
  card.style.transform = "translateX(-50%) translateY(" + ((1 - ease) * {rise}) + "px)";
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


class HyperFramesError(Exception):
    pass


def card_html(text: str, width: int, height: int, fps: float, duration: float) -> str:
    unit = min(width, height) / 1080      # sized for 1080 on the short side; portrait fits too
    return _CARD.format(
        w=width, h=height, fps=_rate(fps), d=round(duration, 6), text=html.escape(text),
        bottom=round(height * 0.11), max_w=round(width * 0.84), pad_y=round(26 * unit),
        pad_x=round(44 * unit), radius=round(22 * unit), size=round(60 * unit), rise=round(90 * unit))


def _npx() -> str:
    found = shutil.which("npx")
    if not found:
        raise HyperFramesError("HyperFrames needs Node.js (npx); install Node.js 22 or newer")
    return found


def render(composition: Path, out: Path, fps: float) -> Path:
    """Render a HyperFrames project folder to a transparent .mov."""
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [_npx(), "-y", f"hyperframes@{VERSION}", "render", str(composition), "--format", "mov",
         "--fps", _rate(fps), "--output", str(out.resolve()), "--quiet"],
        capture_output=True, text=True, errors="replace", timeout=3600,
    )
    if result.returncode != 0 or not out.exists():
        raise HyperFramesError(f"HyperFrames could not render {composition}: "
                               f"{(result.stderr or result.stdout)[-2000:]}")
    return out


def _digest(folder: Path, extra: str) -> str:
    h = hashlib.sha256(extra.encode())
    for f in sorted(p for p in folder.rglob("*") if p.is_file()):
        h.update(f.relative_to(folder).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def render_clip(clip: dict, project: dict, folder: Path) -> Path:
    """The rendered file for one generated clip, rendering it if not cached."""
    graphics = folder / GRAPHICS_DIR
    fps = project["fps"]
    composition = (clip.get("generator_params") or {}).get("composition")
    if composition:
        source = Path(composition)
        if not (source / "index.html").exists():
            raise HyperFramesError(f"clip {clip['id']!r}: {source} has no index.html")
    else:
        if not clip.get("text"):
            raise HyperFramesError(f"clip {clip['id']!r} has neither text nor a composition")
        page = card_html(clip["text"], project["width"], project["height"], fps,
                         clip["timeline_duration"])
        source = graphics / "cards" / hashlib.sha256(page.encode()).hexdigest()[:16]
        source.mkdir(parents=True, exist_ok=True)
        (source / "index.html").write_text(page, encoding="utf-8")
    out = graphics / f"{_digest(source, f'{VERSION}|{fps}')}.mov"
    return out if out.exists() else render(source, out, fps)


def render_generated(ir: dict, folder: Path) -> dict:
    """Give every HyperFrames clip with no source its rendered file. Changes `ir` in place."""
    for track in ir["tracks"]:
        for clip in track["clips"]:
            if clip.get("generator") == "hyperframes" and "source" not in clip:
                clip["source"] = render_clip(clip, ir["project"], folder).resolve().as_posix()
                clip["source_in"] = 0.0
                clip["source_out"] = clip["timeline_duration"]
    return ir
