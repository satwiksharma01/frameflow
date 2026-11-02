#!/usr/bin/env python3
"""When the beats fall in a piece of music, so cuts can land on them.

Beat tracking by dynamic programming, after Ellis, "Beat Tracking by Dynamic
Programming" (Journal of New Music Research, 2007): how strongly new notes
start, frame by frame; the tempo that best explains that; then the run of beats
that sits on strong onsets while keeping close to the tempo.
"""
import subprocess
from pathlib import Path

import numpy as np

from project.media import MediaError, _find_tool

RATE = 11025            # Hz: enough for kicks, snares and the body of the hats
WINDOW, HOP = 512, 128  # 46 ms windows, one every 11.6 ms
BANDS = 40
TIGHTNESS = 100.0       # how strongly the beats keep to the tempo, against following the onsets


def beats(path: Path | str) -> list[float]:
    """When each beat falls, in seconds from the start of the file."""
    onsets = _onset_strength(_decode(path))
    return [round(frame * HOP / RATE, 4) for frame in _track(onsets, _period(onsets))]


def tempo(times: list[float]) -> float:
    """Beats per minute, from when the beats fall."""
    return 60 * (len(times) - 1) / (times[-1] - times[0])


def _decode(path: Path | str, rate: int = RATE) -> np.ndarray:
    result = subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                             "-ar", str(rate), "-f", "f32le", "-"], capture_output=True, timeout=600)
    if result.returncode != 0:
        raise MediaError(f"could not read {Path(path).name}: {result.stderr.decode(errors='replace').strip()[-500:]}")
    return np.frombuffer(result.stdout, dtype=np.float32)


def _mel_bank() -> np.ndarray:
    """Triangular filters over the FFT bins, spaced evenly in pitch as it is heard."""
    mel = 2595 * np.log10(1 + np.array([30.0, RATE / 2]) / 700)
    edges = 700 * (10 ** (np.linspace(*mel, BANDS + 2) / 2595) - 1)
    bins = np.fft.rfftfreq(WINDOW, 1 / RATE)
    low, mid, high = edges[:-2, None], edges[1:-1, None], edges[2:, None]
    return np.maximum(0, np.minimum((bins - low) / (mid - low), (high - bins) / (high - mid))).astype(np.float32)


def _onset_strength(pcm: np.ndarray) -> np.ndarray:
    """How much louder each frame is than the one before, summed over the bands: high where notes start."""
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(pcm, WINDOW // 2), WINDOW)[::HOP]  # frame i centred on i * HOP
    window, bank = np.hanning(WINDOW).astype(np.float32), _mel_bank()
    power = np.concatenate([np.abs(np.fft.rfft(frames[i:i + 4096] * window)) ** 2 @ bank.T
                            for i in range(0, len(frames), 4096)])
    db = 10 * np.log10(np.maximum(power, 1e-10))
    db = np.maximum(db, db.max() - 80)          # what is 80 dB under the loudest is silence
    flux = np.concatenate([[0.0], np.maximum(0, np.diff(db, axis=0)).mean(axis=1)])
    flux -= np.convolve(flux, np.ones(87) / 87, mode="same")   # take away the slow swell over a second
    flux = np.convolve(flux, np.exp(-0.5 * (np.arange(-3, 4) / 1.7) ** 2), mode="same")   # smooth over 20 ms
    return flux / (flux.std() or 1.0)


def _period(onsets: np.ndarray) -> float:
    """The beat's length in frames: the lag at which the onsets best repeat, preferring one near 120 BPM."""
    spectrum = np.fft.rfft(onsets, 2 * len(onsets))
    repeats = np.fft.irfft(spectrum * np.conj(spectrum))
    lags = np.arange(round(0.25 * RATE / HOP), min(len(onsets), round(2.0 * RATE / HOP)))   # 240 to 30 BPM
    near_120 = np.exp(-0.5 * np.log2(lags * HOP / RATE / 0.5) ** 2)
    return float(lags[np.argmax(repeats[lags] * near_120)])


def _track(onsets: np.ndarray, period: float) -> list[int]:
    """The frames the beats fall on: each on a strong onset, about a period after the one before."""
    gaps = np.arange(round(period / 2), round(2 * period) + 1)
    penalty = -TIGHTNESS * np.log(gaps / period) ** 2
    score, previous = onsets.astype(float), np.full(len(onsets), -1)
    for t in range(gaps[0], len(onsets)):
        before = t - gaps[gaps <= t]
        options = score[before] + penalty[:len(before)]
        best = int(np.argmax(options))
        if options[best] > 0:       # a beat with only worse ones before it starts a new run
            score[t] += options[best]
            previous[t] = before[best]
    t = len(onsets) - round(period) + int(np.argmax(score[-round(period):]))
    frames = []
    while t >= 0:
        frames.append(t)
        t = previous[t]
    frames.reverse()
    # Drop beats at either end where nothing much is played: an intro or an ending that fades.
    strength = onsets[frames]
    strong = np.flatnonzero(strength > 0.5 * np.sqrt(np.mean(strength ** 2)))
    return frames[strong[0]:strong[-1] + 1] if len(strong) else []

