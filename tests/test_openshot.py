#!/usr/bin/env python3
"""The OpenShot bridge: IR -> .osp -> IR, checked against a project OpenShot saved.

examples/openshot-saved.osp was made by hand in OpenShot 4.0.1: two clips with a
gap on Track 1, one clip on Track 2, and a transparent caption on Track 3. Tests
that compile need the media (not committed) and OpenShot's profile files, and
skip themselves without them.

Run with: python -m unittest discover tests
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from project.parse_mlt import quantize_ir
from project.media import _find_tool
from project.parse_osp import ParseError, parse_osp

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENSHOT_SAVED = REPO_ROOT / "examples" / "openshot-saved.osp"
MEDIA = REPO_ROOT / "media"
NORMALIZED_MEDIA = MEDIA / "meet-recording-cfr30.mp4"
CAPTION_MEDIA = MEDIA / "caption.mov"
SECOND_MEDIA = MEDIA / "synthetic-talk.mp4"

# What OpenShot sets per clip; everything else on a clip is a default.
PER_CLIP = {"id", "layer", "position", "start", "end", "file_id", "title", "image",
            "reader", "duration"}


def _have_profiles() -> bool:
    from project.openshot_template import profile_dirs
    return bool(profile_dirs())


def _ir(tracks: list[dict]) -> dict:
    return {"schema_version": "0.2.0",
            "project": {"name": "p", "width": 1920, "height": 1080, "fps": 30,
                        "source_frame_rate_mode": "cfr"},
            "tracks": tracks}


def _clip(clip_id: str, source: Path, source_in: float, timeline_start: float,
          duration: float) -> dict:
    return {"id": clip_id, "source": source.as_posix(), "source_in": source_in,
            "source_out": source_in + duration, "timeline_start": timeline_start,
            "timeline_duration": duration}


class TestTemplateMatchesOpenShot(unittest.TestCase):
    """The conventions the compiler writes are the ones OpenShot wrote."""

    def setUp(self):
        self.saved = json.loads(OPENSHOT_SAVED.read_text(encoding="utf-8"))

    def test_clip_defaults_are_what_openshot_gives_an_untouched_clip(self):
        from project.openshot_template import CLIP_DEFAULTS
        for clip in self.saved["clips"]:
            defaults = {k: v for k, v in clip.items() if k not in PER_CLIP}
            self.assertEqual(defaults, CLIP_DEFAULTS, f"clip {clip['id']}")

    def test_declared_version_is_the_one_the_defaults_came_from(self):
        from project.openshot_template import OPENSHOT_VERSION
        self.assertEqual(self.saved["version"], OPENSHOT_VERSION)

    def test_layer_numbering(self):
        from project.openshot_template import layer
        self.assertEqual([l["number"] for l in self.saved["layers"]],
                         [layer(i, "")["number"] for i in range(5)])


class TestParseOpenShotSave(unittest.TestCase):
    def setUp(self):
        self.ir = parse_osp(OPENSHOT_SAVED)

    def timeline(self, track: dict) -> list[tuple]:
        return [(c["timeline_start"], c["source_in"], c["source_out"], Path(c["source"]).name)
                for c in track["clips"]]

    def test_profile(self):
        project = self.ir["project"]
        self.assertEqual((project["width"], project["height"], project["fps"]), (1920, 1080, 30))

    def test_every_layer_is_a_track_named_as_openshot_shows_it(self):
        self.assertEqual([t["id"] for t in self.ir["tracks"]],
                         ["Track 1", "Track 2", "Track 3", "Track 4", "Track 5"])

    def test_two_clips_with_a_gap_on_track_1(self):
        self.assertEqual(self.timeline(self.ir["tracks"][0]), [
            (0.0, 2.0, 6.0, "meet-recording-cfr30.mp4"),
            (8.0, 10.0, 14.0, "meet-recording-cfr30.mp4"),
        ])

    def test_upper_tracks(self):
        self.assertEqual(self.timeline(self.ir["tracks"][1]),
                         [(1.0, 16.0, 20.0, "meet-recording-cfr30.mp4")])
        self.assertEqual(self.timeline(self.ir["tracks"][2]), [(2.0, 0.0, 4.0, "caption.mov")])
        self.assertEqual(self.ir["tracks"][3]["clips"], [])

    def test_relative_media_paths_resolve_against_the_project_folder(self):
        source = Path(self.ir["tracks"][0]["clips"][0]["source"])
        self.assertTrue(source.is_absolute())
        self.assertEqual(source, NORMALIZED_MEDIA.resolve())

    def test_no_provenance_without_a_sidecar(self):
        self.assertEqual(self.ir["project"]["source_frame_rate_mode"], "cfr")

    def _broken(self, change) -> Path:
        data = json.loads(OPENSHOT_SAVED.read_text(encoding="utf-8"))
        change(data)
        path = Path(self.tmp.name) / "broken.osp"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_a_clip_on_an_undeclared_layer_is_an_error(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = self._broken(lambda d: d["clips"][0].update(layer=9_000_000))
        with self.assertRaises(ParseError):
            parse_osp(path)

    def test_a_clip_with_no_media_path_is_an_error(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = self._broken(lambda d: d["clips"][0]["reader"].pop("path"))
        with self.assertRaises(ParseError):
            parse_osp(path)


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        if not (NORMALIZED_MEDIA.exists() and CAPTION_MEDIA.exists()):
            self.skipTest("media not present")
        if not _have_profiles():
            self.skipTest("OpenShot's profiles not found; is OpenShot installed?")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def compile_and_parse(self, ir: dict, name: str = "p") -> dict:
        from project.compile_osp import compile_file
        ir_path = Path(self.tmp.name) / f"{name}.ir.json"
        ir_path.write_text(json.dumps(ir), encoding="utf-8")
        return parse_osp(compile_file(ir_path, Path(self.tmp.name) / f"{name}.osp"))

    def test_the_openshot_save_round_trips(self):
        """Read OpenShot's project, write it back out, read that: same timeline."""
        original = parse_osp(OPENSHOT_SAVED)
        self.assertEqual(quantize_ir(original), quantize_ir(self.compile_and_parse(original)))

    def test_two_sources_on_two_tracks_round_trip(self):
        if not SECOND_MEDIA.exists():
            self.skipTest("second media file not present")
        ir = _ir([
            {"id": "V1", "type": "video", "clips": [
                _clip("clip1", NORMALIZED_MEDIA, 0.0, 0.0, 4.0),
                _clip("clip2", NORMALIZED_MEDIA, 6.0, 6.0, 4.0)]},
            {"id": "V2", "type": "broll", "clips": [_clip("clip1", SECOND_MEDIA, 1.0, 2.0, 2.0)]},
        ])
        parsed = self.compile_and_parse(ir)
        self.assertEqual(quantize_ir(ir), quantize_ir(parsed))
        self.assertEqual([t["id"] for t in parsed["tracks"]], ["V1", "V2"])

    def test_fades_opacity_and_volume_round_trip(self):
        clip = _clip("clip1", NORMALIZED_MEDIA, 2.0, 0.0, 4.0)
        clip.update(opacity=0.5, volume_db=-6.0, fade_in={"picture": 1.0, "sound": 1.0},
                    fade_out={"sound": 3.0})
        parsed = self.compile_and_parse(_ir([{"id": "V1", "type": "video", "clips": [clip]}]))
        back = parsed["tracks"][0]["clips"][0]
        self.assertEqual({k: back.get(k) for k in ("opacity", "fade_in", "fade_out")},
                         {"opacity": 0.5, "fade_in": {"picture": 1.0, "sound": 1.0},
                          "fade_out": {"sound": 3.0}})
        self.assertAlmostEqual(back["volume_db"], -6.0, places=5)

    def test_the_sidecar_restores_what_openshot_cannot_hold(self):
        ir = _ir([{"id": "V1", "type": "broll",
                   "clips": [_clip("clip1", NORMALIZED_MEDIA, 0.0, 0.0, 2.0)]}])
        ir["project"]["source_frame_rate_mode"] = "normalized_from_vfr"
        parsed = self.compile_and_parse(ir)
        self.assertEqual(parsed["tracks"][0]["type"], "broll")
        self.assertEqual(parsed["project"]["source_frame_rate_mode"], "normalized_from_vfr")


class TestCompiledProject(unittest.TestCase):
    """What the compiler writes, beyond what the parser reads back."""

    def setUp(self):
        if not NORMALIZED_MEDIA.exists():
            self.skipTest("media not present")
        if not _have_profiles():
            self.skipTest("OpenShot's profiles not found; is OpenShot installed?")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def compile(self, ir: dict) -> dict:
        from project.compile_osp import build_osp
        return build_osp(ir, Path(self.tmp.name))

    def test_names_the_profile_openshot_has_for_these_settings(self):
        """An unknown name would open as HD 720p 30 fps."""
        osp = self.compile(_ir([{"id": "V1", "type": "video",
                                 "clips": [_clip("c1", NORMALIZED_MEDIA, 0.0, 0.0, 2.0)]}]))
        self.assertEqual(osp["profile"], "FHD 1080p 30 fps")

    def test_a_size_openshot_has_no_profile_for_is_refused(self):
        from project.openshot_template import ProfileError
        ir = _ir([{"id": "V1", "type": "video",
                   "clips": [_clip("c1", NORMALIZED_MEDIA, 0.0, 0.0, 2.0)]}])
        ir["project"].update(width=1366, height=768)
        with self.assertRaises(ProfileError):
            self.compile(ir)

    def test_clips_from_one_file_share_one_file_entry(self):
        osp = self.compile(_ir([{"id": "V1", "type": "video", "clips": [
            _clip("c1", NORMALIZED_MEDIA, 0.0, 0.0, 2.0),
            _clip("c2", NORMALIZED_MEDIA, 5.0, 2.0, 2.0)]}]))
        self.assertEqual(len(osp["files"]), 1)
        self.assertEqual({c["file_id"] for c in osp["clips"]}, {osp["files"][0]["id"]})

    def test_media_inside_the_project_folder_is_referenced_relatively(self):
        """As OpenShot writes it, so the folder can move."""
        root = Path(self.tmp.name)
        (root / "media").mkdir()
        shutil.copy(NORMALIZED_MEDIA, root / "media" / "clip.mp4")
        osp = self.compile(_ir([{"id": "V1", "type": "video",
                                 "clips": [_clip("c1", root / "media" / "clip.mp4", 0.0, 0.0, 2.0)]}]))
        self.assertEqual(osp["files"][0]["path"], "media/clip.mp4")
        self.assertEqual(osp["clips"][0]["reader"]["path"], "media/clip.mp4")

    def test_a_fade_in_is_written_as_openshots_fade_menu_writes_it(self):
        """Fade In (Fast) on a clip from 5s at 30 fps: source frames 151 to 181, Bezier."""
        from project.openshot_template import keyframe
        clip = _clip("c1", NORMALIZED_MEDIA, 5.0, 0.0, 2.0)
        clip["fade_in"] = {"picture": 1.0, "sound": 1.0}
        written = self.compile(_ir([{"id": "V1", "type": "video", "clips": [clip]}]))["clips"][0]
        fade = {"Points": keyframe(0.0, x=151.0)["Points"] + keyframe(1.0, x=181.0)["Points"]}
        self.assertEqual(written["alpha"], fade)
        self.assertEqual(written["volume"], fade)

    def test_a_clip_past_the_end_of_its_source_is_refused(self):
        with self.assertRaises(ValueError):
            self.compile(_ir([{"id": "V1", "type": "video",
                               "clips": [_clip("c1", NORMALIZED_MEDIA, 20.0, 0.0, 10.0)]}]))


class TestUnsupportedContent(unittest.TestCase):
    """What an edit that regenerates the project would lose. Each case starts
    from the project OpenShot saved and adds one thing a creator might."""

    def setUp(self):
        self.data = json.loads(OPENSHOT_SAVED.read_text(encoding="utf-8"))
        self.track1 = sorted((c for c in self.data["clips"] if c["layer"] == 1_000_000),
                             key=lambda c: c["position"])

    def found(self) -> list[str]:
        from project.parse_osp import unsupported_content
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.osp"
            path.write_text(json.dumps(self.data), encoding="utf-8")
            return unsupported_content(path)

    def test_a_real_save_loses_nothing(self):
        self.assertEqual(self.found(), [])

    def test_openshots_fades_and_levels_are_carried_not_named(self):
        """Fade In and Out on clip 2 (source 10-14s), at half volume."""
        from project.openshot_template import keyframe
        self.track1[1]["alpha"] = {"Points": keyframe(0.0, x=301)["Points"] + keyframe(1.0, x=331)["Points"]
                                   + keyframe(1.0, x=391)["Points"] + keyframe(0.0, x=421)["Points"]}
        self.track1[1]["volume"] = keyframe(0.5)
        self.assertEqual(self.found(), [])

    def test_a_hand_drawn_curve_is_named_with_its_clip(self):
        """A dip in the middle of clip 2 is not a fade the IR can hold."""
        from project.openshot_template import keyframe
        self.track1[1]["alpha"] = {"Points": keyframe(1.0, x=301)["Points"] + keyframe(0.2, x=350)["Points"]
                                   + keyframe(1.0, x=400)["Points"]}
        self.assertEqual(self.found(), ["changed alpha on clip 2 on Track 1"])

    def test_a_speed_change_and_a_move_are_named_together(self):
        from project.openshot_template import keyframe
        self.track1[0]["time"] = {"Points": keyframe(1, x=1)["Points"] + keyframe(60, x=30)["Points"]}
        self.track1[0]["location_x"] = keyframe(0.25)
        self.assertEqual(self.found(), ["changed location x, time on clip 1 on Track 1"])

    def test_an_effect_on_a_clip(self):
        self.track1[0]["effects"].append({"class_name": "Brightness", "id": "E1"})
        self.assertEqual(self.found(), ["the Brightness effect on clip 1 on Track 1"])

    def test_a_title_or_image_clip(self):
        self.track1[0]["reader"]["type"] = "QtImageReader"
        self.assertEqual(self.found(), ["a clip of type QtImageReader, clip 1 on Track 1"])

    def test_a_transition(self):
        self.data["effects"].append({"class_name": "Mask", "layer": 2_000_000, "id": "T1"})
        self.assertEqual(self.found(), ["a Mask transition on Track 2"])

    def test_a_locked_track_and_a_marker(self):
        self.data["layers"][2]["lock"] = True
        self.data["markers"].append({"id": "M1", "position": 3.0})
        self.assertEqual(self.found(), ["track Track 3 is locked", "1 marker(s) on the timeline"])

    def test_a_file_in_project_files_that_is_not_on_the_timeline(self):
        self.data["files"].append({**self.data["files"][0], "id": "UNUSED0001"})
        self.assertEqual(self.found(), ["1 file(s) in Project Files that are not on the timeline"])


class TestHearingAnOpenShotProject(unittest.TestCase):
    """Through libopenshot when OpenShot is installed, through FFmpeg otherwise."""

    def setUp(self):
        if not (NORMALIZED_MEDIA.exists() and CAPTION_MEDIA.exists()):
            self.skipTest("media not present")

    def test_the_main_track_renders_at_its_timeline_positions(self):
        """Track 1 is 0-4s and 8-12s: twelve seconds long, silent in between."""
        import subprocess
        from project.media import _find_tool
        from project.verify_cuts import render_osp_audio
        with tempfile.TemporaryDirectory() as tmp:
            wav = render_osp_audio(OPENSHOT_SAVED, Path(tmp) / "main.wav")
            probe = subprocess.run(
                [_find_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(wav)], capture_output=True, text=True)
            gap = subprocess.run(
                [_find_tool("ffmpeg"), "-nostats", "-ss", "4.0", "-t", "4.0", "-i", str(wav),
                 "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        self.assertAlmostEqual(float(probe.stdout), 12.0, places=2)
        loudest = float(gap.stderr.split("max_volume:")[1].split("dB")[0])
        self.assertLess(loudest, -80.0)


class TestEditors(unittest.TestCase):
    def test_openshot_is_the_default(self):
        from project.editors import DEFAULT, EDITORS
        self.assertEqual(EDITORS[DEFAULT].suffix, ".osp")

    def test_a_project_s_suffix_says_which_editor_it_belongs_to(self):
        from project.editors import editor_for
        self.assertEqual(editor_for("a/b.osp").name, "OpenShot")
        self.assertEqual(editor_for("a/b.MLT").name, "Shotcut")
        with self.assertRaises(ValueError):
            editor_for("a/b.kdenlive")


class TestCompilerRefusals(unittest.TestCase):
    """What the compiler will not guess at, and says so - before probing any media."""

    def test_a_caption_clip_with_no_source_is_refused_by_name(self):
        from project.compile_osp import build_osp
        ir = _ir([{"id": "C1", "type": "captions", "clips": [
            {"id": "caption7", "text": "hello", "timeline_start": 0.0, "timeline_duration": 1.0}]}])
        with self.assertRaises(NotImplementedError) as cm:
            build_osp(ir, Path("."))
        self.assertIn("caption7", str(cm.exception))

    def test_a_project_with_no_clips_anywhere_is_an_error(self):
        from project.compile_osp import build_osp
        with self.assertRaises(ValueError):
            build_osp(_ir([{"id": "V1", "type": "video", "clips": []}]), Path("."))


class TestAudioTrack(unittest.TestCase):
    """A voice on its own track, heard through OpenShot's own engine."""

    def setUp(self):
        if not NORMALIZED_MEDIA.exists():
            self.skipTest("media not present")
        if not _have_profiles():
            self.skipTest("OpenShot's profiles not found; is OpenShot installed?")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Two seconds of tone, standing in for a voiceover.
        self.voice = self.root / "voice.wav"
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=2", str(self.voice)], check=True)

    def project(self):
        video = _clip("clip1", NORMALIZED_MEDIA, 0.0, 0.0, 4.0)
        video["volume_db"] = -60.0
        voice = {"id": "clip1", "source": self.voice.as_posix(), "source_in": 0.0, "source_out": 2.0,
                 "timeline_start": 1.0, "timeline_duration": 2.0, "volume_db": -6.0}
        return _ir([{"id": "V1", "type": "video", "clips": [video]},
                    {"id": "Voice", "type": "audio", "clips": [voice]}])

    def test_an_audio_track_round_trips(self):
        from project.compile_osp import compile_file
        ir_path = self.root / "p.ir.json"
        ir_path.write_text(json.dumps(self.project()), encoding="utf-8")
        parsed = parse_osp(compile_file(ir_path, self.root / "p.osp"))
        self.assertEqual([(t["id"], t["type"]) for t in parsed["tracks"]], [("V1", "video"), ("Voice", "audio")])
        voice = parsed["tracks"][1]["clips"][0]
        self.assertEqual((voice["timeline_start"], voice["timeline_duration"]), (1.0, 2.0))
        self.assertAlmostEqual(voice["volume_db"], -6.0, places=4)
        osp = json.loads((self.root / "p.osp").read_text(encoding="utf-8"))
        self.assertEqual({f["media_type"] for f in osp["files"]}, {"video", "audio"})

    def test_openshots_engine_plays_the_voice(self):
        from project import openshot_build
        from project.compile_osp import compile_file
        if openshot_build.install_dir() is None:
            self.skipTest("OpenShot is not installed")
        ir_path = self.root / "p.ir.json"
        ir_path.write_text(json.dumps(self.project()), encoding="utf-8")
        osp = compile_file(ir_path, self.root / "p.osp")
        wav = self.root / "all.wav"
        result = openshot_build.run_script(REPO_ROOT / "project" / "openshot_render.py",
                                           str(osp), str(wav), cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        # The tone plays from 1s to 3s and nowhere else. The footage is turned down
        # to -60 dB so its own sound cannot pass for the tone.
        def tone(start):
            r = subprocess.run([_find_tool("ffmpeg"), "-nostats", "-ss", str(start), "-t", "0.8", "-i", str(wav),
                                "-af", "bandpass=f=440:width_type=q:w=30,volumedetect", "-f", "null", "-"],
                               capture_output=True, text=True)
            return float(r.stderr.split("max_volume:")[1].split("dB")[0])
        self.assertGreater(tone(1.5), -35)
        self.assertLess(tone(3.2), -60)


if __name__ == "__main__":
    unittest.main()
