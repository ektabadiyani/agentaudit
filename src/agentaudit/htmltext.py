"""Convert help-centre article HTML into readable Markdown-ish text for the grader."""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

BLOCK = {"p", "div", "section", "article", "table", "tr", "br", "hr", "pre", "blockquote"}
HEADINGS = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}
SKIP = {"script", "style", "noscript"}


class _Converter(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.lists: list[list] = []   # stack of [tag, counter]
        self.skipping = 0
        self.href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skipping += 1
        elif tag in HEADINGS:
            self.parts.append("\n\n" + HEADINGS[tag])
        elif tag in ("ul", "ol"):
            self.lists.append([tag, 0])
        elif tag == "li":
            indent = "  " * max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.parts.append(f"\n{indent}{self.lists[-1][1]}. ")
            else:
                self.parts.append(f"\n{indent}- ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in BLOCK:
            self.parts.append("\n\n" if tag != "br" else "\n")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag == "a":
            self.href = dict(attrs).get("href")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self.parts.append(f"[image: {alt}]")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in HEADINGS or tag in BLOCK:
            self.parts.append("\n\n")
        elif tag in ("ul", "ol"):
            if self.lists:
                self.lists.pop()
            self.parts.append("\n")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag == "a":
            # Keep the destination of links that aren't just repeated text, e.g. a status page URL.
            if self.href and self.href.startswith("http"):
                self.parts.append(f" ({self.href})")
            self.href = None

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    if not html:
        return ""
    converter = _Converter()
    converter.feed(html)
    converter.close()
    text = unescape("".join(converter.parts))
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+(?=[^-\d ])", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\*\*\s*\*\*", "", text)
    return text.strip()
