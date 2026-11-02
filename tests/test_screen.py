"""A screen recording under the face: lined up by the voice, laid out, and cut with the face."""
import copy
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from project import screen
from project.broll import MUTED_DB
from project.change_agent import build_context
from project.media import MediaError
from project.reconcile import HumanChanges, source_key
from project.validate import validate

FACE, SHOWN = "C:/media/face.mp4", "C:/media/screen.mp4"
RATE = 16000


def _voice(seconds: float, seed: int) -> np.ndarray:
    """Speech as a level meter sees it: bursts a syllable long, with pauses between them."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * RATE))
    at = 0
    while at < len(out):
        length = min(int(rng.uniform(0.05, 0.3) * RATE), len(out) - at)
        out[at:at + length] = rng.normal(0, 0.3, length) * np.hanning(length)
        at += length + int(rng.uniform(0.05, 0.6) * RATE)
    return out


def _other_mic(samples: np.ndarray, seed: int) -> np.ndarray:
    """The same sound through a duller, quieter microphone with its own hiss."""
    dull = np.convolve(samples, np.ones(8) / 8, mode="same")
    return 0.5 * dull + np.random.default_rng(seed).normal(0, 0.01, len(samples))


def _write(path: Path, samples: np.ndarray) -> Path:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def _clip(source, source_in, source_out, timeline_start, **extra):
    return {"id": "", "source": source, "source_in": source_in, "source_out": source_out,
            "timeline_start": timeline_start, "timeline_duration": round(source_out - source_in, 6), **extra}


def _ir(face: list[dict], shown: list[dict] | None = None) -> dict:
    tracks = [{"id": "V1", "type": "video", "clips": copy.deepcopy(face)}]
    if shown is not None:
        tracks.insert(0, {"id": "Screen", "type": "screen", "clips": copy.deepcopy(shown)})
    for track in tracks:
        for n, clip in enumerate(track["clips"], start=1):
            clip["id"] = f"clip{n}"
    return {"schema_version": "0.2.0",
            "project": {"name": "t", "width": 1920, "height": 1080, "fps": 30, "source_frame_rate_mode": "cfr"},
            "tracks": tracks}


def _spans(ir: dict) -> list[tuple]:
    """(screen moments in, out, where they play) for each screen clip."""
    track = next(t for t in ir["tracks"] if t["type"] == "screen")
    return [(c["source_in"], c["source_out"], c["timeline_start"]) for c in track["clips"]]


# A first cut that took out a pause at 10-12 s, over a screen recording started 3 s before the face.
FIRST_CUT = [_clip(FACE, 0.0, 10.0, 0.0), _clip(FACE, 12.0, 20.0, 10.0)]
UNDER = [_clip(SHOWN, 3.0, 13.0, 0.0, volume_db=MUTED_DB), _clip(SHOWN, 15.0, 23.0, 10.0, volume_db=MUTED_DB)]
# The same cut after an edit took out 4-6 s.
TIGHTER = [_clip(FACE, 0.0, 4.0, 0.0), _clip(FACE, 6.0, 10.0, 4.0), _clip(FACE, 12.0, 20.0, 8.0)]


class TestLiningUp(unittest.TestCase):
    """Two recordings of one voice through different microphones, started apart."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        voice = _voice(30, seed=1)
        cls.face = _write(root / "face.wav", voice[:25 * RATE])
        cls.first = _write(root / "first.wav", _other_mic(np.concatenate([np.zeros(int(2.5 * RATE)), voice]), 2))
        cls.second = _write(root / "second.wav", _other_mic(voice[int(1.2 * RATE):], 3))
        cls.other = _write(root / "other.wav", _other_mic(_voice(30, seed=4), 5))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_a_screen_started_first_runs_ahead_of_the_face(self):
        self.assertAlmostEqual(screen.offset(self.face, self.first), 2.5, delta=0.01)

    def test_a_screen_started_second_runs_behind(self):
        self.assertAlmostEqual(screen.offset(self.face, self.second), -1.2, delta=0.01)

    def test_recordings_that_share_no_voice_are_refused(self):
        with self.assertRaises(MediaError) as cm:
            screen.offset(self.face, self.other)
        self.assertIn("voice", str(cm.exception))


class TestTheLayout(unittest.TestCase):
    def test_a_720p_face_is_a_quarter_of_the_frame_48px_from_its_corner(self):
        # 1280x720 fits 1920x1080 at 1.5; a quarter of that is 480x270, centred 48+240 px from
        # the right and 48+135 px from the bottom.
        self.assertEqual(screen.face_transform((1280, 720)),
                         {"scale": 0.25, "position": {"x": 0.35, "y": 0.330556}})

    def test_a_4_3_face_keeps_its_shape(self):
        # 640x480 fits at 2.25, 1440x1080; a quarter of that is 360x270.
        self.assertEqual(screen.face_transform((640, 480)),
                         {"scale": 0.25, "position": {"x": 0.38125, "y": 0.330556}})


class TestLayingOut(unittest.TestCase):
    def laid(self, shift: float, length: float = 100.0) -> dict:
        ir = _ir(FIRST_CUT)
        ir["project"].update(width=1280, height=720)
        screen.lay_out(ir, SHOWN, shift, length, (1280, 720))
        validate(ir, "ir")
        return ir

    def test_the_screen_goes_under_the_face_showing_what_was_on_it_as_each_word_was_said(self):
        ir = self.laid(3.0)
        self.assertEqual([t["type"] for t in ir["tracks"]], ["screen", "video"])
        self.assertEqual(_spans(ir), [(3.0, 13.0, 0.0), (15.0, 23.0, 10.0)])
        self.assertEqual({c["volume_db"] for c in ir["tracks"][0]["clips"]}, {MUTED_DB})

    def test_the_frame_is_youtubes_with_the_face_in_its_corner(self):
        ir = self.laid(3.0)
        self.assertEqual((ir["project"]["width"], ir["project"]["height"]), screen.FRAME)
        self.assertEqual([c["transform"] for c in ir["tracks"][1]["clips"]],
                         [screen.face_transform((1280, 720))] * 2)

    def test_a_screen_started_after_the_face_comes_in_under_it_later(self):
        self.assertEqual(_spans(self.laid(-2.0)), [(0.0, 8.0, 2.0), (10.0, 18.0, 10.0)])

    def test_the_screen_stops_where_its_recording_does(self):
        self.assertEqual(_spans(self.laid(3.0, length=18.0)), [(3.0, 13.0, 0.0), (15.0, 18.0, 10.0)])


class TestFollowingTheCut(unittest.TestCase):
    def edited(self, before: dict, face: list[dict], length: float = 100.0) -> dict:
        after = copy.deepcopy(before)
        after["tracks"][1] = _ir(face)["tracks"][0]
        screen.follow(before, after, {source_key(SHOWN): length})
        validate(after, "ir")
        return after

    def test_what_an_edit_cuts_from_the_face_it_cuts_from_the_screen(self):
        self.assertEqual(_spans(self.edited(_ir(FIRST_CUT, UNDER), TIGHTER)),
                         [(3.0, 7.0, 0.0), (9.0, 13.0, 4.0), (15.0, 23.0, 8.0)])

    def test_a_pause_put_back_gets_the_screen_recorded_with_it(self):
        self.assertEqual(_spans(self.edited(_ir(FIRST_CUT, UNDER), [_clip(FACE, 0.0, 20.0, 0.0)])),
                         [(3.0, 23.0, 0.0)])

    def test_a_screen_clip_the_creator_deleted_stays_gone(self):
        self.assertEqual(_spans(self.edited(_ir(FIRST_CUT, UNDER[1:]), TIGHTER)), [(15.0, 23.0, 8.0)])

    def test_speech_put_back_beside_a_deleted_stretch_gets_the_screen_only_from_the_side_it_played(self):
        self.assertEqual(_spans(self.edited(_ir(FIRST_CUT, UNDER[:1]), [_clip(FACE, 0.0, 20.0, 0.0)])),
                         [(3.0, 15.0, 0.0)])

    def test_a_zoom_on_the_screen_stays_on_its_moments(self):
        zoomed = copy.deepcopy(UNDER)
        zoomed[0]["transform"] = {"scale": 2.0, "position": {"x": 0.2}}
        after = self.edited(_ir(FIRST_CUT, zoomed), TIGHTER)
        self.assertEqual([c.get("transform") for c in after["tracks"][0]["clips"]],
                         [zoomed[0]["transform"]] * 2 + [None])

    def test_a_fade_stays_on_its_clips_edge(self):
        faded = copy.deepcopy(UNDER)
        faded[0]["fade_in"] = {"picture": 1.0}
        after = self.edited(_ir(FIRST_CUT, faded), TIGHTER)
        self.assertEqual([c.get("fade_in") for c in after["tracks"][0]["clips"]], [{"picture": 1.0}, None, None])

    def test_speech_put_back_from_before_the_screen_was_started_shows_it_from_its_start(self):
        # The screen was started 2 s after the face, and the first cut had left out the face's first 5 s.
        before = _ir([_clip(FACE, 5.0, 15.0, 0.0)], [_clip(SHOWN, 3.0, 13.0, 0.0)])
        self.assertEqual(_spans(self.edited(before, [_clip(FACE, 0.0, 15.0, 0.0)])), [(0.0, 13.0, 2.0)])

    def test_and_from_after_it_was_stopped_up_to_its_end(self):
        before = _ir([_clip(FACE, 0.0, 10.0, 0.0)], [_clip(SHOWN, 3.0, 13.0, 0.0)])
        self.assertEqual(_spans(self.edited(before, [_clip(FACE, 0.0, 14.0, 0.0)], length=15.0)),
                         [(3.0, 15.0, 0.0)])


class TestTheEditorIsTold(unittest.TestCase):
    def test_the_screen_track_is_described_as_cut_with_the_face(self):
        ir = _ir(FIRST_CUT, UNDER)
        timing = {"source": FACE, "duration_seconds": 20.0, "words": [], "pauses": []}
        context = build_context("tighten it", ir, HumanChanges(known=True), timing)
        self.assertIn("- Screen (screen): 2 clip(s). The screen recording, cut wherever the main track is cut.",
                      context)


if __name__ == "__main__":
    unittest.main()
