"""Finding the beat in a piece of music."""
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from project import beats

RATE = 22050


def _song(path: Path, bpm: float, first: float, seconds: float) -> list[float]:
    """A drum loop over a held chord: kick on 1 and 3, snare on 2 and 4, hats on every eighth.
    Returns when its beats fall."""
    t = np.arange(int(seconds * RATE)) / RATE
    rng = np.random.default_rng(1)
    song = 0.05 * (np.sin(2 * np.pi * 110 * t) + np.sin(2 * np.pi * 165 * t) + np.sin(2 * np.pi * 220 * t))
    period = 60 / bpm
    times = list(np.arange(first, seconds - 0.2, period))
    for n, beat in enumerate(times):
        for at, kind in ((beat, "kick" if n % 2 == 0 else "snare"), (beat, "hat"), (beat + period / 2, "hat")):
            i = int(at * RATE)
            d = np.arange(min(int(0.25 * RATE), len(t) - i)) / RATE
            if kind == "kick":
                hit = 0.9 * np.sin(2 * np.pi * (50 * d + 3 * (1 - np.exp(-d / 0.03)))) * np.exp(-d / 0.12)
            elif kind == "snare":
                hit = 0.5 * rng.standard_normal(len(d)) * np.exp(-d / 0.06)
            else:
                hit = 0.15 * np.diff(rng.standard_normal(len(d) + 1)) * np.exp(-d / 0.02)
            song[i:i + len(d)] += hit
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(song, -1, 1) * 32767).astype("<i2").tobytes())
    return times


class TestFindingTheBeat(unittest.TestCase):
    def test_each_beat_is_found_where_the_drums_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            truth = _song(Path(tmp) / "song.wav", bpm=124, first=0.31, seconds=20)
            found = beats.beats(Path(tmp) / "song.wav")
        self.assertAlmostEqual(beats.tempo(found), 124, delta=1)
        # Every beat is found, none between them, each within a frame of video at 30 fps.
        inside = [b for b in truth if 1 < b < 19]
        nearest = [min(found, key=lambda f: abs(f - b)) for b in inside]
        self.assertLess(max(abs(f - b) for f, b in zip(nearest, inside)), 1 / 30)
        self.assertEqual(len([f for f in found if 1 < f < 19]), len(inside))

    def test_a_slower_song_is_not_taken_at_double_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _song(Path(tmp) / "song.wav", bpm=92, first=0.5, seconds=20)
            found = beats.beats(Path(tmp) / "song.wav")
        self.assertAlmostEqual(beats.tempo(found), 92, delta=1)


if __name__ == "__main__":
    unittest.main()
