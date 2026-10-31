#!/usr/bin/env python3
"""Speech-to-text plus silence detection for a source video.

Transcription uses whisper.cpp's CLI, so no PyTorch install. Any whisper-cli
works (on PATH, or Shotcut's); `--install` fetches the build OpenWhispr (MIT)
pins and tests, and a model OpenWhispr already downloaded is used if
Frameflow has none of its own. Whisper's segment timestamps are not trustworthy as cut
points on their own: they absorb the pauses around speech, so a segment can
start seconds before the words do. Silence is therefore measured separately
from the audio with ffmpeg's silencedetect, and both signals go to the editor.

Usage:
    python -m project.transcribe <video> [-o transcript.json] [--language auto]
    python -m project.transcribe --install      # fetch the engine (and a model if none)
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from project.media import _find_tool, analyze
from project.validate import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = REPO_ROOT / "models" / "ggml-large-v3-turbo-q5_0.bin"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin"
MODEL_SHA256 = "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"

# OpenWhispr's build of whisper.cpp: the release OpenWhispr pins and tests, with
# the MSVC runtime DLLs beside the exe so it runs without the VC++ redistributable.
OPENWHISPR_ENGINE_URL = ("https://github.com/OpenWhispr/whisper.cpp/releases/download/0.0.11/"
                         "whisper-cpp-win32-x64-cpu.zip")
OPENWHISPR_ENGINE_SHA256 = "b62b30d4b605f5202c8daa257e90c76ad65d3738de33534e798aecc27363eca8"
ENGINE_DIR = REPO_ROOT / "tools" / "whisper.cpp-openwhispr-0.0.11"
ENGINE_EXE = ENGINE_DIR / "whisper-cpp-win32-x64-cpu.exe"
# Where OpenWhispr keeps the models it downloads, and its names for them, best first.
OPENWHISPR_MODELS = Path.home() / ".cache" / "openwhispr" / "whisper-models"
_OPENWHISPR_PREFERENCE = ("large-v3-turbo", "turbo", "large-v3", "large", "medium", "small", "base", "tiny")

# Quiet enough to catch real pauses, loud enough to ignore room tone.
SILENCE_NOISE_DB = -35
SILENCE_MIN_SECONDS = 0.5

# Cut points need finer resolution than the editor's view of the recording.
# A gap this short is not a pause a listener notices, but it is often the only
# safe place to put a cut between two words.
MICRO_PAUSE_MIN_SECONDS = 0.08

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)")


class TranscriptionError(Exception):
    pass


def find_whisper_cli() -> str:
    override = os.environ.get("FRAMEFLOW_WHISPER_CLI")
    if override:
        return override
    for name in ("whisper-cli", "whisper-cli.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [Path(r"C:\Program Files\Shotcut\whisper-cli.exe")]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Shotcut" / "whisper-cli.exe")
    candidates.append(ENGINE_EXE)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise TranscriptionError(
        "whisper-cli not found. Run `python -m project.transcribe --install` to fetch OpenWhispr's "
        "build of whisper.cpp, or put whisper-cli on PATH or set FRAMEFLOW_WHISPER_CLI to it."
    )


def find_model(model: Path | str | None = None) -> Path:
    named = model or os.environ.get("FRAMEFLOW_WHISPER_MODEL")
    if named:
        path = Path(named)
    elif DEFAULT_MODEL.exists():
        path = DEFAULT_MODEL
    else:
        # A model the creator's OpenWhispr already downloaded saves downloading another.
        path = next((p for p in (OPENWHISPR_MODELS / f"ggml-{n}.bin" for n in _OPENWHISPR_PREFERENCE)
                     if p.exists()), DEFAULT_MODEL)
    if not path.exists():
        raise TranscriptionError(
            f"Whisper model not found at {path}. Run `python -m project.transcribe --install`, "
            f"download a ggml model from huggingface.co/ggerganov/whisper.cpp, or set "
            f"FRAMEFLOW_WHISPER_MODEL."
        )
    return path


def _download(url: str, dest: Path, sha256: str) -> Path:
    """Fetch a file and keep it only if it is exactly the one expected."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
            out.write(chunk)
    if digest.hexdigest() != sha256:
        partial.unlink()
        raise TranscriptionError(f"{url} did not match its expected checksum; not using it")
    partial.replace(dest)
    return dest


def install() -> list[str]:
    """Fetch what transcription needs and is missing. Returns what was done."""
    done = []
    try:
        done.append(f"engine: using {find_whisper_cli()}")
    except TranscriptionError:
        if sys.platform != "win32":
            raise TranscriptionError("OpenWhispr's build is fetched for Windows only; install "
                                     "whisper.cpp's whisper-cli and put it on PATH") from None
        with tempfile.TemporaryDirectory() as tmp:
            archive = _download(OPENWHISPR_ENGINE_URL, Path(tmp) / "engine.zip", OPENWHISPR_ENGINE_SHA256)
            with zipfile.ZipFile(archive) as z:
                z.extractall(ENGINE_DIR)
        done.append(f"engine: installed OpenWhispr's whisper.cpp in {ENGINE_DIR}")
    try:
        done.append(f"model: using {find_model()}")
    except TranscriptionError:
        print("    downloading the Whisper model (548 MB)...", flush=True)
        done.append(f"model: downloaded {_download(MODEL_URL, DEFAULT_MODEL, MODEL_SHA256)}")
    return done


def extract_audio(video: Path | str, wav: Path | str, duration: float) -> None:
    """16 kHz mono PCM - the input format whisper.cpp expects.

    Cut to the video's duration: some recorders (Windows Camera, observed) write
    an audio track that runs well past the last video frame. Audio beyond the
    picture can't be part of the edit, and transcribing it produces timestamps
    past the end of the timeline.
    """
    result = subprocess.run(
        [_find_tool("ffmpeg"), "-y", "-v", "error", "-i", str(video), "-t", f"{duration:.3f}",
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode != 0:
        raise TranscriptionError(f"audio extraction failed: {result.stderr.strip()}")


def parse_silencedetect(stderr: str, duration: float,
                        min_seconds: float = SILENCE_MIN_SECONDS) -> list[dict]:
    silences = []
    start = None
    for line in stderr.splitlines():
        if (m := _SILENCE_START.search(line)):
            start = max(0.0, float(m.group(1)))
        elif (m := _SILENCE_END.search(line)) and start is not None:
            silences.append({"start": round(start, 3), "end": round(float(m.group(1)), 3)})
            start = None
    # Audio that ends while still silent reports a start with no matching end.
    if start is not None and duration - start >= min_seconds:
        silences.append({"start": round(start, 3), "end": round(duration, 3)})
    return silences


def detect_silences(wav: Path | str, duration: float,
                    min_seconds: float = SILENCE_MIN_SECONDS) -> list[dict]:
    result = subprocess.run(
        [_find_tool("ffmpeg"), "-v", "info", "-i", str(wav),
         "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={min_seconds}",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode != 0:
        raise TranscriptionError(f"silence detection failed: {result.stderr[-2000:]}")
    return parse_silencedetect(result.stderr, duration, min_seconds)


def whisper_json_to_segments(whisper: dict) -> list[dict]:
    segments = []
    for item in whisper.get("transcription", []):
        text = item.get("text", "").strip()
        # Whisper emits bare punctuation ("...", ".") over stretches with no
        # words in them; that is not speech.
        if not any(ch.isalnum() for ch in text):
            continue
        offsets = item["offsets"]
        segments.append({
            "start": round(offsets["from"] / 1000, 3),
            "end": round(offsets["to"] / 1000, 3),
            "text": text,
        })
    return segments


def word_timings(whisper: dict, pauses: list[dict]) -> list[dict]:
    """Words, timed by DTW where whisper.cpp aligned them.

    Measured against pauses on a real recording, a token's DTW time is where it
    ends, while Whisper's own word times stretch a word over the silence before
    it. So a word ends at its last token's DTW time, and starts where the word
    before it ended, or at the end of a measured pause between them.
    """
    items = whisper.get("transcription", [])
    if not any(t.get("t_dtw", -1) >= 0 for item in items for t in item.get("tokens", [])):
        return whisper_json_to_segments(whisper)
    words = []
    for item in items:
        text = item.get("text", "").strip()
        if not any(ch.isalnum() for ch in text):
            continue
        aligned = [t["t_dtw"] for t in item.get("tokens", [])
                   if t.get("t_dtw", -1) >= 0 and not t["text"].startswith("[_")]
        end = aligned[-1] / 100 if aligned else item["offsets"]["to"] / 1000
        start = words[-1]["end"] if words else item["offsets"]["from"] / 1000
        start = max([start] + [p["end"] for p in pauses if start <= p["end"] <= end])
        words.append({"start": round(start, 3), "end": round(max(start, end), 3), "text": text})
    return words


# whisper.cpp's alignment-head presets for DTW, named like the model files.
DTW_PRESETS = {"tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
               "large.v1", "large.v2", "large.v3", "large.v3.turbo"}


def dtw_preset(model: Path) -> str | None:
    """The DTW preset for a ggml model file: ggml-large-v3-turbo-q5_0.bin -> large.v3.turbo."""
    name = re.sub(r"-q\d_\d$", "", Path(model).stem.removeprefix("ggml-")).replace("-", ".")
    return name if name in DTW_PRESETS else None


def run_whisper(wav: Path | str, model: Path, language: str, out_base: Path,
                per_word: bool = False) -> dict:
    extra = ["-ml", "1", "-sow"] if per_word else []
    if per_word and (preset := dtw_preset(model)):
        # DTW times are only in the full JSON, and whisper.cpp quietly skips DTW with flash attention on.
        extra += ["-ojf", "-dtw", preset, "-nfa"]
    result = subprocess.run(
        [find_whisper_cli(), "-m", str(model), "-f", str(wav), "-l", language,
         "--suppress-nst",  # drop non-speech annotations like "*Trips*" or "[Music]"
         *extra, "-oj", "-of", str(out_base), "-np",
         "-t", str(os.cpu_count() or 4)],  # whisper-cli uses 4 threads unless told; all of them was fastest
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4 * 3600,
    )
    json_path = out_base.with_suffix(".json")
    if result.returncode != 0 or not json_path.exists():
        raise TranscriptionError(f"whisper-cli failed: {result.stderr[-2000:]}")
    return json.loads(json_path.read_text(encoding="utf-8"))


def build_timing_map(video: Path | str, model: Path | str | None = None,
                     language: str = "auto") -> dict:
    """Word timings and micro-pauses, for placing cut points precisely.

    Separate from the transcript on purpose. The transcript is what the editor
    reads to decide *what* to cut; this is what the pipeline uses afterwards to
    decide exactly *where* the cut goes. Feeding hundreds of 0.08s gaps to the
    editor would bury the signal it actually needs.
    """
    video = Path(video)
    info = analyze(video)
    if not info.has_audio:
        raise TranscriptionError(f"{video.name} has no audio track")
    model_path = find_model(model)

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_audio(video, wav, info.duration_seconds)
        whisper = run_whisper(wav, model_path, language, Path(tmp) / "words", per_word=True)
        pauses = detect_silences(wav, info.duration_seconds, MICRO_PAUSE_MIN_SECONDS)

    return {
        "source": video.resolve().as_posix(),
        "duration_seconds": round(info.duration_seconds, 3),
        "words": word_timings(whisper, pauses),
        "pauses": pauses,
    }

def transcribe(video: Path | str, model: Path | str | None = None, language: str = "auto") -> dict:
    video = Path(video)
    info = analyze(video)
    if not info.has_audio:
        raise TranscriptionError(f"{video.name} has no audio track, so there is no speech to transcribe")
    duration = info.duration_seconds
    model_path = find_model(model)

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        extract_audio(video, wav, duration)
        whisper = run_whisper(wav, model_path, language, Path(tmp) / "whisper")
        silences = detect_silences(wav, duration)

    transcript = {
        "source": video.resolve().as_posix(),
        "duration_seconds": round(duration, 3),
        "language": whisper.get("result", {}).get("language", language),
        "segments": whisper_json_to_segments(whisper),
        "silences": silences,
    }
    validate(transcript, "transcript")
    return transcript


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a video and detect silences.")
    parser.add_argument("video", nargs="?")
    parser.add_argument("--install", action="store_true",
                        help="fetch the transcription engine, and a model if there is none")
    parser.add_argument("-o", "--output", help="write transcript JSON here instead of stdout")
    parser.add_argument("--language", default="auto", help="spoken language code, or 'auto'")
    parser.add_argument("--model", help="ggml Whisper model path")
    args = parser.parse_args()

    if args.install:
        try:
            for line in install():
                print(line)
        except TranscriptionError as e:
            sys.exit(str(e))
        return
    if not args.video:
        parser.error("give a video to transcribe, or --install")
    transcript = transcribe(args.video, args.model, args.language)
    text = json.dumps(transcript, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
