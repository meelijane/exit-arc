"""The website, README and Claude skill each have a "what each browser gets" table.
These tests fail when one of them disagrees with cli.CAPABILITIES, so the docs can't drift."""
import html
import re
import unittest
from html.parser import HTMLParser

from helpers import ROOT

from exit_arc import cli

TARGETS = ("firefox", "zen", "chrome")
ROWS = {  # row label in the docs -> step
    "bookmarks": "import",
    "spaces": "spaces",
    "favourites": "pin-favourites",
    "vertical tabs": "vertical-tabs",
    "new tab cleanup": "clean-newtab",
    "extensions": "extensions",
    "default browser": "default-browser",
}


def level(cell):
    """What a table cell claims: yes, experimental, built in or no."""
    text = re.sub(r"[*_`]", "", cell).strip().lower()
    if text in ("-", "–", "") or text.startswith("no") or text.startswith("not "):
        return "no"
    if text.startswith("experimental"):
        return "experimental"
    if text.startswith("built in"):
        return "built in"
    return "yes"


def expected(step, target):
    return cli.CAPABILITIES[step][target][0]


def markdown_rows(text, heading):
    section = text.split(heading, 1)[1]
    rows = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        label = re.sub(r"[*`]", "", cells[0]).split(":")[0].strip().lower()
        rows[label] = cells
    return rows


class SiteTable(HTMLParser):
    """Collects {row label: {data-label: cell text}} from the site's "moves" section."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.in_moves, self.skip = {}, None, None, False, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section":
            self.in_moves = a.get("aria-labelledby") == "moves"
        if not self.in_moves:
            return
        if tag == "th" and a.get("scope") == "row":
            self.cell = ("__label__", "")
        elif tag == "td" and self.row is not None:
            self.cell = (a.get("data-label", "").lower(), "")
        elif tag == "span" and ("sub" in (a.get("class") or "").split() or a.get("class") == "sr-only"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag == "span" and self.skip:
            self.skip -= 1
        if tag in ("th", "td") and self.cell is not None:
            key, text = self.cell
            text = html.unescape(text).strip()
            if key == "__label__":
                self.row = text.lower()
                self.rows[self.row] = {}
            else:
                self.rows[self.row][key] = text
            self.cell = None
        if tag == "section":
            self.in_moves = False

    def handle_data(self, data):
        if self.cell is not None and not self.skip:
            self.cell = (self.cell[0], self.cell[1] + data)


class DocsMatchTheTool(unittest.TestCase):
    def check(self, name, cells_for):
        for label, step in ROWS.items():
            cells = cells_for(label)
            self.assertIsNotNone(cells, f"{name} has no row for {label!r}")
            for target in TARGETS:
                with self.subTest(doc=name, step=step, target=target):
                    self.assertEqual(level(cells[target]), expected(step, target),
                                     f"{name}: {label} / {target} says {cells[target]!r}")

    def test_readme(self):
        rows = markdown_rows((ROOT / "README.md").read_text(), "## What each browser gets")
        self.check("README", lambda l: rows.get(l) and dict(zip(TARGETS, rows[l][1:4])))

    def test_site(self):
        parser = SiteTable()
        parser.feed((ROOT / "site" / "public" / "index.html").read_text())
        self.check("site", lambda l: parser.rows.get(l))

    def test_skill(self):
        rows = markdown_rows((ROOT / "skills" / "exit-arc" / "SKILL.md").read_text(), "| Step | Option |")
        by_option = {}
        for cells in rows.values():
            m = re.search(r"--[a-z-]+", cells[1]) if len(cells) > 1 else None
            if m:
                by_option[m.group(0)] = dict(zip(TARGETS, cells[2:5]))
        option = {"import": "--import", "spaces": "--spaces", "pin-favourites": "--pin-favourites",
                  "vertical-tabs": "--vertical-tabs", "clean-newtab": "--clean-newtab",
                  "extensions": "--extensions", "default-browser": "--default-browser"}
        self.check("SKILL.md", lambda l: by_option.get(option[ROWS[l]]))

    def test_level_reader(self):
        self.assertEqual(level("No: Chrome has no spaces"), "no")
        self.assertEqual(level("**yes**: real Zen spaces"), "yes")
        self.assertEqual(level("Experimental: added"), "experimental")
        self.assertEqual(level("Built in"), "built in")
        self.assertEqual(level("-"), "no")


if __name__ == "__main__":
    unittest.main()
