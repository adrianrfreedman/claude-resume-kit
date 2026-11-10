#!/usr/bin/env python3
"""
Render a JavaScript-heavy page with headless Chrome and print a cleaned
text view + link list to stdout. Used by /scan-jobs for careers pages
that aren't usable via WebFetch.

Usage:
    render.py <url>

Output to stdout (UTF-8):
    === TITLE ===
    <document title>
    === LINKS ===
    <one per line: "<absolute_href>\t<anchor text up to 200 chars>">
    === TEXT ===
    <visible text content, multiple blank lines collapsed>

Exit codes:
    0  ok
    1  chrome binary not found
    2  chrome execution failed / timed out
    3  empty render (got <1KB of HTML — likely Cloudflare or auth wall)
    4  bad usage
"""

from __future__ import annotations

import html
import html.parser
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TIMEOUT_SEC = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)

# Tags whose inner text we never want to surface.
_DROP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe"}


class _DomExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        self.text_parts: list[str] = []
        # (href, anchor_text) pairs collected in document order.
        self.links: list[tuple[str, str]] = []
        # Stack of currently-open tag names; used to skip text inside drop-tags.
        self._tag_stack: list[str] = []
        # Currently-open anchor's href and its text accumulator.
        self._open_anchor_href: str | None = None
        self._open_anchor_text: list[str] = []
        # Are we inside a <title> tag?
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self._tag_stack.append(tag)
        if tag == "title":
            self._in_title = True
        elif tag == "a":
            attr = dict(attrs)
            self._open_anchor_href = attr.get("href")
            self._open_anchor_text = []
        elif tag == "br":
            self.text_parts.append("\n")
        # Block-level tags push a newline so visible text doesn't run together.
        elif tag in {
            "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
            "section", "article", "header", "footer", "main",
        }:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        if tag == "title":
            self._in_title = False
        elif tag == "a":
            if self._open_anchor_href:
                anchor_text = " ".join("".join(self._open_anchor_text).split())[:200]
                self.links.append((self._open_anchor_href, anchor_text))
            self._open_anchor_href = None
            self._open_anchor_text = []

    def handle_data(self, data):
        if any(t in _DROP_TAGS for t in self._tag_stack):
            return
        if self._in_title:
            self.title += data
        if self._open_anchor_href is not None:
            self._open_anchor_text.append(data)
        self.text_parts.append(data)


def _run_chrome(url: str) -> str:
    if not Path(CHROME).exists():
        sys.stderr.write(f"chrome not found at {CHROME}\n")
        sys.exit(1)
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-pdf-header-footer",
        f"--user-agent={USER_AGENT}",
        "--virtual-time-budget=8000",
        "--dump-dom",
        url,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"chrome timed out after {TIMEOUT_SEC}s\n")
        sys.exit(2)
    if result.returncode != 0:
        sys.stderr.write(
            f"chrome exited {result.returncode}\n"
            f"stderr: {result.stderr[:500]}\n"
        )
        sys.exit(2)
    return result.stdout


def _collapse_blank_lines(text: str) -> str:
    # Strip trailing spaces per line, collapse 3+ newlines to 2.
    lines = [ln.rstrip() for ln in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 4
    url = argv[1]

    rendered = _run_chrome(url)
    if len(rendered) < 1024:
        sys.stderr.write(
            f"empty render ({len(rendered)} bytes) — likely blocked or no body\n"
        )
        return 3

    parser = _DomExtractor()
    try:
        parser.feed(rendered)
    except Exception as exc:  # pragma: no cover — html.parser is permissive
        sys.stderr.write(f"parse error: {exc}\n")
        return 2

    text = _collapse_blank_lines("".join(parser.text_parts))

    # Resolve relative hrefs against the page URL.
    base = url
    abs_links: list[tuple[str, str]] = []
    seen_hrefs: set[str] = set()
    for href, anchor in parser.links:
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        absu = urljoin(base, href)
        if absu in seen_hrefs:
            continue
        seen_hrefs.add(absu)
        abs_links.append((absu, anchor))

    out: list[str] = []
    out.append("=== TITLE ===")
    out.append(parser.title.strip() or "(no title)")
    out.append("=== LINKS ===")
    for href, anchor in abs_links:
        out.append(f"{href}\t{anchor}")
    out.append("=== TEXT ===")
    out.append(text)

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
