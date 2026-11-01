"""Captions that pop in word by word: lines, placing them through a cut, and the track."""
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from project import captions, hyperframes, voiceover
from project.reconcile import source_key
from project.validate import validate


def words(*spoken):
    """(start, end, text) -> Whisper-style words."""
    return [{"start": s, "end": e, "text": t} for s, e, t in spoken]


def texts(found):
    return [" ".join(t for _, t in line["words"]) for line in found]


class TestLines(unittest.TestCase):
    def test_lines_break_at_length_pauses_and_sentence_ends(self):
        said = words((0.0, 0.3, "hey"), (0.3, 0.6, "everyone"), (0.6, 0.9, "welcome"),
                     (1.5, 1.8, "back."), (1.8, 2.1, "So"), (2.1, 2.4, "today"))
        found = captions.lines([captions.run(said, 0.0, 3.0, 0.0)], 30, 16)
        # "hey everyone welcome" is 20 characters; a 0.6s pause before "back."; a sentence ends after it.
        self.assertEqual(texts(found), ["hey everyone", "welcome", "back.", "So today"])

    def test_a_line_stays_up_until_the_next_unless_there_is_a_real_pause(self):
        said = words((0.0, 0.5, "one"), (0.9, 1.2, "two"), (3.0, 3.4, "three"))
        found = captions.lines([captions.run(said, 0.0, 5.0, 0.0)], 30, 3)
        self.assertEqual(found[0]["end"], found[1]["start"])                 # 0.4s gap: held
        self.assertEqual(found[1]["end"], round((1.2 + captions.TAIL_SECONDS) * 30))   # 1.8s gap: not
        self.assertEqual(found[2]["end"], round((3.4 + captions.TAIL_SECONDS) * 30))

    def test_a_word_too_short_to_read_alone_takes_the_word_before_it(self):
        said = words((0.0, 0.3, "look"), (0.3, 0.5, "at"), (0.5, 0.65, "the"), (0.65, 0.8, "current"),
                     (0.8, 1.3, "timeline,"), (1.3, 1.6, "find"))
        found = captions.lines([captions.run(said, 0.0, 2.0, 0.0)], 30, 14)
        # "look at the current" is 19 characters; alone, "current" would be up for 0.15s.
        self.assertEqual(texts(found), ["look at", "the current", "timeline, find"])

    def test_it_takes_it_across_a_breath_but_not_a_real_pause(self):
        said = words((0.0, 0.5, "creativity"), (0.5, 0.9, "um"), (1.3, 1.4, "actually"), (1.4, 1.9, "making"))
        self.assertEqual(texts(captions.lines([captions.run(said, 0.0, 2.0, 0.0)], 30, 14)),
                         ["creativity", "um actually", "making"])          # a 0.4s breath before "actually"
        said = words((0.0, 0.5, "creativity"), (0.5, 0.9, "um"), (2.0, 2.1, "actually"), (2.1, 2.6, "making"))
        self.assertEqual(texts(captions.lines([captions.run(said, 0.0, 3.0, 0.0)], 30, 14)),
                         ["creativity um", "actually", "making"])          # 1.1s: the line before is down by then

    def test_a_word_stretched_over_noise_does_not_hold_the_line(self):
        found = captions.lines([captions.run(words((1.0, 10.6, "recording.")), 0.0, 12.0, 0.0)], 30, 14)
        self.assertEqual(found[0]["end"], round((1.0 + captions.LONGEST_WORD + captions.TAIL_SECONDS) * 30))


class TestThroughTheCut(unittest.TestCase):
    IR = {"schema_version": "0.2.0", "project": {"name": "t", "fps": 30, "width": 1080, "height": 1920,
                                                 "source_frame_rate_mode": "cfr"}, "tracks": [
        {"id": "V1", "type": "video", "clips": [
            {"id": "c1", "source": "C:/x/talk.mp4", "source_in": 0.0, "source_out": 2.0,
             "timeline_start": 0.0, "timeline_duration": 2.0},
            {"id": "c2", "source": "C:/x/talk.mp4", "source_in": 5.0, "source_out": 7.0,
             "timeline_start": 2.0, "timeline_duration": 2.0}]}]}
    SAID = words((0.5, 0.9, "kept"), (1.0, 1.9, "first"), (3.0, 3.5, "cut"), (5.2, 5.6, "second"))

    def runs(self):
        return captions.runs_from_cut(self.IR, {source_key("C:/x/talk.mp4"): self.SAID})

    def test_words_move_with_their_clip_and_removed_words_go(self):
        runs = self.runs()
        self.assertEqual([[(w["start"], w["text"]) for w in r["words"]] for r in runs],
                         [[(0.5, "kept"), (1.0, "first")], [(2.2, "second")]])

    def test_no_line_crosses_a_cut(self):
        found = captions.lines(self.runs(), 30, 14)
        self.assertEqual(texts(found), ["kept first", "second"])
        self.assertLessEqual(found[0]["end"], 60)                      # the first clip ends at frame 60

    def test_the_track_plays_spans_of_one_render(self):
        rendered = []

        def fake_render(composition, out, fps):
            rendered.append((composition / "index.html").read_text(encoding="utf-8"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"mov")
            return out

        ir = {**self.IR, "tracks": [dict(self.IR["tracks"][0])]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(hyperframes, "render", fake_render),                 mock.patch.object(hyperframes, "BRAND_FILE", Path(tmp) / "no-kit.json"):
            self.assertEqual(captions.add(ir, self.runs(), Path(tmp)), 2)
            self.assertEqual(captions.add(ir, [], Path(tmp)), 0)
        validate(ir, "ir")
        self.assertEqual(len(rendered), 1)
        self.assertIn('"KEPT"', rendered[0])
        first, second = ir["tracks"][1]["clips"]
        self.assertEqual(ir["tracks"][1]["type"], "captions")
        self.assertEqual(first["source"], second["source"])
        self.assertEqual(second["source_in"], first["source_out"])     # back to back in the render
        self.assertEqual((first["timeline_start"], second["timeline_start"]), (0.5, 2.2))
        self.assertAlmostEqual(second["source_out"] - second["source_in"], second["timeline_duration"])

    def test_captions_take_the_brand_kit(self):
        line = {"start": 0, "end": 30, "words": [(0, "Hello")]}
        kit = dict(hyperframes.BRAND, font="Georgia", text="#222222", accent="#FF3366", uppercase_captions=False)
        html, _ = captions.page([line], 1080, 1920, 30, kit)
        self.assertIn('"Hello"', html)
        self.assertIn('HIGHLIGHT = "#FF3366", TEXT = "#222222"', html)
        self.assertIn('font-family:"Georgia",', html)
        self.assertIn("px #FFFFFF;", html)          # dark text gets a light outline, to read over dark footage
        self.assertIn("px #000000;", captions.page([line], 1080, 1920, 30)[0])

    def test_text_cannot_end_the_script(self):
        line = {"start": 0, "end": 30, "words": [(0, "</script><b>")]}
        html, _ = captions.page([line], 1080, 1920, 30)
        self.assertNotIn("</SCRIPT>", html)


def _clip(source, source_in, start, duration):
    return {"id": "c", "source": source, "source_in": source_in, "source_out": source_in + duration,
            "timeline_start": start, "timeline_duration": duration}


class TestFollowingAnEdit(unittest.TestCase):
    TALK = "C:/x/talk.mp4"
    PROJECT = {"fps": 30, "width": 1920, "height": 1080}

    def ir(self, main, lines):
        return {"project": self.PROJECT, "tracks": [
            {"id": "V1", "type": "video", "clips": [_clip(self.TALK, *c) for c in main]},
            {"id": "Captions", "type": "captions",
             "clips": [_clip("C:/p/graphics/caps.mov", *c) for c in lines]}]}

    def test_lines_go_with_their_words_move_up_and_stop_at_a_cut(self):
        lines = [(0.0, 0.5, 1.0), (1.0, 2.0, 1.5), (2.5, 3.2, 0.5), (3.5, 6.0, 1.0)]
        before = self.ir([(0.0, 0.0, 5.0), (10.0, 5.0, 5.0)], lines)
        # 3-4s of the recording removed: 0-3 plays at 0, 4-5 at 3, 10-15 at 4.
        after = self.ir([(0.0, 0.0, 3.0), (4.0, 3.0, 1.0), (10.0, 4.0, 5.0)], lines)
        counts = captions.follow_cut(before, after, {}, Path("unused"))
        self.assertEqual(counts, {"moved": 1, "removed": 1, "added": 0})
        placed = [(c["timeline_start"], c["timeline_duration"], c["source_in"], c["source_out"])
                  for c in after["tracks"][1]["clips"]]
        self.assertEqual(placed, [(0.5, 1.0, 0.0, 1.0),
                                  (2.0, 1.0, 1.0, 2.0),      # ran into the cut at 3s: trimmed there
                                  (5.0, 1.0, 3.5, 4.5)])     # 11s of the recording now plays at 5s

    def test_words_left_over_from_a_line_that_went_get_a_new_one(self):
        # "gone kept" was one line from 1.8s; removing 1.5-2.5s takes "gone" but leaves "kept".
        lines = [(0.0, 1.0, 0.8), (0.8, 1.8, 1.2)]
        before = self.ir([(0.0, 0.0, 5.0)], lines)
        after = self.ir([(0.0, 0.0, 1.5), (2.5, 1.5, 2.5)], lines)
        said = words((1.1, 1.4, "one"), (1.9, 2.3, "gone"), (2.7, 2.9, "kept"))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(hyperframes, "render", lambda c, out, fps: out):
            counts = captions.follow_cut(before, after, {source_key(self.TALK): said}, Path(tmp))
        self.assertEqual(counts, {"moved": 0, "removed": 1, "added": 1})
        self.assertEqual([(c["timeline_start"], c.get("text")) for c in after["tracks"][1]["clips"]],
                         [(1.0, None), (1.7, "kept")])

    def test_speech_put_back_gets_new_lines(self):
        before = self.ir([(0.0, 0.0, 2.0), (4.0, 2.0, 2.0)], [(0.0, 2.2, 1.0)])
        after = self.ir([(0.0, 0.0, 6.0)], [(0.0, 2.2, 1.0)])
        said = words((2.2, 2.6, "put"), (2.6, 3.0, "back"), (4.2, 4.8, "kept"))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(hyperframes, "render", lambda c, out, fps: out):
            counts = captions.follow_cut(before, after, {source_key(self.TALK): said}, Path(tmp))
        self.assertEqual(counts, {"moved": 1, "removed": 0, "added": 1})
        self.assertEqual([(c["timeline_start"], c.get("text")) for c in after["tracks"][1]["clips"]],
                         [(2.2, "put back"), (4.2, None)])


class TestVoiceWordTimings(unittest.TestCase):
    def test_positions_are_scaled_and_repeats_dropped(self):
        text = "Meet it. Now $129 today!"
        # As System.Speech reports them for a 22.05 kHz file: "$129 today" fires three times.
        events = "\n".join(["137.8 0 4", "591.9 5 2", "3023.4 9 3", "3285.6 13 10", "3878.1 13 10",
                            "4477.4 13 10", ""])
        found = voiceover.words(text, events, 22050, 5.0)
        self.assertEqual([w["text"] for w in found], ["Meet", "it.", "Now", "$129 today!"])
        self.assertEqual([w["start"] for w in found], [0.1, 0.429, 2.194, 2.384])
        self.assertEqual([w["end"] for w in found], [0.429, 2.194, 2.384, 5.0])


class TestPiperWordTimings(unittest.TestCase):
    # Piper says how many samples each phoneme lasts; "^" and "$" open and close a sentence.
    def test_each_word_spans_its_phonemes_and_not_the_pause_after(self):
        aligned = [("^", 100), ("m", 100), ("i", 100), ("t", 100), (" ", 200), ("ɪ", 100), ("t", 100), (".", 100),
                   ("$", 100), ("^", 100), ("n", 100), ("a", 100), (" ", 100), ("g", 100), ("o", 100), ("!", 100),
                   ("$", 100)]
        found = voiceover.piper_words("Meet it. Now go!", [1, 1, 1, 1], aligned, 1000)
        self.assertEqual([(w["start"], w["end"], w["text"]) for w in found],
                         [(0.1, 0.4, "Meet"), (0.6, 0.9, "it."), (1.1, 1.3, "Now"), (1.4, 1.7, "go!")])

    def test_a_number_said_as_several_words_is_one_word_on_screen(self):
        aligned = [("^", 100), ("d", 100), (" ", 100), ("w", 100), (" ", 100), ("n", 100), (" ", 100), ("t", 100),
                   ("$", 100)]
        found = voiceover.piper_words("$129 today", [3, 1], aligned, 1000)
        self.assertEqual([(w["start"], w["end"], w["text"]) for w in found], [(0.1, 0.6, "$129"), (0.7, 0.8, "today")])

    def test_words_the_voice_runs_together_still_come_in_order(self):
        # Piper says "everyone... so," without a break between them: four words, three runs of phonemes.
        aligned = [("^", 100), ("h", 100), (" ", 100), ("e", 100), ("s", 100), (",", 100), (" ", 100), ("t", 100),
                   ("$", 100)]
        found = voiceover.piper_words("Hey everyone... so, today", [1, 1, 1, 1], aligned, 1000)
        self.assertEqual([w["text"] for w in found], ["Hey", "everyone...", "so,", "today"])
        times = [t for w in found for t in (w["start"], w["end"])]
        self.assertEqual(times, sorted(times))
        self.assertEqual((times[0], times[-1]), (0.1, 0.8))

    def test_a_mark_with_nothing_to_say_is_left_out(self):
        aligned = [("^", 100), ("m", 100), (" ", 100), ("ɪ", 100), ("$", 100)]
        found = voiceover.piper_words("Meet — it", [1, 0, 1], aligned, 1000)
        self.assertEqual([w["text"] for w in found], ["Meet", "it"])

    def test_piper_voices_are_offered_first(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(voiceover, "PIPER_DIR", Path(tmp)), \
                mock.patch.object(voiceover, "_powershell", lambda script: mock.Mock(stdout="Microsoft Zira Desktop\n")):
            (Path(tmp) / "en_US-ljspeech-high.onnx").write_bytes(b"")
            self.assertEqual(voiceover.voices(), ["en_US-ljspeech-high", "Microsoft Zira Desktop"])

    def test_without_windows_powershell_piper_s_voices_are_still_offered(self):
        def no_powershell(script):
            raise voiceover.VoiceError("the built-in voice needs Windows PowerShell")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(voiceover, "PIPER_DIR", Path(tmp)), \
                mock.patch.object(voiceover, "_powershell", no_powershell):
            (Path(tmp) / "en_US-ljspeech-high.onnx").write_bytes(b"")
            self.assertEqual(voiceover.voices(), ["en_US-ljspeech-high"])

    @unittest.skipUnless((voiceover.PIPER_DIR / f"{voiceover.DEFAULT_PIPER_VOICE}.onnx").exists(),
                         "the Piper voice is not installed")
    def test_piper_reads_a_line_with_a_time_for_every_word(self):
        text = "Meet the Nova jacket. Now $129, only today!"
        with tempfile.TemporaryDirectory() as tmp:
            wav = voiceover.speak(text, Path(tmp) / "line.wav", voiceover.DEFAULT_PIPER_VOICE)
            said = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
            with wave.open(str(wav)) as w:
                duration = w.getnframes() / w.getframerate()
        self.assertEqual([w["text"] for w in said], text.split())
        self.assertLessEqual(said[-1]["end"], duration)


if __name__ == "__main__":
    unittest.main()
