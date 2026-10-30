#!/usr/bin/env python3
"""A voice reading the script, made on this machine for free.

Uses the speech voices built into Windows (System.Speech), so it needs no
download, no account and no network. It also says when each word starts, which
captions use, in a .json beside the .wav.

ponytail: Windows' voices sound robotic. Swap in Piper or a paid voice (as
another function with the same signature) when the videos need a better one.
"""
import json
import os
import subprocess
import wave
from pathlib import Path

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
    result = _powershell(_LIST)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


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


def speak(text: str, out: Path, voice: str | None = None) -> Path:
    """Read `text` aloud into a .wav file, with its word timings beside it in a .json."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    result = _powershell(_SPEAK, FRAMEFLOW_TTS_TEXT=text, FRAMEFLOW_TTS_OUT=str(out.resolve()),
                         FRAMEFLOW_TTS_VOICE=voice or "")
    if result.returncode != 0 or not out.exists():
        raise VoiceError(f"the voice could not read {text[:40]!r}: {result.stderr.strip()[-500:]}")
    with wave.open(str(out)) as w:
        rate, duration = w.getframerate(), w.getnframes() / w.getframerate()
    out.with_suffix(".json").write_text(json.dumps(words(text, result.stdout, rate, duration)), encoding="utf-8")
    return out
