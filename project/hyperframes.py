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

Cards and captions take the creator's brand kit, brand/brand.json (its schema
is project/schema/brand.schema.json): their font, colours, logo and caption
style. What it leaves out keeps Frameflow's own look.

Renders are cached by content in the project's graphics/ folder, so building
the same project again does not render again.
"""
import hashlib
import html
import json
import shutil
import subprocess
from pathlib import Path

from project.compile_mlt import fps_to_fraction
from project.transcribe import REPO_ROOT
from project.validate import ValidationError, validate

VERSION = "0.8.199"
GRAPHICS_DIR = "graphics"
BRAND_FILE = REPO_ROOT / "brand" / "brand.json"
BRAND = {"font": None, "text": "#FFFFFF", "accent": "#FFE14D", "background": None, "logo": None,
         "uppercase_captions": True}
_FONT_SUFFIXES = {".ttf", ".otf", ".woff", ".woff2"}


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
{font_face}*{{box-sizing:border-box;margin:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden;background:transparent;font-family:{family}}}
#root{{width:{w}px;height:{h}px;position:relative;background:{screen}}}
#card{{position:absolute;left:50%;{anchor};width:max-content;max-width:{max_w}px;padding:{pad_y}px {pad_x}px;
  border-radius:{radius}px;background:{plate};color:{color};font-size:{size}px;font-weight:700;
  line-height:1.2;text-align:center;opacity:0;transform:{base}}}
#logo{{display:block;margin:0 auto {pad_y}px;max-width:100%;max-height:{logo_h}px}}
</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="{d}" data-width="{w}" data-height="{h}" data-fps="{fps}">
<div id="card" class="clip" data-start="0" data-duration="{d}" data-track-index="0">{logo}{text}</div></div>
<script>
const card = document.getElementById("card"), D = {d}, IN = 0.4, OUT = 0.3;
let now = 0;
function show(t) {{
  const k = Math.max(0, Math.min(1, t / IN, (D - t) / OUT));
  const ease = 1 - Math.pow(1 - k, 3);
  card.style.opacity = ease;
  card.style.transform = "{base} translateY(" + ((1 - ease) * {rise}) + "px)";
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


def brand() -> dict:
    """The creator's brand kit over Frameflow's own look, its font file and logo as absolute Paths."""
    if not BRAND_FILE.exists():
        return dict(BRAND)
    try:
        kit = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
        validate(kit, "brand")
    except (json.JSONDecodeError, ValidationError) as e:
        raise HyperFramesError(f"the brand kit {BRAND_FILE} needs fixing: {e}") from e
    for key in ("font", "logo"):
        if key in kit and (key == "logo" or Path(kit[key]).suffix.lower() in _FONT_SUFFIXES):
            kit[key] = (BRAND_FILE.parent / kit[key]).resolve()
            if not kit[key].is_file():
                raise HyperFramesError(f"the brand kit's {key}, {kit[key]}, is not there")
    return {**BRAND, **kit}


def brand_css(kit: dict, fallback: str) -> tuple[str, str]:
    """The @font-face for the kit's font file, if it has one, and the font-family list to use."""
    font = kit["font"]
    if isinstance(font, Path):      # weights 100-900 so the browser does not thicken it a second time
        return (f'@font-face{{font-family:"Brand";src:url("brand-font{font.suffix.lower()}");'
                f'font-weight:100 900}}\n', f'"Brand",{fallback}')
    return "", f'"{font}",{fallback}' if font else fallback


def brand_files(kit: dict, composition: Path) -> None:
    """Copy the kit's font and logo beside a composition's index.html, where its page looks for them."""
    for key in ("font", "logo"):
        if isinstance(kit[key], Path):
            shutil.copyfile(kit[key], composition / f"brand-{key}{kit[key].suffix.lower()}")


def card_html(text: str, width: int, height: int, fps: float, duration: float,
              layout: str = "lower", kit: dict = BRAND) -> str:
    """A text card: "lower" sits low in the frame over footage, "title" is centred and larger,
    on the kit's background and under its logo."""
    unit = min(width, height) / 1080      # sized for 1080 on the short side; portrait fits too
    title = layout == "title"
    font_face, family = brand_css(kit, "Arial,Helvetica,sans-serif")
    logo = title and isinstance(kit["logo"], Path)
    return _CARD.format(
        w=width, h=height, fps=_rate(fps), d=round(duration, 6), text=html.escape(text),
        font_face=font_face, family=family, color=kit["text"],
        screen=title and kit["background"] or "transparent",
        plate=f"{kit['background']}C7" if kit["background"] else "rgba(16,24,39,.78)",     # C7: 78% opaque
        logo=f'<img id="logo" src="brand-logo{kit["logo"].suffix.lower()}" alt="">' if logo else "",
        logo_h=round(240 * unit),
        anchor="top:50%" if title else f"bottom:{round(height * 0.11)}px",
        base="translate(-50%,-50%)" if title else "translateX(-50%)",
        max_w=round(width * 0.84), pad_y=round(26 * unit), pad_x=round(44 * unit),
        radius=round(22 * unit), size=round((96 if title else 60) * unit), rise=round(90 * unit))


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
        kit = brand()
        page = card_html(clip["text"], project["width"], project["height"], fps,
                         clip["timeline_duration"],
                         (clip.get("generator_params") or {}).get("layout", "lower"), kit)
        source = graphics / "cards" / hashlib.sha256(page.encode()).hexdigest()[:16]
        source.mkdir(parents=True, exist_ok=True)
        (source / "index.html").write_text(page, encoding="utf-8")
        brand_files(kit, source)
    return render_cached(source, folder, fps)


def render_cached(composition: Path, folder: Path, fps: float) -> Path:
    """A composition rendered into the project's graphics/ folder, unless it already is."""
    out = folder / GRAPHICS_DIR / f"{_digest(composition, f'{VERSION}|{fps}')}.mov"
    return out if out.exists() else render(composition, out, fps)


def render_generated(ir: dict, folder: Path) -> dict:
    """Give every HyperFrames clip with no source its rendered file. Changes `ir` in place."""
    for track in ir["tracks"]:
        for clip in track["clips"]:
            if clip.get("generator") == "hyperframes" and "source" not in clip:
                clip["source"] = render_clip(clip, ir["project"], folder).resolve().as_posix()
                clip["source_in"] = 0.0
                clip["source_out"] = clip["timeline_duration"]
    return ir
