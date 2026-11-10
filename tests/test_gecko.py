"""Firefox/Zen profile helpers: profiles.ini, places.sqlite, sessionstore, headless import."""
import os
import unittest
from pathlib import Path

from fake_firefox import add, create_places
from helpers import FAKE_FIREFOX, FIXTURE, SandboxTest

from exit_arc import ToolError, arc, browsers, exporters, gecko, mozlz4


class ProfilesIniTests(SandboxTest):
    def write_ini(self, text):
        (self.dir / "profiles.ini").write_text(text)

    def test_install_default_wins(self):
        self.write_ini("[Profile1]\nName=old\nIsRelative=1\nPath=Profiles/old.default\nDefault=1\n\n"
                       "[Profile0]\nName=default-release\nIsRelative=1\nPath=Profiles/abc.default-release\n\n"
                       "[Install4F96D1932A9F858E]\nDefault=Profiles/abc.default-release\nLocked=1\n")
        path, note = gecko.default_profile(browsers.FIREFOX, self.dir)
        self.assertEqual(path, self.dir / "Profiles/abc.default-release")
        self.assertIsNone(note)

    def test_several_installs_noted(self):
        self.write_ini("[InstallA]\nDefault=Profiles/a\n\n[InstallB]\nDefault=Profiles/b\n")
        path, note = gecko.default_profile(browsers.ZEN, self.dir)
        self.assertEqual(path, self.dir / "Profiles/a")
        self.assertIn("Several Zen installs", note)

    def test_absolute_profile_and_legacy_fallback(self):
        self.write_ini("[Profile0]\nName=x\nIsRelative=0\nPath=/somewhere/x\nDefault=1\n")
        self.assertEqual(gecko.default_profile(browsers.FIREFOX, self.dir)[0], Path("/somewhere/x"))

    def test_missing_profiles_ini(self):
        with self.assertRaises(ToolError) as cm:
            gecko.default_profile(browsers.ZEN, self.dir)
        self.assertIn("No Zen profile", str(cm.exception))


class PlacesTests(SandboxTest):
    def test_existing_bookmarks_ignores_defaults_and_tags(self):
        p = self.profile()
        self.assertEqual(gecko.existing_bookmarks(p), (0, 0))
        db = create_places(p / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Getting Started", "url": "https://www.mozilla.org/firefox/central/"})
        add(db, 2, {"type": "folder", "title": "Mine", "children": [
            {"type": "link", "title": "Mine", "url": "https://mine.example.com/"}]})
        add(db, 4, {"type": "folder", "title": "tag", "children": [
            {"type": "link", "title": "", "url": "https://tagged.example.com/"}]})
        db.commit()
        db.close()
        self.assertEqual(gecko.existing_bookmarks(p), (2, 1))

    def test_backup_writes_importable_html(self):
        p = self.profile()
        db = create_places(p / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        dest = gecko.backup_bookmarks(p, self.dir / "bk")
        self.assertTrue((dest / "places.sqlite").exists())
        self.assertIn("https://keep.example.com/", (dest / "bookmarks.html").read_text())

    def test_profile_lock(self):
        p = self.profile()
        self.assertFalse(gecko.profile_in_use(p))
        os.symlink("127.0.0.1:+999999", p / "lock")
        self.assertFalse(gecko.profile_in_use(p))  # stale
        (p / "lock").unlink()
        os.symlink(f"127.0.0.1:+{os.getpid()}", p / "lock")
        self.assertTrue(gecko.profile_in_use(p))

    def test_normalize_url(self):
        self.assertEqual(gecko.normalize_url("HTTPS://Example.COM"), "https://example.com/")
        self.assertEqual(gecko.normalize_url("about:blank"), "about:blank")


class SessionTests(unittest.TestCase):
    def window(self, *tabs, selected=1):
        return {"windows": [{"tabs": [dict(t) for t in tabs], "selected": selected}]}

    def tab(self, url, pinned=False):
        return {"entries": [{"url": url}], "index": 1, "pinned": pinned}

    def test_inserts_after_existing_pins_and_shifts_selection(self):
        s = self.window(self.tab("https://pinned.example/", True), self.tab("https://a.example/"),
                        self.tab("https://b.example/"), selected=3)
        added = gecko.add_pinned_tabs(s, [("https://new1.example/", "N1"), ("https://new2.example/", "N2")], 1)
        tabs = s["windows"][0]["tabs"]
        self.assertEqual(added, 2)
        self.assertEqual([gecko.tab_url(t) for t in tabs], ["https://pinned.example/", "https://new1.example/",
                                                            "https://new2.example/", "https://a.example/",
                                                            "https://b.example/"])
        self.assertEqual(s["windows"][0]["selected"], 5)  # still b.example
        self.assertTrue(tabs[1]["pinned"])
        self.assertEqual(tabs[1]["entries"][0]["triggeringPrincipal_base64"], '{"3":{}}')

    def test_selection_before_insert_point_unchanged(self):
        s = self.window(self.tab("https://pinned.example/", True), self.tab("https://a.example/"), selected=1)
        gecko.add_pinned_tabs(s, [("https://new.example/", "N")], 1)
        self.assertEqual(s["windows"][0]["selected"], 1)

    def test_skips_already_pinned_and_duplicates(self):
        s = self.window(self.tab("https://Pinned.example", True), self.tab("https://open.example/"))
        added = gecko.add_pinned_tabs(s, [("https://pinned.example/", "P"), ("https://open.example/", "O"),
                                          ("https://open.example/", "O again")], 1)
        self.assertEqual(added, 1)  # an open (unpinned) tab with the URL still gets a pinned copy
        self.assertEqual(gecko.add_pinned_tabs(s, [("https://open.example/", "O")], 1), 0)

    def test_empty_session(self):
        s = gecko.empty_session(5)
        gecko.add_pinned_tabs(s, [("https://a.example/", "A")], 5)
        self.assertEqual(s["windows"][0]["selected"], 1)
        self.assertEqual(len(s["windows"][0]["tabs"]), 1)


class PinTabsFileTests(SandboxTest):
    def test_creates_session_when_missing(self):
        p = self.profile()
        added, path = gecko.pin_tabs(p, [("https://a.example/", "A")])
        self.assertEqual((added, path.name), (1, "sessionstore.jsonlz4"))
        self.assertTrue(mozlz4.read_json(path)["windows"][0]["tabs"][0]["pinned"])

    def test_uses_recovery_when_no_clean_session_and_backs_up(self):
        p = self.profile()
        (p / "sessionstore-backups").mkdir()
        mozlz4.write_json(p / "sessionstore-backups" / "recovery.jsonlz4",
                          {"windows": [{"tabs": [{"entries": [{"url": "https://open.example/"}], "index": 1}],
                                        "selected": 1}]})
        added, path = gecko.pin_tabs(p, [("https://a.example/", "A")], backup_dir=self.dir / "bk")
        tabs = mozlz4.read_json(p / "sessionstore.jsonlz4")["windows"][0]["tabs"]
        self.assertEqual([gecko.tab_url(t) for t in tabs], ["https://a.example/", "https://open.example/"])
        self.assertTrue((self.dir / "bk" / "sessionstore.jsonlz4").exists())


class HeadlessImportTests(SandboxTest):
    def html(self):
        export = arc.read_arc(FIXTURE)
        return exporters.build_html(export), exporters.exported_urls(export)

    def test_import_restores_user_js_session_and_prefs(self):
        p = self.profile()
        (p / "user.js").write_text('user_pref("my.own.pref", 1);\n')
        mozlz4.write_json(p / "zen-sessions.jsonlz4", {"spaces": [{"uuid": "x"}], "tabs": []})
        html, urls = self.html()
        found, expected, missing = gecko.import_bookmarks(html, urls, p, FAKE_FIREFOX, log=lambda *_: None,
                                                          timeout=20)
        self.assertEqual((found, expected, missing), (10, 10, []))
        self.assertEqual((p / "user.js").read_text(), 'user_pref("my.own.pref", 1);\n')
        prefs_text = (p / "prefs.js").read_text()
        self.assertNotIn("browser.bookmarks.file", prefs_text)
        self.assertNotIn("importBookmarksHTML", prefs_text)
        self.assertIn('"browser.toolbars.bookmarks.visibility", "always"', prefs_text)
        self.assertEqual(list(p.glob("exit-arc-import-*.html")), [])
        self.assertEqual(mozlz4.read_json(p / "zen-sessions.jsonlz4")["spaces"], [{"uuid": "x"}])
        self.assertFalse(os.path.lexists(p / "lock"))

    def test_reports_missing(self):
        p = self.profile()
        html, urls = self.html()
        os.environ["FAKE_FIREFOX_SKIP"] = "chat.example.com"
        try:
            found, expected, missing = gecko.import_bookmarks(html, urls, p, FAKE_FIREFOX, show_toolbar=False,
                                                              log=lambda *_: None, timeout=20)
        finally:
            del os.environ["FAKE_FIREFOX_SKIP"]
        self.assertEqual((found, expected, missing), (9, 10, ["https://chat.example.com/"]))
        self.assertFalse((p / "user.js").exists())


if __name__ == "__main__":
    unittest.main()
