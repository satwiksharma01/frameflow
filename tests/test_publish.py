"""The publish package: title, description, tags and chapters, checked against YouTube's limits,
with each chapter where its moment of the recording plays in the cut as it is now."""
import unittest
from pathlib import Path

from project import publish

REC = "C:/media/talk.mp4"


def clip(source_in, source_out, timeline_start):
    return {"id": "c", "source": REC, "source_in": source_in, "source_out": source_out,
            "timeline_start": timeline_start, "timeline_duration": source_out - source_in}


def cut(*clips):
    return {"project": {"fps": 30}, "tracks": [{"id": "V1", "type": "video", "clips": list(clips)}]}


# 0-30s of the recording, then 40-100s: ten seconds cut out, 90s long.
CUT = cut(clip(0.0, 30.0, 0.0), clip(40.0, 100.0, 30.0))


def doc(**fields):
    return {"title": "Three things nobody tells you about starting a channel",
            "description": "What I wish I'd known before my first video.",
            "tags": ["starting a youtube channel", "youtube tips"],
            "chapters": [{"title": "Why I started"}, {"title": "Gear", "at": 20.5}, {"title": "Editing", "at": 61.2}],
            **fields}


def chapter_lines(package, ir=CUT):
    return publish.description(package, ir, REC).split("\n\n")[-1].splitlines()


class TestChapterTimes(unittest.TestCase):
    def test_each_chapter_starts_where_its_moment_of_the_recording_plays(self):
        self.assertEqual(publish.check(doc(), CUT, REC), [])
        self.assertEqual(chapter_lines(doc()), ["0:00 Why I started", "0:20 Gear", "0:51 Editing"])

    def test_after_an_edit_cuts_before_a_chapter_its_time_moves_up_with_the_cut(self):
        tighter = cut(clip(0.0, 30.0, 0.0), clip(45.0, 100.0, 30.0))      # five more seconds out
        self.assertEqual(chapter_lines(doc(), tighter)[2], "0:46 Editing")

    def test_times_round_down_so_a_chapter_never_starts_after_its_first_word(self):
        package = doc(chapters=[{"title": "Why I started"}, {"title": "Gear", "at": 20.9},
                                {"title": "Editing", "at": 61.2}])
        self.assertEqual(chapter_lines(package)[1], "0:20 Gear")

    def test_a_chapter_whose_moment_is_not_in_the_cut_is_named(self):
        package = doc(chapters=[{"title": "Why I started"}, {"title": "Gear", "at": 20.5},
                                {"title": "Editing", "at": 35.0}])
        problems = publish.check(package, CUT, REC)
        self.assertEqual(len(problems), 1)
        self.assertIn("chapter 3 (Editing", problems[0])
        self.assertIn("not in the cut", problems[0])

    def test_a_chapter_under_ten_seconds_is_named(self):
        package = doc(chapters=[{"title": "Why I started"}, {"title": "Gear", "at": 20.5},
                                {"title": "Editing", "at": 25.0}])
        problems = publish.check(package, CUT, REC)
        self.assertEqual(len(problems), 1)
        self.assertIn("chapter 2 (Gear) runs 5", problems[0])

    def test_the_last_chapter_needs_ten_seconds_before_the_video_ends(self):
        package = doc(chapters=[{"title": "Why I started"}, {"title": "Gear", "at": 20.5},
                                {"title": "Outro", "at": 95.0}])
        self.assertIn("chapter 3 (Outro)", publish.check(package, CUT, REC)[0])

    def test_chapters_out_of_playing_order_are_named(self):
        package = doc(chapters=[{"title": "Why I started"}, {"title": "Editing", "at": 61.2},
                                {"title": "Gear", "at": 20.5}])
        self.assertIn("chapter 2 (Editing)", publish.check(package, CUT, REC)[0])

    def test_fewer_than_three_chapters_are_refused(self):
        package = doc(chapters=[{"title": "Why I started"}, {"title": "Gear", "at": 20.5}])
        self.assertTrue(publish.check(package, CUT, REC))

    def test_the_first_chapter_starts_the_video_so_it_takes_no_moment(self):
        package = doc(chapters=[{"title": "Why I started", "at": 5.0}, {"title": "Gear", "at": 20.5},
                                {"title": "Editing", "at": 61.2}])
        self.assertTrue(publish.check(package, CUT, REC))

    def test_a_video_of_an_hour_or_more_has_hours_in_every_time(self):
        long = cut(clip(0.0, 4000.0, 0.0))
        package = doc(chapters=[{"title": "Intro"}, {"title": "Gear", "at": 600.0}, {"title": "Q&A", "at": 3700.4}])
        self.assertEqual(publish.check(package, long, REC), [])
        self.assertEqual(chapter_lines(package, long), ["0:00:00 Intro", "0:10:00 Gear", "1:01:40 Q&A"])

    def test_a_short_without_chapters_gets_its_description_alone(self):
        package = doc()
        del package["chapters"]
        self.assertEqual(publish.check(package, CUT, REC), [])
        self.assertEqual(publish.description(package, CUT, REC), "What I wish I'd known before my first video.")


class TestYouTubesLimits(unittest.TestCase):
    def test_a_title_over_100_characters_is_named(self):
        problems = publish.check(doc(title="x" * 101), CUT, REC)
        self.assertEqual(len(problems), 1)
        self.assertIn("101 characters", problems[0])
        self.assertEqual(publish.check(doc(title="x" * 100), CUT, REC), [])

    def test_angle_brackets_are_refused_in_the_title_and_the_description(self):
        problems = publish.check(doc(title="Gear <2026>", description="a -> b"), CUT, REC)
        self.assertEqual(len(problems), 2)

    def test_tags_are_counted_as_youtube_counts_them(self):
        self.assertEqual(publish.tags_length(["Foo-Baz"]), 7)                 # YouTube's own examples
        self.assertEqual(publish.tags_length(["Foo Baz"]), 9)                 # the quotes round a space count
        self.assertEqual(publish.tags_length(["Foo-Baz", "Foo Baz"]), 17)     # and so does the comma
        self.assertEqual(publish.check(doc(tags=["x" * 500]), CUT, REC), [])
        self.assertIn("501 characters", publish.check(doc(tags=["x" * 499, "y"]), CUT, REC)[0])

    def test_the_description_and_its_chapter_list_must_fit_5000_bytes(self):
        self.assertEqual(publish.check(doc(description="x" * 4900), CUT, REC), [])
        self.assertIn("bytes", publish.check(doc(description="x" * 4990), CUT, REC)[0])
        short = doc(description="é" * 2600)                                   # 2,600 characters, 5,200 bytes
        del short["chapters"]
        self.assertIn("bytes", publish.check(short, CUT, REC)[0])


class TestThePackage(unittest.TestCase):
    def test_each_part_is_ready_to_paste(self):
        self.assertEqual(publish.package(doc(), CUT, REC),
                         "Title\nThree things nobody tells you about starting a channel\n\n"
                         "Description\nWhat I wish I'd known before my first video.\n\n"
                         "0:00 Why I started\n0:20 Gear\n0:51 Editing\n\n"
                         "Tags\nstarting a youtube channel, youtube tips\n")


class TestTheRequest(unittest.TestCase):
    TIMING = {"source": REC, "duration_seconds": 100.0, "pauses": [], "words": [
        {"text": " Why", "start": 1.0, "end": 1.3}, {"text": " I", "start": 1.3, "end": 1.4},
        {"text": " started.", "start": 1.4, "end": 2.0},
        {"text": " Gone.", "start": 35.0, "end": 35.4},                        # cut out
        {"text": " Editing", "start": 61.2, "end": 61.6}, {"text": " next.", "start": 61.6, "end": 62.0},
    ]}

    def test_it_lists_what_is_said_in_the_cut_with_the_moment_of_the_recording_and_where_it_plays(self):
        request = publish.build_request(CUT, self.TIMING, Path("out/publish.json"), "python -m project.publish x --write")
        self.assertIn("[1.00] 0:01  Why I started.", request)
        self.assertIn("[61.20] 0:51  Editing next.", request)
        self.assertNotIn("Gone.", request)
        self.assertLess(request.index("Why I started."), request.index("Editing next."))
        self.assertIn("out/publish.json", request)


if __name__ == "__main__":
    unittest.main()
