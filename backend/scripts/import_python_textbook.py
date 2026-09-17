"""Import the pilot's complete selected sections; never fetch on a learner request.

Only Python's official documentation host is used. The resulting snapshot carries
its original anchors, text hashes, source version and full PSF license notice.
Run from the repository root with backend/.venv/Scripts/python.exe.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen

BASE = "https://docs.python.org/zh-cn/3.14/"
SECTIONS = {
    "introduction": {"numbers": ["py_values"], "text": ["py_values"], "lists": ["py_loops"],
                     "first-steps-towards-programming": ["py_values", "py_branches", "py_loops"]},
    "controlflow": {"if-statements": ["py_branches"], "for-statements": ["py_loops"],
                    "the-range-function": ["py_loops"], "defining-functions": ["py_functions"],
                    "default-argument-values": ["py_functions"]},
    "datastructures": {"more-on-conditions": ["py_branches"]},
}


class Sections(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.parts = {}
        self.titles = {}
        self.heading = 0
        self.pre = False
        self.skip = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            anchor = attrs.get("id", "")
            self.stack.append(anchor)
            self.parts.setdefault(anchor, [])
        if tag in ("h1", "h2", "h3", "h4", "h5"):
            self.heading += 1
        if tag == "a" and attrs.get("class") == "headerlink":
            self.skip = True
        if tag == "pre":
            self.pre = True
            self.add("\n\n```python\n")
        elif tag in ("p", "li", "dt", "dd"):
            self.add("\n\n")

    def handle_endtag(self, tag):
        if tag == "a":
            self.skip = False
        if tag in ("h1", "h2", "h3", "h4", "h5"):
            self.heading = max(0, self.heading - 1)
            self.add("\n\n")
        if tag == "pre":
            self.add("\n```\n\n")
            self.pre = False
        if tag == "section" and self.stack:
            self.stack.pop()

    def add(self, text):
        for anchor in self.stack:
            self.parts[anchor].append(text)

    def handle_data(self, text):
        if self.skip:
            return
        if self.heading and self.stack:
            self.titles[self.stack[-1]] = self.titles.get(self.stack[-1], "") + text
        self.add(text if self.pre else re.sub(r"\s+", " ", text))


def main():
    target = Path(__file__).resolve().parents[1] / "app/data/textbooks"
    target.mkdir(parents=True, exist_ok=True)
    sections = []
    version = ""
    for document, anchors in SECTIONS.items():
        url = f"{BASE}tutorial/{document}.html"
        html = urlopen(url, timeout=30).read().decode("utf-8")
        match = re.search(r"Python (3\.14\.\d+)", html)
        if not match or (version and version != match[1]):
            raise ValueError("Cannot pin a consistent Python documentation version")
        version = match[1]
        parser = Sections()
        parser.feed(html)
        for anchor, kps in anchors.items():
            text = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "".join(parser.parts[anchor])).strip()
            if len(text) < 100:
                raise ValueError(f"Missing section: {anchor}")
            sections.append({"id": anchor, "title": parser.titles[anchor].strip(), "text": text,
                             "url": url + "#" + anchor, "kps": kps,
                             "sha256": hashlib.sha256(text.encode()).hexdigest()})
    license_html = urlopen(BASE + "license.html", timeout=30).read().decode("utf-8")
    parser = Sections()
    parser.feed(license_html)
    notice = "\n\n".join("".join(parser.parts[key]).strip() for key in (
        "python-software-foundation-license-version-2", "zero-clause-bsd-license-for-code-in-the-python-documentation"))
    if "PSF" not in notice or len(notice) < 1000:
        raise ValueError("PSF license notice missing")
    (target / "PYTHON-LICENSE.txt").write_text(notice + "\n", encoding="utf-8")
    snapshot = {"id": "python-tutorial-3.14", "title": "Python 官方教程", "version": version,
                "url": BASE + "tutorial/", "license": "PSF-2.0; code examples additionally 0BSD",
                "license_url": BASE + "license.html", "copyright": "Copyright (c) 2001 Python Software Foundation. All Rights Reserved.",
                "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "adaptation": "Selected complete sections converted from HTML to plain text/Markdown; navigation and header links removed. Teaching notes and questions are independently authored.",
                "scope_note": f"完整保留所列 {len(sections)} 节原文；本轮只测变量、分支、循环、函数四个入门主题，不覆盖整本教程。",
                "sections": sections}
    (target / "python_tutorial.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(sections)} complete sections, {sum(len(s['text']) for s in sections)} characters, version {version}")


if __name__ == "__main__":
    main()
