"""Generated pictures and clips: one interface, a cap before anything paid, ordinary clips after."""
import base64
import http.server
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from project import generate, produce
from project.media import _find_tool, analyze, probe
from project.validate import ValidationError, validate

BRIEF = {"title": "Nomad reel", "format": "product reel", "aspect": "9:16", "target_seconds": 15,
         "audience": "travellers", "tone": "upbeat", "summary": "A launch reel."}


def _board(*visuals: dict) -> dict:
    return {"script": "A jacket.", "scenes": [{"visual": v, "duration": 2.0, "reason": "r"} for v in visuals]}


def _picture(prompt: str) -> dict:
    return {"type": "generated", "kind": "picture", "prompt": prompt}


def _generator(**env: str):
    """The environment with only these generator settings, the rest of it as it is."""
    patch = mock.patch.dict(os.environ)
    patch.start()
    for name in ("FRAMEFLOW_GENERATOR", "GEMINI_API_KEY"):
        os.environ.pop(name, None)
    os.environ.update(env)
    return patch


class Priced:
    """A paid generator that makes free stand-in files, counting what it is asked for."""
    name, prices = "priced", {"picture": 0.05, "clip": 1.0}

    def __init__(self):
        self.made = []

    def make(self, kind, prompt, aspect, out):
        self.made.append(prompt)
        return generate.StandIn().make(kind, prompt, aspect, out)


class TestTheCap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.inputs = {"prompt": "p", "script": None, "footage": [], "assets": [], "music": []}
        self.board = _board(_picture("a jacket on a mountain"), _picture("a jacket in the rain"))

    def test_nothing_paid_runs_above_the_cap(self):
        maker = Priced()
        with self.assertRaises(generate.GenerateError) as cm:
            generate.make_all(self.folder, self.board, self.inputs, "9:16", 0.0, maker)
        self.assertEqual(maker.made, [])
        for said in ("$0.05", "a jacket in the rain", "about $0.10", "cap of $0.00", "--budget 0.10"):
            self.assertIn(said, str(cm.exception))

    def test_within_the_cap_each_becomes_an_ordinary_asset(self):
        board, inputs, spent = generate.make_all(self.folder, self.board, self.inputs, "9:16", 0.10, Priced())
        self.assertAlmostEqual(spent, 0.10)
        paths = [scene["visual"]["path"] for scene in board["scenes"]]
        self.assertEqual([scene["visual"]["type"] for scene in board["scenes"]], ["asset", "asset"])
        self.assertEqual([(a["path"], a["kind"]) for a in inputs["assets"]], [(p, "image") for p in paths])
        self.assertTrue(all(Path(p).is_file() for p in paths))
        self.assertEqual(self.board["scenes"][0]["visual"]["type"], "generated")      # the storyboard is left as written

    def test_what_was_made_is_kept_so_a_rebuild_costs_nothing(self):
        generate.make_all(self.folder, self.board, self.inputs, "9:16", 0.10, Priced())
        again = Priced()
        _, _, spent = generate.make_all(self.folder, self.board, self.inputs, "9:16", 0.0, again)
        self.assertEqual((again.made, spent), ([], 0.0))

    def test_the_stand_in_is_free(self):
        _, _, spent = generate.make_all(self.folder, self.board, self.inputs, "9:16", 0.0, generate.StandIn())
        self.assertEqual(spent, 0.0)

    def test_without_a_generator_a_generated_scene_is_refused(self):
        self.addCleanup(_generator().stop)
        with self.assertRaises(generate.GenerateError) as cm:
            generate.make_all(self.folder, self.board, self.inputs, "9:16", 0.0)
        self.assertIn("GEMINI_API_KEY", str(cm.exception))


class TestTheStandIn(unittest.TestCase):
    def test_a_picture_and_a_clip_the_size_of_the_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            picture = generate.StandIn().make("picture", "a jacket", "9:16", Path(tmp) / "p")
            clip = generate.StandIn().make("clip", "a jacket", "16:9", Path(tmp) / "c")
            self.assertEqual((picture.suffix, clip.suffix), (".png", ".mp4"))
            shown, moving = probe(picture)["streams"][0], analyze(clip)
        self.assertEqual((shown["width"], shown["height"]), (1080, 1920))
        self.assertEqual((moving.width, moving.height), (1920, 1080))
        self.assertAlmostEqual(moving.duration_seconds, generate.CLIP_SECONDS, delta=0.1)


class Google(http.server.BaseHTTPRequestHandler):
    """Answers as the Gemini Interactions API does, keeping each request it is sent."""
    requests, reply = [], None

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Google.requests.append((self.path, self.headers.get("x-goog-api-key"), body))
        status, answer = Google.reply
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(answer).encode())

    def log_message(self, *args):
        pass


class TestGemini(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Google)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.png, cls.mp4 = Path(cls.tmp.name) / "made.png", Path(cls.tmp.name) / "made.mp4"
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64",
                        "-frames:v", "1", str(cls.png)], check=True)
        subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1",
                        "-pix_fmt", "yuv420p", str(cls.mp4)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        Google.requests.clear()
        patch = mock.patch.object(generate, "API", f"http://127.0.0.1:{self.server.server_port}/v1beta/interactions")
        patch.start()
        self.addCleanup(patch.stop)

    def made(self, kind: str, data: Path, mime: str):
        Google.reply = (200, {"id": "v1_1", "status": "completed", "object": "interaction", "steps": [
            {"type": "user_input", "content": [{"type": "text", "text": "..."}]},
            {"type": "model_output", "content": [{"type": "text", "text": "Here it is."},
                                                  {"type": kind, "mime_type": mime,
                                                   "data": base64.b64encode(data.read_bytes()).decode()}]}]})

    def test_a_picture_is_asked_for_in_the_video_s_shape_and_saved(self):
        self.made("image", self.png, "image/png")
        with tempfile.TemporaryDirectory() as tmp:
            out = generate.Gemini("test-key").make("picture", "a jacket on a mountain", "9:16", Path(tmp) / "p")
            self.assertEqual(out.read_bytes(), self.png.read_bytes())
        path, key, body = Google.requests[0]
        self.assertEqual((path, key, out.suffix), ("/v1beta/interactions", "test-key", ".png"))
        self.assertEqual(body, {"model": generate.Gemini.MODELS["picture"], "input": "a jacket on a mountain",
                                "store": False,
                                "response_format": {"type": "image", "aspect_ratio": "9:16", "image_size": "2K"}})

    def test_a_clip_is_one_shot_without_dialogue_in_a_shape_it_can_make(self):
        self.made("video", self.mp4, "video/mp4")
        with tempfile.TemporaryDirectory() as tmp:
            out = generate.Gemini("test-key").make("clip", "a jacket in the rain.", "1:1", Path(tmp) / "c")
            self.assertEqual(out.suffix, ".mp4")
        body = Google.requests[0][2]
        self.assertEqual(body["model"], generate.Gemini.MODELS["clip"])
        self.assertEqual(body["input"], "a jacket in the rain. In a single continuous shot. No dialogue.")
        self.assertEqual(body["response_format"], {"type": "video", "aspect_ratio": "16:9"})

    def test_a_refusal_says_what_google_said(self):
        Google.reply = (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                        "message": "This model is not available on the free tier."}})
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(generate.GenerateError) as cm:
            generate.Gemini("test-key").make("picture", "a jacket", "9:16", Path(tmp) / "p")
        self.assertIn("This model is not available on the free tier.", str(cm.exception))


class TestInAVideoFromAPrompt(unittest.TestCase):
    def test_a_generated_visual_is_part_of_the_storyboard(self):
        validate(_board(_picture("a jacket"), {"type": "generated", "kind": "clip", "prompt": "rain"}), "storyboard")
        with self.assertRaises(ValidationError):
            validate(_board({"type": "generated", "kind": "song", "prompt": "a jacket"}), "storyboard")

    def test_a_generated_picture_needs_a_duration_or_narration(self):
        board = {"script": "s", "scenes": [{"visual": _picture("a jacket"), "reason": "r"}]}
        problems = produce.check_storyboard(board, {"footage": [], "assets": [], "music": []})
        self.assertEqual(problems, ["scene 1 (generated): give it a duration, or narration to set one"])

    def test_a_stand_in_picture_lands_on_the_main_track_as_an_image_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            board, inputs, _ = generate.make_all(folder, _board(_picture("a jacket")), {
                "prompt": "p", "script": None, "footage": [], "assets": [], "music": []}, "9:16", 0.0,
                generate.StandIn())
            ir = produce.build_ir(folder, board, BRIEF, inputs)
        clip = ir["tracks"][0]["clips"][0]
        self.assertEqual((clip["timeline_start"], clip["timeline_duration"]), (0.0, 2.0))
        self.assertTrue(clip["source"].endswith(".mp4"))        # pushed in, as every image is

    def test_the_storyboard_request_says_what_generating_costs_or_that_it_cannot(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / produce.INPUTS_FILE).write_text('{"prompt": "p", "script": null, "footage": [], '
                                                      '"assets": [], "music": []}', encoding="utf-8")
            (folder / produce.BRIEF_FILE).write_text(json.dumps(BRIEF), encoding="utf-8")
            patch = _generator(GEMINI_API_KEY="k")
            priced = produce.storyboard_request(folder).read_text(encoding="utf-8")
            patch.stop()
            patch = _generator()
            none = produce.storyboard_request(folder).read_text(encoding="utf-8")
            patch.stop()
        self.assertIn("about $0.05 a picture and $1.01 a clip", priced)
        self.assertIn("no generator is set up, so leave `generated` visuals out", none)


if __name__ == "__main__":
    unittest.main()
