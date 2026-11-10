"""Tests for arc-to-firefox. Run: python3 -m unittest discover -s tests

All data here is synthetic (tests/fixtures/arc). Nothing touches your real
Arc or Firefox profiles: Firefox is replaced by tests/fake_firefox.py.
"""
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import arc_to_firefox as a2f  # noqa: E402
from fake_firefox import add, create_places, parse_bookmarks_html  # noqa: E402

FIXTURE = HERE / "fixtures" / "arc"
FAKE_FIREFOX = HERE / "fake_firefox.py"


def titles(nodes):
    return [n["title"] for n in nodes]


def find(nodes, title):
    return next(n for n in nodes if n["title"] == title)


def flat_links(nodes):
    out = []
    for n in nodes:
        out += [n["url"]] if n["type"] == "link" else flat_links(n["children"])
    return out


class ReadArcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = a2f.read_arc(FIXTURE)
        cls.by_dir = {p["directory"]: p for p in cls.export["profiles"]}

    def test_profiles_named_and_system_profile_ignored(self):
        self.assertEqual(list(self.by_dir), ["Default", "Profile 2"])
        self.assertEqual(self.by_dir["Default"]["name"], "Default")
        self.assertEqual(self.by_dir["Profile 2"]["name"], "Work")
        all_urls = flat_links([s for p in self.export["profiles"] for s in p["spaces"] for s in s["pinned"]])
        self.assertNotIn("https://system.example.com/", all_urls)

    def test_spaces_titles_and_emoji(self):
        spaces = self.by_dir["Default"]["spaces"]
        self.assertEqual([(s["emoji"], s["title"]) for s in spaces], [("🏠", "Home"), ("📚", "Reading")])
        self.assertEqual(self.by_dir["Profile 2"]["spaces"][0]["emoji"], "")

    def test_pinned_tree_folders_and_split_view(self):
        home = self.by_dir["Default"]["spaces"][0]["pinned"]
        # split view children are flattened into the space; notes/easels skipped
        self.assertEqual(titles(home), ['Docs & "Notes" <b>', "Tools", "Left pane", "Right pane"])
        tools = find(home, "Tools")
        self.assertEqual(titles(tools["children"]), ["Tools page", "Nested"])
        self.assertEqual(find(tools["children"], "Nested")["children"][0]["url"], "https://deep.example.net/path/")

    def test_title_falls_back_to_saved_title_then_url(self):
        reading = self.by_dir["Default"]["spaces"][1]["pinned"]
        self.assertEqual(reading[0]["title"], "https://reading.example.org/article")
        favs = self.by_dir["Default"]["favourites"]
        self.assertEqual(titles(favs), ["Mail", "Cal"])  # 'Cal' is a user rename

    def test_favourites_per_profile(self):
        self.assertEqual(flat_links(self.by_dir["Profile 2"]["favourites"]), ["https://chat.example.com/"])

    def test_unpinned_kept_in_json(self):
        self.assertEqual(flat_links(self.by_dir["Default"]["spaces"][0]["unpinned"]),
                         ["https://open.example.com/unpinned"])

    def test_newcontainerids_only_space(self):
        self.assertEqual(len(self.by_dir["Default"]["spaces"][1]["pinned"]), 1)

    def test_skipped_counts(self):
        self.assertEqual(self.export["skipped"], {"easel": 1, "missing item": 1, "tab without URL": 1})

    def test_counts_and_summary(self):
        self.assertEqual(len(a2f.exported_urls(self.export)), 10)
        self.assertEqual(len(a2f.exported_urls(self.export, include_unpinned=True)), 11)
        text = "\n".join(a2f.summary(self.export))
        self.assertIn("🏠 Home: 5 pinned links, 2 folders, 1 open unpinned (not exported)", text)
        self.assertIn("Profile: Work (Profile 2)", text)
        self.assertIn("Total links to bookmark: 10", text)

    def test_filter_profiles(self):
        only = a2f.filter_profiles(self.export, ["work"])
        self.assertEqual([p["directory"] for p in only["profiles"]], ["Profile 2"])
        with self.assertRaises(a2f.ToolError):
            a2f.filter_profiles(self.export, ["nope"])

    def test_missing_arc_dir_is_friendly(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(a2f.ToolError) as cm:
            a2f.read_arc(d)
        self.assertIn("Arc data not found", str(cm.exception))

    def test_works_without_local_state(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "StorableSidebar.json").write_text((FIXTURE / "StorableSidebar.json").read_text())
            export = a2f.read_arc(d)
        # Without profile names nothing can be identified as the system profile.
        self.assertEqual([p["directory"] for p in export["profiles"]], ["Default", "Profile 1", "Profile 2"])


class HtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = a2f.read_arc(FIXTURE)

    def test_toolbar_layout_multi_profile(self):
        tree = parse_bookmarks_html(a2f.build_html(self.export, "toolbar"))
        self.assertEqual(tree["menu"], [])
        self.assertEqual(titles(tree["toolbar"]), ["Default", "Work"])
        default = tree["toolbar"][0]["children"]
        self.assertEqual(titles(default), ["Mail", "Cal", "🏠 Home", "📚 Reading"])
        self.assertEqual(find(default, "🏠 Home")["children"][0]["title"], 'Docs & "Notes" <b>')
        self.assertEqual(len(flat_links(tree["toolbar"])), 10)

    def test_toolbar_layout_single_profile_is_flat(self):
        one = a2f.filter_profiles(self.export, ["Default"])
        tree = parse_bookmarks_html(a2f.build_html(one, "toolbar"))
        self.assertEqual(titles(tree["toolbar"]), ["Mail", "Cal", "🏠 Home", "📚 Reading"])

    def test_folder_layout(self):
        one = a2f.filter_profiles(self.export, ["Default"])
        tree = parse_bookmarks_html(a2f.build_html(one, "folder"))
        self.assertEqual(tree["toolbar"], [])
        arc = tree["menu"][0]
        self.assertEqual(arc["title"], "Arc")
        self.assertEqual(titles(arc["children"]), ["Favourites", "🏠 Home", "📚 Reading"])
        multi = parse_bookmarks_html(a2f.build_html(self.export, "folder"))
        self.assertEqual(titles(multi["menu"][0]["children"]), ["Default", "Work"])

    def test_include_unpinned(self):
        tree = parse_bookmarks_html(a2f.build_html(self.export, "toolbar", include_unpinned=True))
        home = find(tree["toolbar"][0]["children"], "🏠 Home")
        self.assertEqual(find(home["children"], "Open tabs (unpinned)")["children"][0]["url"],
                         "https://open.example.com/unpinned")

    def test_urls_escaped(self):
        html_text = a2f.build_html(self.export)
        self.assertIn('HREF="https://example.org/tools?a=1&amp;b=2"', html_text)
        self.assertIn("Docs &amp; &quot;Notes&quot; &lt;b&gt;", html_text)
        self.assertIn('PERSONAL_TOOLBAR_FOLDER="true"', html_text)


class FirefoxProfileTests(unittest.TestCase):
    def write_ini(self, d, text):
        Path(d, "profiles.ini").write_text(text)

    def test_install_default_wins(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_ini(d, "[Profile1]\nName=old\nIsRelative=1\nPath=Profiles/old.default\nDefault=1\n\n"
                              "[Profile0]\nName=default-release\nIsRelative=1\nPath=Profiles/abc.default-release\n\n"
                              "[Install4F96D1932A9F858E]\nDefault=Profiles/abc.default-release\nLocked=1\n")
            path, note = a2f.default_firefox_profile(d)
            self.assertEqual(path, Path(d) / "Profiles/abc.default-release")
            self.assertIsNone(note)

    def test_absolute_profile_and_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_ini(d, "[Profile0]\nName=x\nIsRelative=0\nPath=/somewhere/x\nDefault=1\n")
            self.assertEqual(a2f.default_firefox_profile(d)[0], Path("/somewhere/x"))

    def test_missing_profiles_ini(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(a2f.ToolError):
            a2f.default_firefox_profile(d)

    def test_existing_bookmarks_ignores_defaults_and_tags(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(a2f.existing_bookmarks(d), (0, 0))  # no places.sqlite yet
            db = create_places(Path(d) / "places.sqlite")
            add(db, 3, {"type": "link", "title": "Getting Started", "url": "https://www.mozilla.org/firefox/central/"})
            add(db, 2, {"type": "folder", "title": "Mine", "children": [
                {"type": "link", "title": "Mine", "url": "https://mine.example.com/"}]})
            add(db, 4, {"type": "folder", "title": "sometag", "children": [
                {"type": "link", "title": "", "url": "https://tagged.example.com/"}]})
            db.commit()
            db.close()
            self.assertEqual(a2f.existing_bookmarks(d), (2, 1))

    def test_normalize_url(self):
        self.assertEqual(a2f.normalize_url("HTTPS://Example.COM"), "https://example.com/")
        self.assertEqual(a2f.normalize_url("about:blank"), "about:blank")


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.profile = self.dir / "ffprofile"
        self.profile.mkdir()
        self.out = self.dir / "out"
        os.chmod(FAKE_FIREFOX, os.stat(FAKE_FIREFOX).st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *extra):
        argv = ["--arc-dir", str(FIXTURE), "-o", str(self.out), "--import", "--firefox-profile", str(self.profile),
                "--firefox-bin", str(FAKE_FIREFOX), "--yes", "--timeout", "20", *extra]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = a2f.run(a2f.parse_args(argv))
        return code, buf.getvalue()

    def imported_urls(self):
        with a2f.PlacesSnapshot(self.profile) as snap:
            return {u for _, u, _ in snap.bookmarks()}

    def test_import_into_empty_profile_and_cleanup(self):
        (self.profile / "user.js").write_text('user_pref("my.own.pref", 1);\n')
        code, out = self.cli()
        self.assertEqual(code, 0, out)
        self.assertIn("all 10 links are in Firefox", out)
        self.assertEqual(len(self.imported_urls()), 10)
        self.assertEqual((self.profile / "user.js").read_text(), 'user_pref("my.own.pref", 1);\n')
        prefs = (self.profile / "prefs.js").read_text()
        self.assertNotIn("browser.bookmarks.file", prefs)
        self.assertNotIn("importBookmarksHTML", prefs)
        self.assertIn('"browser.toolbars.bookmarks.visibility", "always"', prefs)
        self.assertEqual(list(self.profile.glob("arc-to-firefox-import-*.html")), [])
        self.assertTrue((self.out / "arc-bookmarks.html").exists())
        self.assertFalse(os.path.lexists(self.profile / "lock"))

    def test_user_js_removed_when_it_did_not_exist(self):
        code, out = self.cli("--no-show-toolbar")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.profile / "user.js").exists())
        self.assertNotIn("visibility", (self.profile / "prefs.js").read_text())

    def test_refuses_profile_with_existing_bookmarks(self):
        db = create_places(self.profile / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep me", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        code, out = self.cli()
        self.assertEqual(code, 3)
        self.assertIn("REPLACES", out)
        self.assertIn("Import Bookmarks from HTML", out)
        self.assertEqual(self.imported_urls(), {"https://keep.example.com/"})
        self.assertFalse((self.profile / "user.js").exists())

    def test_replace_existing_backs_up_first(self):
        db = create_places(self.profile / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep me", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        code, out = self.cli("--replace-existing")
        self.assertEqual(code, 0, out)
        backups = list(self.out.glob("firefox-bookmarks-backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "places.sqlite").exists())
        saved = parse_bookmarks_html((backups[0] / "bookmarks.html").read_text())
        self.assertEqual(flat_links(saved["toolbar"]), ["https://keep.example.com/"])
        self.assertNotIn("https://keep.example.com/", self.imported_urls())

    def test_reports_missing_links(self):
        os.environ["FAKE_FIREFOX_SKIP"] = "chat.example.com"
        try:
            code, out = self.cli()
        finally:
            del os.environ["FAKE_FIREFOX_SKIP"]
        self.assertEqual(code, 4)
        self.assertIn("Imported 9 of 10 links", out)
        self.assertIn("https://chat.example.com/", out)

    def test_refuses_locked_profile(self):
        os.symlink(f"127.0.0.1:+{os.getpid()}", self.profile / "lock")
        with self.assertRaises(a2f.ToolError) as cm:
            self.cli()
        self.assertIn("Quit Firefox", str(cm.exception))

    def test_stale_lock_is_ignored(self):
        os.symlink("127.0.0.1:+999999", self.profile / "lock")
        self.assertFalse(a2f.profile_in_use(self.profile))

    def test_dry_run_writes_nothing(self):
        code, out = self.cli("--dry-run")
        self.assertEqual(code, 0, out)
        self.assertIn("[dry run]", out)
        self.assertFalse(self.out.exists())
        self.assertEqual(sorted(p.name for p in self.profile.iterdir()), [])


class JsonOutputTests(unittest.TestCase):
    def test_writes_json_and_html(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = a2f.run(a2f.parse_args(["--arc-dir", str(FIXTURE), "-o", d]))
            self.assertEqual(code, 0)
            data = json.loads(Path(d, "arc-export.json").read_text())
            self.assertEqual([p["name"] for p in data["profiles"]], ["Default", "Work"])
            self.assertTrue(Path(d, "arc-bookmarks.html").read_text().startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>"))


if __name__ == "__main__":
    unittest.main()
