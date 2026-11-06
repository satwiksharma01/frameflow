"""Graphics rendered by HyperFrames."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project import hyperframes
from project.media import _find_tool


def _project(width=1920, height=1080):
    return {"name": "p", "width": width, "height": height, "fps": 30.0, "source_frame_rate_mode": "cfr"}


class TestCard(unittest.TestCase):
    def test_text_is_escaped(self):
        page = hyperframes.card_html("<b>Tom & Jerry</b>", 1920, 1080, 30, 2)
        self.assertIn("&lt;b&gt;Tom &amp; Jerry&lt;/b&gt;", page)
        self.assertNotIn("<b>Tom", page)

    def test_the_card_takes_the_projects_size(self):
        page = hyperframes.card_html("Hi", 1080, 1920, 30, 2)
        self.assertIn('data-width="1080" data-height="1920"', page)

    def test_frame_rates_are_written_as_hyperframes_accepts_them(self):
        self.assertEqual(hyperframes._rate(30.0), "30")
        self.assertEqual(hyperframes._rate(29.97), "30000/1001")
        self.assertIn('data-fps="30"', hyperframes.card_html("Hi", 1920, 1080, 30.0, 2))

    def test_a_render_is_reused(self):
        clip = {"id": "clip1", "timeline_start": 0, "timeline_duration": 2.0,
                "generator": "hyperframes", "text": "Hello"}
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake_render(composition, out, fps):
                calls.append(composition)
                out.write_bytes(b"mov")
                return out

            with mock.patch.object(hyperframes, "render", fake_render):
                first = hyperframes.render_clip(clip, _project(), Path(tmp))
                second = hyperframes.render_clip(clip, _project(), Path(tmp))
                hyperframes.render_clip(dict(clip, text="Other"), _project(), Path(tmp))
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)

    def test_render_generated_gives_the_clip_its_file(self):
        ir = {"project": _project(), "tracks": [{"id": "Graphics", "type": "graphics", "clips": [
            {"id": "clip1", "timeline_start": 3.0, "timeline_duration": 2.0,
             "generator": "hyperframes", "text": "Hello"}]}]}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(hyperframes, "render", lambda c, out, fps: out):
            hyperframes.render_generated(ir, Path(tmp))
        clip = ir["tracks"][0]["clips"][0]
        self.assertTrue(clip["source"].endswith(".mov"))
        self.assertEqual((clip["source_in"], clip["source_out"]), (0.0, 2.0))


class TestOverlay(unittest.TestCase):
    def test_an_overlay_is_copied_with_the_videos_length_and_its_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "board"
            source.mkdir()
            (source / "index.html").write_text('<div id="root" data-composition-id="main" data-duration="1">'
                                               '<div class="clip" data-duration="5"></div></div>', encoding="utf-8")
            (source / "face.png").write_bytes(b"png")
            data = {"split": 0.6, "moments": {"turn": 8.7}}
            copy = hyperframes.overlay(source, Path(tmp), 21.6, data)
            page = (copy / "index.html").read_text(encoding="utf-8")
            self.assertEqual(page.count('data-duration="21.6"'), 2)      # every layer lasts the whole video
            self.assertEqual((copy / "face.png").read_bytes(), b"png")    # its own files go with it
            script = (copy / "frameflow.js").read_text(encoding="utf-8")
            self.assertEqual(json.loads(script.removeprefix("window.FRAMEFLOW = ").rstrip().removesuffix(";")),
                             {"duration": 21.6, "split": 0.6, "moments": {"turn": 8.7}})
            self.assertEqual(hyperframes.overlay(source, Path(tmp), 21.6, data), copy)    # made once
            self.assertNotEqual(hyperframes.overlay(source, Path(tmp), 20.0, data), copy)


class TestBrandKit(unittest.TestCase):
    def kit(self, folder: Path, **fields):
        (folder / "brand.json").write_text(json.dumps(fields), encoding="utf-8")
        return mock.patch.object(hyperframes, "BRAND_FILE", folder / "brand.json")

    def test_without_a_kit_cards_keep_frameflows_look(self):
        with mock.patch.object(hyperframes, "BRAND_FILE", Path("no/such/brand.json")):
            self.assertEqual(hyperframes.brand(), hyperframes.BRAND)
        page = hyperframes.card_html("Hi", 1920, 1080, 30, 2, "title")
        self.assertIn("background:rgba(16,24,39,.78)", page)
        self.assertIn("background:transparent", page)
        self.assertNotIn("<img", page)

    def test_a_kit_restyles_the_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Brand-Bold.ttf").write_bytes(b"font")
            (folder / "logo.png").write_bytes(b"png")
            with self.kit(folder, font="Brand-Bold.ttf", text="#111111", background="#F4E9DA", logo="logo.png"):
                kit = hyperframes.brand()
        title = hyperframes.card_html("Spring drop", 1080, 1920, 30, 2, "title", kit)
        lower = hyperframes.card_html("Spring drop", 1080, 1920, 30, 2, "lower", kit)
        self.assertIn('src:url("brand-font.ttf")', title)
        self.assertIn('font-family:"Brand",', title)
        self.assertIn("color:#111111", title)
        # The title screen in the brand's colour: on the composition, since HyperFrames drops the page's own.
        self.assertIn("#root{width:1080px;height:1920px;position:relative;background:#F4E9DA}", title)
        self.assertIn('src="brand-logo.png"', title)
        self.assertIn("background:transparent", lower)            # a card over footage stays see-through
        self.assertIn("background:#F4E9DAC7", lower)              # on a plate of the brand's colour
        self.assertNotIn("<img", lower)

    def test_an_installed_font_is_used_by_name(self):
        page = hyperframes.card_html("Hi", 1920, 1080, 30, 2, "lower", dict(hyperframes.BRAND, font="Georgia"))
        self.assertIn('font-family:"Georgia",Arial', page)
        self.assertNotIn("@font-face", page)

    def test_the_kits_files_go_beside_the_card(self):
        clip = {"id": "clip1", "timeline_start": 0, "timeline_duration": 2.0, "generator": "hyperframes",
                "text": "Hello", "generator_params": {"layout": "title"}}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "Brand.OTF").write_bytes(b"font")
            (folder / "logo.svg").write_bytes(b"<svg/>")
            seen = []

            def fake_render(composition, out, fps):
                seen.extend(sorted(p.name for p in composition.iterdir()))
                return out

            with self.kit(folder, font="Brand.OTF", logo="logo.svg"),                     mock.patch.object(hyperframes, "render", fake_render):
                hyperframes.render_clip(clip, _project(), folder / "video")
        self.assertEqual(seen, ["brand-font.otf", "brand-logo.svg", "index.html"])

    def test_a_kit_that_needs_fixing_says_where(self):
        for fields, expected in [({"text": "white"}, "does not match"),
                                 ({"colour": "#FFFFFF"}, "colour"),
                                 ({"font": 'Arial"}body{color:red'}, "does not match"),
                                 ({"font": "missing.ttf"}, "missing.ttf"),
                                 ({"logo": "missing.png"}, "missing.png")]:
            with self.subTest(fields=fields), tempfile.TemporaryDirectory() as tmp, self.kit(Path(tmp), **fields):
                with self.assertRaises(hyperframes.HyperFramesError) as cm:
                    hyperframes.brand()
                self.assertIn("brand", str(cm.exception))
                self.assertIn(expected, str(cm.exception))


class TestProductCardsAndLowerThirds(unittest.TestCase):
    def test_a_product_card_shows_its_name_a_line_and_the_price_as_a_tag(self):
        page = hyperframes.card_html("Nomad jacket", 1080, 1920, 30, 3, "product",
                                     subtitle="Packs into its own pocket", price="₹4,990")
        self.assertIn('Nomad jacket<div class="sub">Packs into its own pocket</div><div class="price">₹4,990</div>',
                      page)
        self.assertIn(".price{display:inline-block;", page)
        self.assertIn("background:#FFE14D;color:#000000}", page)      # the accent, with text that reads on it
        # At the left, its bottom edge above where the spoken captions' line sits (68% down a reel).
        self.assertIn("left:65px;bottom:749px;", page)
        self.assertIn("text-align:left", page)

    def test_a_lower_third_has_an_accent_bar_and_never_a_price(self):
        page = hyperframes.card_html("Satwik Sharma", 1920, 1080, 30, 3, "lower_third",
                                     subtitle="Founder, Frameflow", price="₹4,990")
        self.assertIn('Satwik Sharma<div class="sub">Founder, Frameflow</div></div>', page)
        self.assertIn("border-left:", page)
        self.assertIn("solid #FFE14D", page)
        self.assertNotIn('class="price"', page)
        self.assertIn("left:115px;bottom:281px;", page)             # above the captions at 84% down

    def test_the_kits_accent_marks_the_price_and_the_bar(self):
        kit = dict(hyperframes.BRAND, accent="#1A1A2E", background="#F4E9DA")
        page = hyperframes.card_html("Nomad", 1080, 1920, 30, 3, "product", kit, price="$129")
        self.assertIn("background:#1A1A2E;color:#FFFFFF}", page)     # a dark accent gets light text
        self.assertIn("background:#F4E9DAC7", page)

    def test_a_cards_lines_reach_the_render(self):
        clip = {"id": "clip1", "timeline_start": 0, "timeline_duration": 3.0, "generator": "hyperframes",
                "text": "Nomad jacket", "generator_params": {"layout": "product", "price": "$129"}}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(hyperframes, "BRAND_FILE", Path("no/such/brand.json")), \
                mock.patch.object(hyperframes, "render", lambda c, out, fps: out):
            hyperframes.render_clip(clip, _project(1080, 1920), Path(tmp))
            page = next(Path(tmp).rglob("index.html")).read_text(encoding="utf-8")
        self.assertIn('<div class="price">$129</div>', page)


class TestRealRender(unittest.TestCase):
    def test_a_card_renders_with_a_transparent_background(self):
        if shutil.which("npx") is None:
            self.skipTest("Node.js is not installed")
        clip = {"id": "clip1", "timeline_start": 0, "timeline_duration": 1.0, "text": "Hello"}
        with tempfile.TemporaryDirectory() as tmp:
            mov = hyperframes.render_clip(clip, _project(640, 360), Path(tmp))
            probe = subprocess.run([_find_tool("ffprobe"), "-v", "error", "-show_entries",
                                    "stream=pix_fmt,width,height", "-of", "csv=p=0", str(mov)],
                                   capture_output=True, text=True)
            corner = subprocess.run([_find_tool("ffmpeg"), "-v", "error", "-ss", "0.5", "-i", str(mov),
                                     "-frames:v", "1", "-vf", "alphaextract,crop=40:40:0:0",
                                     "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
        self.assertEqual(probe.stdout.strip(), "640,360,yuva444p12le")
        self.assertEqual(max(corner.stdout), 0)          # nothing drawn in the corner


if __name__ == "__main__":
    unittest.main()
