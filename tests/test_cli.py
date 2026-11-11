"""End-to-end CLI runs against fixture profiles in a temp dir (fake OS, fake Firefox, fake AMO)."""
import csv
import json
import os

from fake_firefox import add, create_places
from helpers import FAKE_FIREFOX, SandboxTest

from exit_arc import ToolError, browsers, cli, gecko, mozlz4, prefs, zen


class ExportOnlyTests(SandboxTest):
    def test_writes_all_formats_by_default(self):
        code, out = self.cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         ["arc-bookmarks.html", "arc-export.json", "arc-sidebar.md", "arc-tabs.csv"])
        self.assertIn("Import Bookmarks from HTML", out)
        self.assertEqual(self.amo.queries, [])  # nothing sent anywhere without --extensions

    def test_format_option(self):
        code, _ = self.cli("--format", "csv,md")
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["arc-sidebar.md", "arc-tabs.csv"])
        with (self.out / "arc-tabs.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual({r["kind"] for r in rows}, {"favourite", "pinned", "unpinned"})

    def test_dry_run_writes_nothing(self):
        code, out = self.cli("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("[dry run]", out)
        self.assertFalse(self.out.exists())

    def test_capabilities(self):
        code, out = self.cli("--capabilities")
        self.assertIn("Spaces as real spaces", out)
        self.assertIn("experimental", out)


class FirefoxTests(SandboxTest):
    def run_ff(self, *extra, answers=(True,)):
        return self.cli("--to", "firefox", "--browser-profile", str(self.profile()), "--browser-bin",
                        str(FAKE_FIREFOX), "--timeout", "20", *extra, answers=list(answers))

    def test_all_steps(self):
        code, out = self.run_ff("--import", "--pin-favourites", "--vertical-tabs", "--clean-newtab")
        self.assertEqual(code, 0, out)
        p = self.dir / "profile"
        with gecko.PlacesSnapshot(p) as snap:
            self.assertEqual(len({u for _, u, _ in snap.bookmarks()}), 10)
        values = prefs.read_prefs(p / "prefs.js")
        self.assertEqual(values["sidebar.verticalTabs"], True)
        self.assertEqual(values["browser.startup.page"], 3)
        self.assertEqual(values["browser.newtabpage.activity-stream.showSponsoredTopSites"], False)
        self.assertEqual(values["browser.newtabpage.activity-stream.default.sites"], "")
        self.assertNotIn("browser.bookmarks.file", values)
        tabs = mozlz4.read_json(p / "sessionstore.jsonlz4")["windows"][0]["tabs"]
        self.assertEqual([gecko.tab_url(t) for t in tabs if t["pinned"]],
                         ["https://mail.example.com/", "https://calendar.example.com/", "https://chat.example.com/"])
        self.assertEqual(len(list(self.out.glob("backup-firefox-*"))), 1)
        self.assertEqual(self.asked, ["Change this Firefox profile now?"])

    def test_refuses_existing_bookmarks(self):
        p = self.profile()
        db = create_places(p / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        code, out = self.run_ff("--import", "--vertical-tabs")
        self.assertEqual(code, 3)
        self.assertIn("REPLACES", out)
        self.assertFalse((p / "prefs.js").exists())  # nothing else ran either

    def test_replace_existing_backs_up(self):
        p = self.profile()
        db = create_places(p / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        code, out = self.run_ff("--import", "--replace-existing")
        self.assertEqual(code, 0, out)
        backup = next(self.out.glob("backup-firefox-*"))
        self.assertIn("https://keep.example.com/", (backup / "bookmarks" / "bookmarks.html").read_text())

    def test_cancel_changes_nothing(self):
        code, out = self.run_ff("--vertical-tabs", answers=[False])
        self.assertEqual(code, 1)
        self.assertFalse((self.dir / "profile" / "prefs.js").exists())

    def test_locked_profile(self):
        p = self.profile()
        os.symlink(f"127.0.0.1:+{os.getpid()}", p / "lock")
        with self.assertRaises(ToolError):
            self.run_ff("--vertical-tabs")

    def test_dry_run_changes_nothing(self):
        code, out = self.run_ff("--import", "--vertical-tabs", "--dry-run")
        self.assertEqual(code, 0, out)
        self.assertEqual(list((self.dir / "profile").iterdir()), [])

    def test_extensions_lookup_and_install_prompts(self):
        code, out = self.run_ff("--extensions", answers=[True])
        self.assertEqual(code, 0, out)
        self.assertIn("Tab Notes Example", self.amo.queries)
        self.assertEqual(self.system.opened[0][0], "firefox")
        self.assertEqual(len(self.system.opened[0][1]), 2)
        self.assertIn("maybe: Snapshot Helper Free", out)
        self.assertIn("sign in again", out)
        md = (self.out / "arc-sidebar.md").read_text()
        self.assertIn("tab-notes-example", md)

    def test_extensions_declined(self):
        code, out = self.run_ff("--extensions", answers=[False])
        self.assertEqual(self.system.opened, [])
        self.assertIn("Skipped", out)


class ZenCliTests(SandboxTest):
    def test_all_on_zen(self):
        p = self.profile()
        code, out = self.cli("--to", "zen", "--all", "--browser-profile", str(p), "--browser-bin", str(FAKE_FIREFOX),
                             "--timeout", "20", answers=[True, True])
        self.assertEqual(code, 0, out)
        self.assertIn("Vertical tabs: skipped - built in", out)
        d = mozlz4.read_json(p / zen.SESSION_FILE)
        self.assertEqual(len(d["spaces"]), 3)
        self.assertEqual(sum(1 for t in d["tabs"] if t.get("zenEssential")), 3)
        self.assertNotIn("sidebar.verticalTabs", prefs.read_prefs(p / "prefs.js"))
        self.assertEqual(self.system.opened[0][0], "zen")


class ChromeCliTests(SandboxTest):
    def test_chrome_import_and_extensions(self):
        p = self.profile("Chrome/Default")
        code, out = self.cli("--to", "chrome", "--all", "--browser-profile", str(p), answers=[True, True])
        self.assertEqual(code, 0, out)
        self.assertIn("Favourites as pinned tabs: skipped - no", out)
        bar = json.loads((p / "Bookmarks").read_text())["roots"]["bookmark_bar"]["children"]
        self.assertEqual([c["name"] for c in bar], ["Default", "Work"])
        self.assertEqual(self.amo.queries, [])  # Chrome needs no lookup
        opened = self.system.opened[0]
        self.assertEqual(opened[0], "chrome")
        self.assertTrue(all(u.startswith("https://chromewebstore.google.com/detail/") for u in opened[1]))

    def test_chrome_lock(self):
        p = self.profile("Chrome/Default")
        os.symlink(f"host-{os.getpid()}", p.parent / "SingletonLock")
        with self.assertRaises(ToolError):
            self.cli("--to", "chrome", "--import", "--browser-profile", str(p), answers=[True])


class QuitBrowserTests(SandboxTest):
    def test_asks_then_quits(self):
        self.system.running.add("firefox")
        asked = []
        browsers.ensure_closed(browsers.FIREFOX, lambda q: asked.append(q) or True, log=lambda *_: None)
        self.assertEqual(self.system.quit_calls, ["firefox"])
        self.assertIn("Quit it now?", asked[0])

    def test_refuses_without_permission(self):
        self.system.running.add("zen")
        with self.assertRaises(ToolError):
            browsers.ensure_closed(browsers.ZEN, lambda q: False, log=lambda *_: None)
        self.assertEqual(self.system.quit_calls, [])

    def test_quit_flag_and_failure(self):
        self.system.running.add("chrome")
        self.system.quit_works = False
        with self.assertRaises(ToolError) as cm:
            browsers.ensure_closed(browsers.CHROME, lambda q: False, allow_quit=True, log=lambda *_: None)
        self.assertIn("didn't quit", str(cm.exception))

    def test_yes_does_not_quit_by_itself(self):
        ask = cli.make_ask(True)
        self.assertTrue(ask("Change?"))
        import builtins
        real_input = builtins.input
        builtins.input = lambda *_: "n"
        try:
            self.assertFalse(ask("Quit?", quitting=True))
        finally:
            builtins.input = real_input


if __name__ == "__main__":
    import unittest
    unittest.main()
