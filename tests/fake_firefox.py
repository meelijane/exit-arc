#!/usr/bin/env python3
"""A stand-in for the firefox binary, used by the tests.

It does the parts of a real Firefox startup that arc-to-firefox relies on:
reads <profile>/user.js, and if browser.places.importBookmarksHTML is true it
REPLACES places.sqlite with the bookmarks from browser.bookmarks.file, records
the prefs in prefs.js, holds a profile lock, then idles until it's told to quit.

Set FAKE_FIREFOX_SKIP to a URL substring to simulate a bookmark Firefox drops.
"""
import os
import re
import signal
import sqlite3
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

ROOTS = [(1, 0, "root________", ""), (2, 1, "menu________", "menu"), (3, 1, "toolbar_____", "toolbar"),
         (4, 1, "tags________", "tags"), (5, 1, "unfiled_____", "unfiled"), (6, 1, "mobile______", "mobile")]


def create_places(path):
    """An empty places.sqlite with the columns arc-to-firefox reads."""
    if path.exists():
        path.unlink()
    db = sqlite3.connect(str(path))
    db.executescript("""
        CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT);
        CREATE TABLE moz_bookmarks (id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER, parent INTEGER,
                                    position INTEGER, title TEXT, guid TEXT);
    """)
    for i, parent, guid, title in ROOTS:
        db.execute("INSERT INTO moz_bookmarks VALUES (?, 2, NULL, ?, 0, ?, ?)", (i, parent, title, guid))
    db.commit()
    return db


def add(db, parent, node, position=0):
    if node["type"] == "folder":
        cur = db.execute("INSERT INTO moz_bookmarks (type, parent, position, title) VALUES (2, ?, ?, ?)",
                         (parent, position, node["title"]))
        for i, child in enumerate(node["children"]):
            add(db, cur.lastrowid, child, i)
    else:
        place = db.execute("INSERT INTO moz_places (url) VALUES (?)", (node["url"],)).lastrowid
        db.execute("INSERT INTO moz_bookmarks (type, fk, parent, position, title) VALUES (1, ?, ?, ?, ?)",
                   (place, parent, position, node["title"]))


class NetscapeParser(HTMLParser):
    """Parse a Netscape bookmarks file into {'toolbar': [...], 'menu': [...]}."""

    def __init__(self):
        super().__init__()
        self.root = {"type": "folder", "title": "", "children": []}
        self.stack = [self.root]
        self.pending = None   # folder waiting for its <DL>
        self.text = None
        self.toolbar = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h3":
            self.pending = {"type": "folder", "title": "", "children": []}
            if attrs.get("personal_toolbar_folder") == "true":
                self.toolbar = self.pending
            self.stack[-1]["children"].append(self.pending)
            self.text = self.pending
        elif tag == "a":
            link = {"type": "link", "title": "", "url": attrs.get("href")}
            self.stack[-1]["children"].append(link)
            self.text = link
        elif tag == "dl" and self.pending is not None:
            self.stack.append(self.pending)
            self.pending = None

    def handle_endtag(self, tag):
        if tag in ("h3", "a"):
            self.text = None
        elif tag == "dl" and len(self.stack) > 1:
            self.stack.pop()

    def handle_data(self, data):
        if self.text is not None:
            self.text["title"] += data

    def result(self):
        menu = [n for n in self.root["children"] if n is not self.toolbar]
        return {"toolbar": self.toolbar["children"] if self.toolbar else [], "menu": menu}


def parse_bookmarks_html(text):
    p = NetscapeParser()
    p.feed(text)
    return p.result()


def read_prefs(path):
    prefs = {}
    if path.exists():
        for m in re.finditer(r'user_pref\("([^"]+)",\s*(.+?)\);', path.read_text(encoding="utf-8")):
            prefs[m.group(1)] = m.group(2)
    return prefs


def main():
    args = sys.argv[1:]
    profile = Path(args[args.index("--profile") + 1])
    prefs = read_prefs(profile / "user.js")
    (profile / "lock").unlink(missing_ok=True)
    os.symlink(f"127.0.0.1:+{os.getpid()}", profile / "lock")

    def quit_(*_):
        (profile / "lock").unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, quit_)

    if prefs.get("browser.places.importBookmarksHTML") == "true":
        import json
        source = Path(json.loads(prefs["browser.bookmarks.file"]))
        tree = parse_bookmarks_html(source.read_text(encoding="utf-8"))
        skip = os.environ.get("FAKE_FIREFOX_SKIP")

        def keep(nodes):
            out = []
            for n in nodes:
                if n["type"] == "link" and skip and skip in n["url"]:
                    continue
                if n["type"] == "folder":
                    n = {**n, "children": keep(n["children"])}
                out.append(n)
            return out

        db = create_places(profile / "places.sqlite")
        for parent, key in ((3, "toolbar"), (2, "menu")):
            for i, node in enumerate(keep(tree[key])):
                add(db, parent, node, i)
        db.commit()
        db.close()
        # Like Firefox: user.js values end up persisted in prefs.js.
        with open(profile / "prefs.js", "a", encoding="utf-8") as f:
            f.write('user_pref("browser.places.importBookmarksHTML", false);\n')
            f.write(f'user_pref("browser.bookmarks.file", {prefs["browser.bookmarks.file"]});\n')
            if "browser.toolbars.bookmarks.visibility" in prefs:
                f.write(f'user_pref("browser.toolbars.bookmarks.visibility", '
                        f'{prefs["browser.toolbars.bookmarks.visibility"]});\n')

    while True:
        time.sleep(0.2)


if __name__ == "__main__":
    main()
