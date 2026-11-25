#!/usr/bin/env python3
"""Where someone is speaking in a file's audio: Silero VAD (MIT) through ONNX Runtime.

Loud is not speech. Music in a phone clip made whisper write lyrics nobody said, and the silence
measure counted the music as speech. The model is a 2.3 MB download kept in models/, as whisper's is.
"""
import subprocess
from pathlib import Path

import numpy as np

from project.media import _find_tool, probe
from project.transcribe import REPO_ROOT, _download

MODEL_PATH = REPO_ROOT / "models" / "silero_vad.onnx"
_COMMIT = "bfdc0193023f121ea5b3cc7b176dbed570a68a59"
MODEL_URL = f"https://github.com/snakers4/silero-vad/raw/{_COMMIT}/src/silero_vad/data/silero_vad.onnx"
MODEL_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
RATE = 16000
CHUNK = 512         # samples the model takes at 16 kHz: 32 ms
CONTEXT = 64        # samples of the chunk before, which the model is given first


class VadError(Exception):
    pass


def installed() -> bool:
    return MODEL_PATH.is_file()


def install() -> str:
    """Fetch the model if it is missing. What was done."""
    if installed():
        return f"Silero VAD: using {MODEL_PATH}"
    return f"Silero VAD: downloaded {_download(MODEL_URL, MODEL_PATH, MODEL_SHA256)}"


def regions(probs: list[float], hop: float = CHUNK / RATE, threshold: float = 0.5, min_speech: float = 0.25,
            min_silence: float = 0.1, pad: float = 0.03) -> list[dict]:
    """Speech regions in seconds from the model's probability for each chunk."""
    runs, start = [], None
    for i, p in enumerate([*probs, 0.0]):           # the trailing 0 closes a run at the end
        if p >= threshold and start is None:
            start = i
        elif p < threshold and start is not None:
            runs.append([start * hop, i * hop])
            start = None
    merged: list[list[float]] = []
    for s, e in runs:
        if merged and s - merged[-1][1] < min_silence:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [{"start": round(max(0.0, s - pad), 3), "end": round(e + pad, 3)}
            for s, e in merged if e - s >= min_speech]


def _pcm(path: Path | str) -> np.ndarray:
    """The file's audio at 16 kHz mono, or nothing when it has none."""
    if not any(s.get("codec_type") == "audio" for s in probe(path).get("streams", [])):
        return np.zeros(0, np.float32)
    result = subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                             "-ar", str(RATE), "-f", "f32le", "-"], capture_output=True)
    if result.returncode != 0:
        raise VadError(f"ffmpeg could not read the audio of {path}: {result.stderr.decode(errors='replace')[-500:]}")
    return np.frombuffer(result.stdout, np.float32)


def speech(path: Path | str) -> list[dict]:
    """Where someone speaks in the file, as {start, end} regions in seconds."""
    if not installed():
        raise VadError("the Silero VAD model is not installed: run python -m project.eyes install")
    audio = _pcm(path)
    if audio.size == 0:
        return []
    import onnxruntime
    session = onnxruntime.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    state = np.zeros((2, 1, 128), np.float32)
    context = np.zeros((1, CONTEXT), np.float32)
    rate = np.array(RATE, dtype=np.int64)
    probs = []
    for i in range(0, audio.size, CHUNK):
        chunk = audio[i:i + CHUNK]
        if chunk.size < CHUNK:
            chunk = np.pad(chunk, (0, CHUNK - chunk.size))
        x = np.concatenate([context, chunk[None, :]], axis=1)
        out, state = session.run(None, {"input": x, "state": state, "sr": rate})
        context = x[:, -CONTEXT:]
        probs.append(float(out[0][0]))
    return regions(probs)
