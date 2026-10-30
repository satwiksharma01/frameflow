#!/usr/bin/env python3
"""Listen to the finished cuts and report any that swallowed a word.

Validation proves the plan is coherent; it cannot prove the result sounds
right. This does: render the project's audio through the real engine, then
re-transcribe a few seconds around each join and check the words either side
of the cut survived.

Two details that matter, both learned the hard way:
  - The check runs on the **rendered** audio, not on spans stitched together
    from the source. A cut that reads fine when ffmpeg concatenates the pieces
    can still lose a word once MLT renders it, because each clip boundary
    loses up to a frame.
  - Each join is transcribed as its own short clip. Transcribing a long render
    in one pass makes Whisper loop and repeat whole passages, which looks
    exactly like a duplicated clip.

An OpenShot project is rendered by libopenshot, OpenShot's own engine, run
without a window through Frameflow's build of OpenShot (openshot_build). Only
where OpenShot is not installed is it heard as its file states it: FFmpeg
mixes the main track at the timings read back from the .osp, which catches a
cut placed mid-word but not anything OpenShot adds at a clip boundary.
"""
import difflib
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from project import openshot_build
from project.engine_check import find_melt
from project.media import _find_tool
from project.parse_osp import parse_osp
from project.transcribe import TranscriptionError, find_model, find_whisper_cli, run_whisper

# Seconds of rendered audio to listen to either side of a join.
CONTEXT_SECONDS = 2.5

# How closely a heard word must match the expected one. Whisper is
# inconsistent with proper nouns ("Claude" / "cloud"), so this is deliberately
# forgiving: it is looking for a missing word, not a misspelled one.
MATCH_RATIO = 0.7


class VerificationError(Exception):
    pass


@dataclass
class JoinCheck:
    index: int
    timeline_seconds: float
    expected_before: str
    expected_after: str
    heard: str
    ok: bool

    @property
    def summary(self) -> str:
        where = f"{int(self.timeline_seconds) // 60}:{self.timeline_seconds % 60:05.2f}"
        if self.ok:
            return f"join {self.index} at {where}: ok"
        return (f"join {self.index} at {where}: expected "
                f"...{self.expected_before!r} | {self.expected_after!r}... but heard {self.heard!r}")


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w]


def word_survived(word: str, heard_tokens: list[str]) -> bool:
    """Is this word present in what was heard, allowing for Whisper's wobble?"""
    target = tokenize(word)
    if not target:
        return True
    needle = target[-1]
    return any(difflib.SequenceMatcher(None, needle, t).ratio() >= MATCH_RATIO
               for t in heard_tokens)


def words_in_clip(words: list[dict], clip: dict, tolerance: float = 0.05) -> list[dict]:
    """Words that fall inside a clip's source range.

    Containment matters, not just "after the cut". Whisper's word timings drift
    badly around hesitations - on one recording it stretched a single "so"
    across three seconds - and a word picked by proximity alone can turn out to
    sit in the span that was deliberately removed.
    """
    return [w for w in words
            if w["start"] >= clip["source_in"] - tolerance
            and w["end"] <= clip["source_out"] + tolerance]


def words_at_boundary(words: list[dict], left: dict, right: dict) -> tuple[str, str]:
    """The last word of the outgoing clip and the first of the incoming one.

    Either can be empty when the word timings in that stretch are too unreliable
    to name one; the caller simply checks whichever side it has.
    """
    before = words_in_clip(words, left)
    after = words_in_clip(words, right)
    return (before[-1]["text"] if before else "", after[0]["text"] if after else "")


def render_audio(mlt_path: Path | str, out_wav: Path | str) -> Path:
    melt = find_melt()
    if melt is None:
        raise VerificationError("melt not found; cannot render the project to verify it")
    result = subprocess.run(
        [melt, str(mlt_path), "-consumer", f"avformat:{out_wav}", "vn=1", "ar=16000", "ac=1"],
        capture_output=True, text=True, errors="replace", timeout=3600,
    )
    if not Path(out_wav).exists():
        raise VerificationError(f"rendering the project's audio failed: {result.stderr[-2000:]}")
    return Path(out_wav)


def render_track_audio(clips: list[dict], out_wav: Path | str) -> Path:
    """Mix one track's clips at their timeline positions, gaps left silent."""
    if not clips:
        raise VerificationError("the main track has no clips to render")
    sources = list(dict.fromkeys(c["source"] for c in clips))
    inputs = [arg for source in sources for arg in ("-i", source)]
    parts = [
        f"[{sources.index(c['source'])}:a]atrim={c['source_in']:.6f}:{c['source_out']:.6f},"
        f"asetpts=PTS-STARTPTS,adelay={round(c['timeline_start'] * 1000)}:all=1[a{n}]"
        for n, c in enumerate(clips)
    ]
    # One track's clips never overlap, so summing them unscaled is just placing them.
    mix = "".join(f"[a{n}]" for n in range(len(clips))) + \
        f"amix=inputs={len(clips)}:normalize=0:dropout_transition=0[out]"
    result = subprocess.run(
        [_find_tool("ffmpeg"), "-y", "-v", "error", *inputs,
         "-filter_complex", ";".join(parts + [mix]), "-map", "[out]",
         "-ac", "1", "-ar", "16000", str(out_wav)],
        capture_output=True, text=True, errors="replace", timeout=3600,
    )
    if not Path(out_wav).exists():
        raise VerificationError(f"rendering the project's audio failed: {result.stderr[-2000:]}")
    return Path(out_wav)


def render_osp_audio(osp_path: Path | str, out_wav: Path | str) -> Path:
    if openshot_build.install_dir() is None:
        return render_track_audio(parse_osp(osp_path)["tracks"][0]["clips"], out_wav)
    osp_path = Path(osp_path).resolve()
    result = openshot_build.run_script(Path(__file__).parent / "openshot_render.py",
                                       str(osp_path), str(Path(out_wav).resolve()), "--main-track",
                                       cwd=osp_path.parent)
    if result.returncode != 0 or not Path(out_wav).exists():
        raise VerificationError(f"OpenShot could not render the project's audio: {result.stderr[-2000:]}")
    return Path(out_wav)


def _hear(wav: Path, start: float, end: float, model: Path, tmp: Path) -> str:
    clip = tmp / "join.wav"
    subprocess.run(
        [_find_tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{max(0.0, start):.3f}",
         "-t", f"{end - max(0.0, start):.3f}", "-i", str(wav),
         "-ac", "1", "-ar", "16000", str(clip)],
        capture_output=True, timeout=300,
    )
    whisper = run_whisper(clip, model, "en", tmp / "heard")
    return " ".join(seg.get("text", "").strip() for seg in whisper.get("transcription", []))


def verify_joins(ir: dict, timing: dict, project_path: Path | str,
                 model: Path | str | None = None,
                 context: float = CONTEXT_SECONDS,
                 include: Callable[[dict, dict], bool] | None = None,
                 render: Callable[[Path | str, Path | str], Path] = render_audio) -> list[JoinCheck]:
    """Render the project and check the words either side of every cut survived.

    `include(left, right)` limits the check to some joins - an edit that makes
    two new cuts should not spend a Whisper pass on each of the thirty it left alone.
    `render` is the project's editor's: melt for Shotcut, render_osp_audio for OpenShot.
    """
    try:
        find_whisper_cli()  # fail fast with a clear message if it is missing
        model_path = find_model(model)
    except TranscriptionError as e:
        # The project is already built; a missing tool means "not listened to", not "failed".
        raise VerificationError(str(e)) from e
    clips = ir["tracks"][0]["clips"]
    words = timing["words"]
    checks: list[JoinCheck] = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        rendered = render(project_path, tmp_path / "rendered.wav")

        for i, (left, right) in enumerate(zip(clips, clips[1:]), start=1):
            joined_at = left["timeline_start"] + left["timeline_duration"]
            if abs(right["timeline_start"] - joined_at) > 0.05:
                continue  # a gap, not a join - nothing to clip
            if include is not None and not include(left, right):
                continue
            before, after = words_at_boundary(words, left, right)
            if not before and not after:
                continue

            heard = _hear(rendered, joined_at - context, joined_at + context, model_path, tmp_path)
            tokens = tokenize(heard)
            ok = word_survived(before, tokens) and word_survived(after, tokens)
            checks.append(JoinCheck(i, joined_at, before, after, heard.strip(), ok))

    return checks
