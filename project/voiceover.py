#!/usr/bin/env python3
"""A voice reading the script, made on this machine for free.

Uses the speech voices built into Windows (System.Speech), so it needs no
download, no account and no network.

ponytail: Windows' voices sound robotic. Swap in Piper or a paid voice (as
another function with the same signature) when the videos need a better one.
"""
import os
import subprocess
from pathlib import Path

# The text and path go in through the environment, never into the script itself,
# so nothing in a narration line can run as PowerShell.
_SPEAK = """
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($env:FRAMEFLOW_TTS_VOICE) { $s.SelectVoice($env:FRAMEFLOW_TTS_VOICE) }
$s.SetOutputToWaveFile($env:FRAMEFLOW_TTS_OUT)
$s.Speak($env:FRAMEFLOW_TTS_TEXT)
$s.Dispose()
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


def speak(text: str, out: Path, voice: str | None = None) -> Path:
    """Read `text` aloud into a .wav file."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    result = _powershell(_SPEAK, FRAMEFLOW_TTS_TEXT=text, FRAMEFLOW_TTS_OUT=str(out.resolve()),
                         FRAMEFLOW_TTS_VOICE=voice or "")
    if result.returncode != 0 or not out.exists():
        raise VoiceError(f"the voice could not read {text[:40]!r}: {result.stderr.strip()[-500:]}")
    return out
