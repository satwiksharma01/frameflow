#!/usr/bin/env python3
"""Speech-to-text plus silence detection for a source video.

Transcription uses whisper.cpp's CLI, which Shotcut already bundles - no
PyTorch install. Whisper's segment timestamps are not trustworthy as cut
points on their own: they absorb the pauses around speech, so a segment can
start seconds before the words do. Silence is therefore measured separately
from the audio with ffmpeg's silencedetect, and both signals go to the editor.

Usage:
    python -m project.transcribe <video> [-o transcript.json] [--language auto]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from project.media import _find_tool, analyze
from project.validate import validate

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = REPO_ROOT / "models" / "ggml-large-v3-turbo-q5_0.bin"

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
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise TranscriptionError(
        "whisper-cli not found. Install Shotcut (it bundles whisper-cli) or set FRAMEFLOW_WHISPER_CLI."
    )


def find_model(model: Path | str | None = None) -> Path:
    path = Path(model or os.environ.get("FRAMEFLOW_WHISPER_MODEL") or DEFAULT_MODEL)
    if not path.exists():
        raise TranscriptionError(
            f"Whisper model not found at {path}. Download a ggml model from "
            f"huggingface.co/ggerganov/whisper.cpp or set FRAMEFLOW_WHISPER_MODEL."
        )
    return path


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


def run_whisper(wav: Path | str, model: Path, language: str, out_base: Path,
                per_word: bool = False) -> dict:
    extra = ["-ml", "1", "-sow"] if per_word else []
    result = subprocess.run(
        [find_whisper_cli(), "-m", str(model), "-f", str(wav), "-l", language,
         "--suppress-nst",  # drop non-speech annotations like "*Trips*" or "[Music]"
         *extra, "-oj", "-of", str(out_base), "-np"],
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
        "words": whisper_json_to_segments(whisper),
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
    parser.add_argument("video")
    parser.add_argument("-o", "--output", help="write transcript JSON here instead of stdout")
    parser.add_argument("--language", default="auto", help="spoken language code, or 'auto'")
    parser.add_argument("--model", help="ggml Whisper model path")
    args = parser.parse_args()

    transcript = transcribe(args.video, args.model, args.language)
    text = json.dumps(transcript, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)


if __name__ == "__main__":
    main()
