#!/usr/bin/env python3
"""Pictures and short clips made from a description, behind one interface, never
paid for above a cap.

A storyboard scene can ask for what none of the creator's files shows: a
`generated` visual, a picture or a clip, with what it should show. Before the
build makes any, it adds up what the new ones will cost and stops if that is
more than the video's cap - $0 unless the creator raises it with --budget, so
nothing paid runs without their say. Each is made once and kept by what it
shows, so building again costs nothing. Then it is an ordinary asset: a picture
gets the slow push in every image gets, a clip plays as made, and both land on
the main track as clips like any other.

Generators, chosen with FRAMEFLOW_GENERATOR, or Gemini when GEMINI_API_KEY is set:

  - gemini: Google's Gemini API, through its Interactions API - pictures from
    Nano Banana 2.1, clips from Gemini Omni Flash. Paid only: neither is on the
    API's free tier (Google's pricing page, 2026-11-03).
  - stand-in: free placeholder pictures and clips drawn by FFmpeg, different for
    each description, for trying a storyboard and for tests.
"""
import base64
import copy
import hashlib
import http.client
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from project.media import MediaError, _find_tool, analyze

API = "https://generativelanguage.googleapis.com/v1beta/interactions"
FOLDER = "generated"
# ponytail: Omni Flash decides a clip's length; the estimate assumes the longest it makes in one go.
CLIP_SECONDS = 10
TIMEOUT = 600           # seconds: a clip can take minutes to make


class GenerateError(Exception):
    pass


class StandIn:
    """Free placeholders: FFmpeg's moving test pattern, its hue set by the description."""
    name = "stand-in"
    prices = {"picture": 0.0, "clip": 0.0}

    def make(self, kind: str, prompt: str, aspect: str, out: Path) -> Path:
        from project.produce import SIZES       # produce imports this module
        width, height = SIZES[aspect]
        hue = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:4], 16) % 360
        path = out.with_suffix(".png" if kind == "picture" else ".mp4")
        path.parent.mkdir(parents=True, exist_ok=True)
        length = ["-frames:v", "1"] if kind == "picture" else \
            ["-t", str(CLIP_SECONDS), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast"]
        result = subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                                 f"testsrc2=s={width}x{height}:r=30", "-vf", f"hue=h={hue}", *length, str(path)],
                                capture_output=True, text=True, errors="replace")
        if result.returncode != 0:
            raise GenerateError(f"FFmpeg could not draw the stand-in: {result.stderr.strip()[-500:]}")
        return path


class Gemini:
    """Google's Gemini API, with the creator's key."""
    name = "gemini"
    MODELS = {"picture": "gemini-nano-banana-2.1", "clip": "gemini-omni-1.1-flash"}
    # Google's pricing page, 2026-11-03: a 2K picture $0.0504; a clip 5,792 tokens a second of 720p at $17.50 a million.
    prices = {"picture": 0.0504, "clip": round(CLIP_SECONDS * 5792 * 17.50 / 1e6, 4)}

    def __init__(self, key: str):
        self.key = key

    def make(self, kind: str, prompt: str, aspect: str, out: Path) -> Path:
        if kind == "picture":
            wanted, shape = "image", {"type": "image", "aspect_ratio": aspect, "image_size": "2K"}
        else:
            # Omni Flash cuts between shots and writes dialogue unless asked not to; the voiceover is the video's.
            prompt = f"{prompt.rstrip()} In a single continuous shot. No dialogue."
            wanted, shape = "video", {"type": "video", "aspect_ratio": "9:16" if aspect == "9:16" else "16:9"}
        body = {"model": self.MODELS[kind], "input": prompt, "store": False, "response_format": shape}
        request = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as e:
            try:
                said = json.loads(e.read()).get("error", {}).get("message") or e.reason
            except ValueError:
                said = e.reason
            raise GenerateError(f"Gemini refused the {kind} ({e.code}): {said}") from e
        except (OSError, http.client.HTTPException, ValueError) as e:
            raise GenerateError(f"Gemini could not be reached: {getattr(e, 'reason', e)}") from e
        made = [block for step in reply.get("steps", []) if step.get("type") == "model_output"
                for block in step.get("content", []) if block.get("type") == wanted and block.get("data")]
        if not made:
            raise GenerateError(f"Gemini sent back no {kind} for {prompt!r}")
        suffix = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(made[-1].get("mime_type"),
                                                                   ".png" if kind == "picture" else ".mp4")
        path = out.with_suffix(suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(made[-1]["data"]))
        return path


def generator() -> StandIn | Gemini | None:
    """The generator the environment sets up, or None."""
    choice = os.environ.get("FRAMEFLOW_GENERATOR") or ("gemini" if os.environ.get("GEMINI_API_KEY") else "")
    if choice == "stand-in":
        return StandIn()
    if choice == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            raise GenerateError("FRAMEFLOW_GENERATOR is gemini, but GEMINI_API_KEY is not set")
        return Gemini(os.environ["GEMINI_API_KEY"])
    if choice:
        raise GenerateError(f"FRAMEFLOW_GENERATOR is {choice!r}: it can be gemini or stand-in")
    return None


def _stem(folder: Path, maker, visual: dict, aspect: str) -> Path:
    """Where this visual is kept, less its suffix: named for what it shows and what made it."""
    what = f"{maker.name}|{getattr(maker, 'MODELS', {}).get(visual['kind'], '')}|{visual['kind']}|{aspect}|{visual['prompt']}"
    return folder / FOLDER / hashlib.sha256(what.encode("utf-8")).hexdigest()[:16]


def _kept(stem: Path) -> Path | None:
    return next(iter(sorted(stem.parent.glob(stem.name + ".*"))), None) if stem.parent.is_dir() else None


def make_all(folder: Path, board: dict, inputs: dict, aspect: str, budget: float,
             maker=None) -> tuple[dict, dict, float]:
    """Make every generated visual not made already, as long as the new ones cost no more than `budget`
    dollars. Returns the storyboard and inputs with each one an asset, and what was spent; the ones
    passed in are left as they are."""
    wanted = [(n, scene["visual"]) for n, scene in enumerate(board["scenes"], start=1)
              if scene["visual"]["type"] == "generated"]
    if not wanted:
        return board, inputs, 0.0
    maker = maker or generator()
    if maker is None:
        raise GenerateError("the storyboard asks for generated pictures or clips, but no generator is set up: set "
                            "GEMINI_API_KEY for Google's Gemini (paid), or FRAMEFLOW_GENERATOR=stand-in for free "
                            "placeholders")
    new = [(n, v) for n, v in wanted if _kept(_stem(folder, maker, v, aspect)) is None]
    cost = sum(maker.prices[v["kind"]] for _, v in new)
    if cost > budget + 1e-9:
        raise GenerateError(
            f"making {len(new)} generated picture(s) and clip(s) with {maker.name} would cost about ${cost:.2f}, "
            f"over this video's cap of ${budget:.2f}:\n"
            + "\n".join(f"  scene {n}, a {v['kind']} of {v['prompt']!r}: ${maker.prices[v['kind']]:.2f}" for n, v in new)
            + f"\nTo allow it, build again with --budget {cost:.2f}.")
    for n, v in new:
        print(f"    scene {n}: making a {v['kind']} with {maker.name} (about ${maker.prices[v['kind']]:.2f})", flush=True)
        maker.make(v["kind"], v["prompt"], aspect, _stem(folder, maker, v, aspect))
    board, inputs = copy.deepcopy(board), copy.deepcopy(inputs)
    for scene in board["scenes"]:
        visual = scene["visual"]
        if visual["type"] != "generated":
            continue
        path = _kept(_stem(folder, maker, visual, aspect)).resolve().as_posix()
        scene["visual"] = {"type": "asset", "path": path}
        if any(a["path"] == path for a in inputs["assets"]):
            continue
        if visual["kind"] == "picture":
            inputs["assets"].append({"path": path, "kind": "image"})
        else:
            try:
                info = analyze(path)
            except MediaError as e:
                raise GenerateError(f"the clip made for {visual['prompt']!r} cannot be read: {e}") from e
            inputs["assets"].append({"path": path, "kind": "clip", "duration": info.duration_seconds,
                                     "size": f"{info.width}x{info.height}"})
    return board, inputs, round(cost, 4)
