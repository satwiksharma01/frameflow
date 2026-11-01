#!/usr/bin/env python3
"""A voice reading the script, made on this machine for free.

Piper (OHF-Voice/piper1-gpl, GPLv3) reads with a natural voice, offline. Its
default voice is trained on public-domain recordings (LJSpeech), so videos made
with it can be posted; many other Piper voices are non-commercial. The speech
voices built into Windows (System.Speech) need no download at all, but sound
robotic. Both say when each word is spoken, which captions use, in a .json
beside the .wav.

    python -m project.voiceover --install      # fetch Piper's default voice (114 MB)
"""
import argparse
import functools
import itertools
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

from project import transcribe

PIPER_DIR = transcribe.REPO_ROOT / "models" / "piper"
DEFAULT_PIPER_VOICE = "en_US-ljspeech-high"
_PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/high/en_US-ljspeech-high"
_PIPER_FILES = {".onnx": "5d4f08ba6a2a48c44592eed3ce56bf85e9de3dd4e20df90541ae68a8310c029a",
                ".onnx.json": "7e1f4634af596d83cca997fb7a931ba80b70f8a316a2655ee69c55365e0ace14"}

# The text and path go in through the environment, never into the script itself,
# so nothing in a narration line can run as PowerShell.
_SPEAK = """
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:FRAMEFLOW_TTS_VOICE) { $s.SelectVoice($env:FRAMEFLOW_TTS_VOICE) }
$s.SetOutputToWaveFile($env:FRAMEFLOW_TTS_OUT)
$words = New-Object System.Collections.ArrayList
$s.add_SpeakProgress({ param($o, $e)
  [void]$words.Add("$($e.AudioPosition.TotalMilliseconds) $($e.CharacterPosition) $($e.CharacterCount)") })
$s.Speak($env:FRAMEFLOW_TTS_TEXT)
$s.Dispose()
$words
"""

_LIST = """
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name }
$s.Dispose()
"""


class VoiceError(Exception):
    pass


def _powershell(script: str, **env: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              env={**os.environ, **env}, capture_output=True, text=True,
                              errors="replace", timeout=300)
    except FileNotFoundError as e:
        raise VoiceError("the built-in voice needs Windows PowerShell") from e


def voices() -> list[str]:
    """Installed voices, Piper's first (default voice first), so a storyboard without one gets Piper."""
    piper = sorted((p.stem for p in PIPER_DIR.glob("*.onnx")), key=lambda name: name != DEFAULT_PIPER_VOICE)
    result = _powershell(_LIST)
    return piper + [line.strip() for line in result.stdout.splitlines() if line.strip()]


def words(text: str, events: str, rate: int, duration: float) -> list[dict]:
    """When each word of `text` starts and ends, from the voice's progress events.

    System.Speech reports positions as if the audio were 16 kHz, whatever the
    file's rate: measured against the pauses in files written at 16, 22.05 and
    44.1 kHz. A number or price fires several events from one place in the
    text ("$129" is said in three words), so the first one counts.
    """
    starts: dict[int, tuple[float, int]] = {}
    for line in events.splitlines():
        if line.strip():
            ms, position, count = line.split()
            starts.setdefault(int(position), (float(ms) / 1000 * 16000 / rate, int(count)))
    found = []
    for position, (start, count) in sorted(starts.items()):
        end = position + count
        while end < len(text) and text[end] in ".,!?;:":    # the word keeps its punctuation
            end += 1
        found.append({"start": round(start, 3), "text": text[position:end]})
    for word, following in zip(found, found[1:] + [None]):
        word["end"] = following["start"] if following else round(duration, 3)
    return found


def _spoken_runs(phonemes: list[str]) -> list[list[int]]:
    """Each word's phonemes as indices: the runs between spaces, without the sentence marks ^ and $."""
    runs: list[list[int]] = []
    for i, p in enumerate(phonemes):
        if p in (" ", "^", "$"):
            continue
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return runs


def piper_words(text: str, counts: list[int], aligned: list[tuple[str, int]], rate: int) -> list[dict]:
    """When each word of `text` is said, from Piper's phoneme durations.

    `counts` is how many runs of phonemes each word of `text.split()` becomes on
    its own ("$129" is said in three words). When the voice runs words together
    and the totals differ, times are spread in proportion: approximate, in order.
    """
    edges = list(itertools.accumulate((n for _, n in aligned), initial=0))
    spans = [(edges[r[0]] / rate, edges[r[-1] + 1] / rate) for r in _spoken_runs([p for p, _ in aligned])]
    if not spans or not sum(counts):
        return []
    scale = len(spans) / sum(counts)

    def at(x: float, ending: bool) -> float:
        k = max(0, min(math.ceil(x) - 1 if ending else int(x), len(spans) - 1))   # the run x falls in
        return spans[k][0] + (x - k) * (spans[k][1] - spans[k][0])

    found, before = [], 0
    for word, count in zip(text.split(), counts):
        if count:
            found.append({"start": round(at(before * scale, False), 3),
                          "end": round(at((before + count) * scale, True), 3), "text": word})
        before += count
    return found


@functools.cache
def _piper(name: str):
    try:
        from piper import PiperVoice
    except ImportError as e:
        raise VoiceError("Piper is not installed: pip install -r requirements.txt") from e
    return PiperVoice.load(PIPER_DIR / f"{name}.onnx", include_alignments=True)


def _speak_piper(text: str, out: Path, name: str) -> None:
    voice = _piper(name)
    with wave.open(str(out), "wb") as w:
        aligned = voice.synthesize_wav(text, w, include_alignments=True)
    if not aligned:
        raise VoiceError(f"the Piper voice {name} gave no word timings, which captions need")
    counts = [len(_spoken_runs(sum(voice.phonemize(word), []))) for word in text.split()]
    found = piper_words(text, counts, [(a.phoneme, a.num_samples) for a in aligned], voice.config.sample_rate)
    out.with_suffix(".json").write_text(json.dumps(found), encoding="utf-8")


def speak(text: str, out: Path, voice: str | None = None) -> Path:
    """Read `text` aloud into a .wav file, with its word timings beside it in a .json."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    if voice and (PIPER_DIR / f"{voice}.onnx").exists():
        _speak_piper(text, out, voice)
        return out
    result = _powershell(_SPEAK, FRAMEFLOW_TTS_TEXT=text, FRAMEFLOW_TTS_OUT=str(out.resolve()),
                         FRAMEFLOW_TTS_VOICE=voice or "")
    if result.returncode != 0 or not out.exists():
        raise VoiceError(f"the voice could not read {text[:40]!r}: {result.stderr.strip()[-500:]}")
    with wave.open(str(out)) as w:
        rate, duration = w.getframerate(), w.getnframes() / w.getframerate()
    out.with_suffix(".json").write_text(json.dumps(words(text, result.stdout, rate, duration)), encoding="utf-8")
    return out


def install() -> str:
    """Fetch Piper's default voice if it is missing."""
    model = PIPER_DIR / f"{DEFAULT_PIPER_VOICE}.onnx"
    if model.exists():
        return f"voice: using {model}"
    print("    downloading the Piper voice (114 MB)...", flush=True)
    for suffix, sha256 in _PIPER_FILES.items():
        transcribe._download(_PIPER_URL + suffix, PIPER_DIR / f"{DEFAULT_PIPER_VOICE}{suffix}", sha256)
    return f"voice: downloaded {model}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Voices for narration.")
    parser.add_argument("--install", action="store_true", help="fetch Piper's default voice")
    args = parser.parse_args()
    if not args.install:
        print("\n".join(voices()))
        return
    try:
        print(install())
    except transcribe.TranscriptionError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
