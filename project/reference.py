#!/usr/bin/env python3
"""Make it like this: a reference video's structure, remade with the creator's own media.

Agent Video (agent-video/, Node 22) does the reference side. It measures the
reference's shots and pacing and writes a request in which the agent - looking
at the reference itself - describes its hook, captions, look and sound, each
with the stretch of the reference that shows it, then writes two or three
concepts, each a storyboard built from the creator's footage and assets. Agent
Video checks them and exports the chosen one. Frameflow hands it the
recordings it has prepared, with their measured pauses, and takes the
storyboard back into the prompt workflow, so the video is built, checked and
edited like any other.

    python -m project.produce <folder> --reference <video>      after the brief is confirmed
    (the agent follows reference/session/analysis-request.md, writing analysis.json and concepts.json there)
    python -m project.produce <folder> --concepts               checked, and listed for the creator
    python -m project.produce <folder> --concept <id> [--sample SECONDS]
"""
import json
import shutil
import subprocess
from pathlib import Path

from project.first_cut import TIMING_FILE

AGENT_VIDEO = Path(__file__).resolve().parent.parent / "agent-video" / "bin" / "agent-video.mjs"
FOLDER = "reference"
# What Agent Video's inventory and brief carry; it refuses anything else, such as a storyboard's looks.
_INPUTS = ("prompt", "script", "footage", "assets", "music")
_BRIEF = ("title", "format", "aspect", "fps", "target_seconds", "audience", "tone", "summary")


class AgentVideoError(Exception):
    pass


def _run(*args: str) -> dict:
    """Run an Agent Video command; its JSON answer, or AgentVideoError with what it said."""
    node = shutil.which("node")
    if node is None:
        raise AgentVideoError("Agent Video needs Node.js 22 or newer")
    result = subprocess.run([node, str(AGENT_VIDEO), *args, "--json"], capture_output=True, text=True,
                            errors="replace", timeout=3600)
    try:
        reply = json.loads(result.stdout)
    except ValueError:
        raise AgentVideoError(f"Agent Video did not answer: {(result.stderr or result.stdout).strip()[-800:]}") from None
    if not reply.get("ok"):
        error = reply.get("error") or {}
        raise AgentVideoError(f"Agent Video: {error.get('message', 'it failed')} ({error.get('code', 'no code')})")
    return reply


def _write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _session(folder: Path) -> Path:
    session = folder / FOLDER / "session"
    if not session.is_dir():
        raise AgentVideoError(f"no reference session in {folder}; run --reference with the reference video first")
    return session


def prepare(folder: Path, video: Path, inputs: dict, brief: dict) -> Path:
    """Have Agent Video measure the reference against the creator's prepared media; the request the
    agent answers next."""
    work = folder / FOLDER
    if (work / "session").exists():
        raise AgentVideoError(f"there is already a reference session in {work / 'session'}; delete that folder to "
                             f"start again with another reference")
    work.mkdir(parents=True, exist_ok=True)
    timings = {}
    for f in inputs["footage"]:
        timing = json.loads((folder / f["folder"] / TIMING_FILE).read_text(encoding="utf-8"))
        timings[f["name"]] = {"pauses": [{"start": p["start"], "end": p["end"]} for p in timing["pauses"]],
                              "words": []}
    _write(work / "inputs.json", {k: inputs[k] for k in _INPUTS})
    _write(work / "brief.json", {k: brief[k] for k in _BRIEF if k in brief})
    _write(work / "source-timings.json", timings)
    reply = _run("reference-prepare", str(video), "--inputs", str(work / "inputs.json"),
                 "--brief", str(work / "brief.json"), "--timings", str(work / "source-timings.json"),
                 "--out-dir", str(work / "session"))
    return Path(reply["request"])


def concepts(folder: Path) -> list[dict]:
    """The agent's concepts, once Agent Video has checked them and the analysis."""
    session = _session(folder)
    _run("reference-check", str(session))
    return json.loads((session / "concepts.json").read_text(encoding="utf-8"))["concepts"]


def export(folder: Path, concept: str, sample: float | None = None) -> dict:
    """The storyboard of the chosen concept, or of its opening `sample` seconds, from a new handoff of
    Agent Video's; the handoff keeps it with its evidence."""
    session = _session(folder)
    stem = folder / FOLDER / (f"sample-{concept}" if sample else f"handoff-{concept}")
    out, n = stem, 1
    while out.exists():                 # Agent Video writes only into a new folder
        n += 1
        out = stem.with_name(f"{stem.name}-{n}")
    if sample:
        _run("reference-sample", str(session), "--concept", concept, "--seconds", f"{sample:g}", "--out-dir", str(out))
    else:
        _run("frameflow-export", str(session), "--concept", concept, "--out-dir", str(out))
    return json.loads((out / "storyboard.json").read_text(encoding="utf-8"))
