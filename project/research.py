#!/usr/bin/env python3
"""Facts with sources, for pitches.

When a video will state facts about the world - a market's size, a price, who
did what - the agent researches each one and puts it in the brief: the claim,
who says it, the page, and the exact words on that page that support it.
Before the creator confirms the brief, Frameflow opens every page and looks
for those words, so a misquote or a made-up page is caught rather than
narrated. A page it cannot read - a PDF, a site that turns it away, one built
by scripts in a browser - is left for the creator to open themselves.
"""
import html.parser
import http.client
import re
import unicodedata
import urllib.error
import urllib.request

TIMEOUT = 20
MIN_QUOTE_WORDS = 4
# Fewer words than this without a browser, and the page is likely built by scripts: the quote may be there unseen.
MIN_PAGE_WORDS = 150
USER_AGENT = "Mozilla/5.0 (compatible; Frameflow fact check)"
_UNSEEN = ("script", "style", "noscript", "template")


class ReadError(Exception):
    pass


class Gone(Exception):
    """The page is not there: an address made up, or one that has moved."""


class _Text(html.parser.HTMLParser):
    """A page's text, less its scripts and styles; every tag a word break."""

    def __init__(self):
        super().__init__()
        self.parts, self.unseen = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in _UNSEEN:
            self.unseen += 1
        self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in _UNSEEN and self.unseen:
            self.unseen -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.unseen:
            self.parts.append(data)


def _text(page: str) -> str:
    parser = _Text()
    parser.feed(page)
    parser.close()
    return "".join(parser.parts)


def words(text: str) -> list[str]:
    """Text as lower-case words and numbers, whatever its quotes, dashes and spacing."""
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).lower())


def _fetch(url: str) -> tuple[str, str, bytes]:
    """(content type, character set, body) of a web page."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return (response.headers.get_content_type(), response.headers.get_content_charset() or "utf-8",
                    response.read(20_000_000))
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            raise Gone(f"the site answered {e.code}: there is no such page") from e
        raise ReadError(f"the site answered {e.code}") from e
    except (OSError, http.client.HTTPException, ValueError) as e:     # URLError and timeouts are OSErrors
        raise ReadError(f"it could not be reached ({getattr(e, 'reason', e)})") from e


def read(url: str) -> str:
    """The text of a web page, or ReadError saying why it cannot be read."""
    kind, charset, body = _fetch(url)
    if kind == "application/pdf":
        raise ReadError("it is a PDF, which Frameflow cannot read yet")
    if kind not in ("text/html", "application/xhtml+xml", "text/plain"):
        raise ReadError(f"it is {kind}, not a web page")
    try:
        page = body.decode(charset, errors="replace")
    except LookupError:                     # a character set Python does not know
        page = body.decode("utf-8", errors="replace")
    return page if kind == "text/plain" else _text(page)


def check(facts: list[dict], reader=None) -> tuple[list[str], list[str]]:
    """(what the agent must fix, a line for the creator on each fact that passed). Each fact's quote is
    looked for on its page, word for word."""
    reader = reader or read
    problems, lines = [], []
    for n, fact in enumerate(facts, start=1):
        label = f"fact {n} ({fact['claim']})"
        quote = words(fact["quote"])
        if len(quote) < MIN_QUOTE_WORDS:
            problems.append(f"{label}: quote a whole phrase from the page, at least {MIN_QUOTE_WORDS} words")
            continue
        try:
            page = words(reader(fact["url"]))
        except Gone as e:
            problems.append(f"{label}: {e} at {fact['url']}; find the page that says it")
            continue
        except ReadError as e:
            lines.append(f"fact {n}: not checked, {e}: open {fact['url']} yourself")
            continue
        if f" {' '.join(quote)} " in f" {' '.join(page)} ":
            lines.append(f"fact {n}: the quote is on {fact['url']}")
        elif len(page) < MIN_PAGE_WORDS:
            lines.append(f"fact {n}: not checked, the page shows only {len(page)} words without a browser: "
                         f"open {fact['url']} yourself")
        else:
            problems.append(f"{label}: the quote is not on {fact['url']}; copy the words as the page has them, "
                            f"or find a source that says it")
    return problems, lines
