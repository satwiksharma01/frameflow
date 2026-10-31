"""Keeping the speaker in a vertical crop: when the window moves, and how far."""
import unittest

from project import reframe

FRAME, SOURCE = (1080, 1920), (1280, 720)      # a 720p recording in a 9:16 frame
WHOLE = (0, 1280)


def offset(centre):
    """The picture's offset that centres the window on `centre` (source px)."""
    return round((640 - centre) / 405, 6)        # scale 1920/720; window 405 px wide


def faces(*spans):
    """(seconds, x) spans -> a sample every quarter second."""
    out, t = [], 0.0
    for seconds, x in spans:
        for _ in range(int(seconds * reframe.SAMPLE_FPS)):
            out.append((t, x))
            t += 1 / reframe.SAMPLE_FPS
    return out


class TestCropKeys(unittest.TestCase):
    def test_a_still_speaker_gets_one_framing(self):
        self.assertEqual(reframe.crop_keys(faces((20, 700)), FRAME, SOURCE, WHOLE),
                         [{"at": 0.0, "value": offset(700)}])

    def test_a_glance_aside_does_not_move_the_window(self):
        keys = reframe.crop_keys(faces((5, 640), (1, 900), (5, 640)), FRAME, SOURCE, WHOLE)
        self.assertEqual(keys, [{"at": 0.0, "value": 0.0}])

    def test_moving_across_the_room_is_one_smooth_move(self):
        keys = reframe.crop_keys(faces((10, 500), (10, 900)), FRAME, SOURCE, WHOLE)
        self.assertEqual(keys, [{"at": 0.0, "value": offset(500)},
                                {"at": 10.0, "value": offset(500)},
                                {"at": 10.0 + reframe.MOVE_SECONDS, "value": offset(900)}])

    def test_the_framing_is_where_the_speaker_usually_is_not_where_they_started(self):
        keys = reframe.crop_keys(faces((2, 560), (18, 650)), FRAME, SOURCE, WHOLE)
        self.assertEqual(keys, [{"at": 0.0, "value": offset(650)}])

    def test_black_bars_never_come_into_view(self):
        """The picture is 386-894 px wide: the window's centre stays within 588.5-691.5."""
        keys = reframe.crop_keys(faces((10, 950)), FRAME, SOURCE, (386, 894))
        self.assertEqual(keys, [{"at": 0.0, "value": offset(691.5)}])

    def test_no_face_centres_the_picture(self):
        keys = reframe.crop_keys(faces((10, None)), FRAME, SOURCE, (300, 1100))
        self.assertEqual(keys, [{"at": 0.0, "value": offset(700)}])


class TestPerClip(unittest.TestCase):
    KEYS = [{"at": 0.0, "value": 0.3}, {"at": 10.0, "value": 0.3}, {"at": 11.0, "value": -0.1}]

    def test_a_clip_where_the_window_holds_still_gets_one_value(self):
        self.assertEqual(reframe.clip_offset(self.KEYS, 2.0, 8.0), 0.3)
        self.assertEqual(reframe.clip_offset(self.KEYS, 12.0, 20.0), -0.1)

    def test_a_clip_across_a_move_starts_where_the_window_is(self):
        self.assertEqual(reframe.clip_offset(self.KEYS, 9.0, 10.5),
                         [{"at": 9.0, "value": 0.3}, {"at": 10.0, "value": 0.3}, {"at": 10.5, "value": 0.1}])

    def test_only_filled_clips_follow(self):
        ir = {"tracks": [{"id": "V1", "type": "video", "clips": [
            {"source_in": 9.0, "source_out": 12.0, "transform": {"fill": True}},
            {"source_in": 2.0, "source_out": 4.0, "transform": {"fill": True}},
            {"source_in": 2.0, "source_out": 4.0}]}]}
        self.assertEqual(reframe.follow(ir, [{"at": 0.0, "value": 0.0}, {"at": 10.0, "value": 0.0},
                                             {"at": 11.0, "value": -0.1}]), 1)
        moving, still, fitted = ir["tracks"][0]["clips"]
        self.assertEqual(moving["transform"]["position"]["x"][-1], {"at": 11.0, "value": -0.1})
        self.assertEqual(still["transform"], {"fill": True})                 # centred: no position
        self.assertNotIn("transform", fitted)


if __name__ == "__main__":
    unittest.main()
