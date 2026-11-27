"""Speech regions from Silero VAD, and a speech check that counts speech, not sound."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from project import editor_agent, first_cut, vad
from project.media import _find_tool


class TestRegions(unittest.TestCase):
    def test_runs_over_the_threshold_become_padded_regions(self):
        probs = [0.0] * 10 + [0.9] * 20 + [0.0] * 10          # 0.32 s to 0.96 s
        self.assertEqual(vad.regions(probs), [{"start": 0.29, "end": 0.99}])

    def test_short_gaps_merge_and_short_bursts_drop(self):
        gap = [0.9] * 10 + [0.0] * 2 + [0.9] * 10             # a 0.064 s gap merges
        self.assertEqual(len(vad.regions(gap)), 1)
        self.assertEqual(vad.regions([0.0] * 5 + [0.9] * 3 + [0.0] * 5), [])   # 0.096 s is too short


class TestSpeechCheck(unittest.TestCase):
    TRANSCRIPT = {"source": "a.mp4", "duration_seconds": 13.667,
                  "segments": [{"start": 0, "end": 9.5, "text": "y que hace bala"}],
                  "silences": [{"start": 0.0, "end": 1.0}]}

    def test_speech_regions_replace_the_audible_measure(self):
        with self.assertRaises(editor_agent.NoSpeechError) as cm:
            editor_agent.ensure_speech({**self.TRANSCRIPT, "speech": [{"start": 2.0, "end": 2.4}]})
        self.assertIn("add it as a picture or clip", str(cm.exception))
        editor_agent.ensure_speech(self.TRANSCRIPT)             # no regions: today's measure, 12.7 s audible

    def test_segments_over_no_speech_are_dropped(self):
        transcript = {"source": "a.mp4", "duration_seconds": 4.0, "speech": [{"start": 1.0, "end": 2.0}],
                      "segments": [{"start": 0.0, "end": 0.8, "text": "Keep loving it"},
                                   {"start": 1.5, "end": 3.0, "text": "hello there"}]}
        self.assertEqual(first_cut.drop_outside_speech(transcript), 1)
        self.assertEqual([s["text"] for s in transcript["segments"]], ["hello there"])

    def test_the_real_model_hears_no_speech_in_a_tone(self):
        if not vad.installed():
            self.skipTest("the Silero model is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            tone = Path(tmp) / "tone.wav"
            subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=330:duration=3", str(tone)], check=True)
            self.assertEqual(vad.speech(tone), [])


if __name__ == "__main__":
    unittest.main()
