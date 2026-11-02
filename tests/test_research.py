"""Facts with sources: every quote looked for on its page before the creator confirms the brief."""
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from project import produce, research
from project.validate import ValidationError, validate

FILLER = "<p>Elsewhere on the page, other news about other things entirely.</p>" * 30
PAGE = ("<html><head><title>Report</title><style>p { color: red }</style>"
        "<script>var claim = 'the creator economy is worth $1 trillion';</script></head>"
        "<body><p>Goldman Sachs Research expects the creator economy could approach "
        "<b>$480&nbsp;billion</b> by 2027.</p><p>The creator\u2019s share \u2014 growing.</p>"
        + FILLER + "</body></html>")
FACT = {"claim": "The creator economy could reach $480 billion by 2027", "source": "Goldman Sachs",
        "url": "https://example.com/report", "quote": "the creator economy could approach $480 billion by 2027"}
BRIEF = {"title": "Frameflow pitch", "format": "startup pitch", "aspect": "16:9", "target_seconds": 60,
         "audience": "investors", "tone": "confident", "summary": "Why creators need Frameflow."}


def _reader(pages: dict):
    def read(url):
        page = pages[url]
        if isinstance(page, Exception):
            raise page
        return page
    return read


class TestThePageText(unittest.TestCase):
    def test_scripts_and_styles_are_not_part_of_the_text(self):
        with mock.patch.object(research, "_fetch", lambda url: ("text/html", "utf-8", PAGE.encode())):
            text = " ".join(research.words(research.read("https://example.com/report")))
        self.assertIn("could approach 480 billion by 2027", text)
        self.assertNotIn("1 trillion", text)
        self.assertNotIn("color", text)

    def test_words_ignore_case_spacing_quotes_and_dashes(self):
        self.assertEqual(research.words("The Creator\u2019s  share \u2014 growing"),
                         research.words("the creator's share - growing"))


class TestCheckingFacts(unittest.TestCase):
    def check(self, fact, page=PAGE):
        page = page if isinstance(page, Exception) else research._text(page)
        return research.check([fact], _reader({fact["url"]: page}))

    def test_a_quote_on_its_page_is_confirmed(self):
        problems, lines = self.check(FACT)
        self.assertEqual(problems, [])
        self.assertEqual(lines, ["fact 1: the quote is on https://example.com/report"])

    def test_a_quote_the_page_does_not_have_must_be_fixed(self):
        problems, _ = self.check(dict(FACT, quote="the creator economy could approach $500 billion by 2027"))
        self.assertEqual(len(problems), 1)
        self.assertIn("fact 1 (The creator economy could reach $480 billion by 2027): the quote is not on "
                      "https://example.com/report", problems[0])

    def test_a_quote_must_be_a_whole_phrase(self):
        problems, _ = self.check(dict(FACT, quote="$480 billion"))
        self.assertIn("at least 4 words", problems[0])

    def test_a_page_that_cannot_be_read_is_left_for_the_creator(self):
        problems, lines = self.check(FACT, research.ReadError("it is a PDF, which Frameflow cannot read yet"))
        self.assertEqual(problems, [])
        self.assertEqual(lines, ["fact 1: not checked, it is a PDF, which Frameflow cannot read yet: "
                                 "open https://example.com/report yourself"])

    def test_a_source_page_that_is_not_there_must_be_fixed(self):
        problems, lines = self.check(FACT, research.Gone("the site answered 404: there is no such page"))
        self.assertEqual(lines, [])
        self.assertIn("fact 1 (The creator economy could reach $480 billion by 2027): the site answered 404: "
                      "there is no such page at https://example.com/report", problems[0])

    def test_a_page_built_in_the_browser_is_left_for_the_creator_too(self):
        problems, lines = self.check(dict(FACT, quote="the creator economy could approach $1 trillion"),
                                     "<html><body><div id='app'>Loading the report</div></body></html>")
        self.assertEqual(problems, [])
        self.assertIn("not checked, the page shows only 3 words without a browser", lines[0])


class Pages(http.server.BaseHTTPRequestHandler):
    """A report, a PDF, a page in Latin-1, and nothing else."""
    def do_GET(self):
        pages = {"/report": ("text/html; charset=utf-8", PAGE.encode()),
                 "/report.pdf": ("application/pdf", b"%PDF-1.7"),
                 "/latin": ("text/html; charset=iso-8859-1", "<p>Caf\xe9 owners say so.</p>".encode("latin-1"))}
        if self.path not in pages:
            self.send_error(404)
            return
        kind, body = pages[self.path]
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestReadingPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Pages)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.site = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_a_page_is_read_as_text(self):
        self.assertIn("could approach 480 billion by 2027",
                      " ".join(research.words(research.read(f"{self.site}/report"))))

    def test_its_own_character_set_is_used(self):
        self.assertIn("Caf\xe9 owners", research.read(f"{self.site}/latin"))

    def test_a_pdf_is_not_read(self):
        with self.assertRaises(research.ReadError) as cm:
            research.read(f"{self.site}/report.pdf")
        self.assertIn("PDF", str(cm.exception))

    def test_a_page_that_is_not_there_is_gone_not_unreadable(self):
        with self.assertRaises(research.Gone) as cm:
            research.read(f"{self.site}/gone")
        self.assertIn("404", str(cm.exception))


class TestTheBrief(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(research, "read", lambda url: research._text(PAGE))
        patch.start()
        self.addCleanup(patch.stop)

    def folder(self, tmp: str, brief: dict) -> Path:
        folder = Path(tmp)
        (folder / produce.INPUTS_FILE).write_text('{"prompt": "p", "script": null, "footage": [], '
                                                  '"assets": [], "music": []}', encoding="utf-8")
        (folder / produce.BRIEF_FILE).write_text(json.dumps(brief), encoding="utf-8")
        return folder

    def test_a_fact_needs_a_web_page(self):
        with self.assertRaises(ValidationError):
            validate(dict(BRIEF, facts=[dict(FACT, url="file:///C:/notes.txt")]), "brief")

    def test_checking_the_brief_reports_each_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = produce.check_brief(self.folder(tmp, dict(BRIEF, facts=[FACT])))
        self.assertEqual(lines, ["fact 1: the quote is on https://example.com/report"])

    def test_a_misquote_stops_the_brief_and_the_storyboard(self):
        brief = dict(BRIEF, facts=[dict(FACT, quote="the creator economy could approach $500 billion by 2027")])
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.folder(tmp, brief)
            for stage in (produce.check_brief, produce.storyboard_request):
                with self.assertRaises(produce.ProduceError) as cm:
                    stage(folder)
                self.assertIn("the quote is not on https://example.com/report", str(cm.exception))

    def test_the_storyboard_is_told_to_name_the_source_in_the_narration(self):
        with tempfile.TemporaryDirectory() as tmp:
            sourced = produce.storyboard_request(self.folder(tmp, dict(BRIEF, facts=[FACT]))).read_text(encoding="utf-8")
            plain = produce.storyboard_request(self.folder(tmp, BRIEF)).read_text(encoding="utf-8")
        self.assertIn("the narration names its source", sourced)
        self.assertNotIn("the narration names its source", plain)

    def test_the_brief_request_asks_for_research_and_the_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = produce.prepare(Path(tmp), "A pitch for my app", None, [], [], []).read_text(encoding="utf-8")
        self.assertIn("research them with your web tools", request)
        self.assertIn("--brief", request)


if __name__ == "__main__":
    unittest.main()
