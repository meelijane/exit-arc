"""Choosing the browser profile: listing them, picking by name, and the question."""
import dataclasses
import io
import json
import sqlite3
from contextlib import redirect_stdout

from fake_firefox import add, create_places
from helpers import FAKE_FIREFOX, FIXTURE, SandboxTest

from exit_arc import ToolError, browsers, chrome, cli, gecko, guided, prefs

INI = """[General]
StartWithLastProfile=1
Version=2

[Profile0]
Name=default-release
IsRelative=1
Path=Profiles/aaa.default-release

[Profile1]
Name=default
IsRelative=1
Path=Profiles/bbb.default
Default=1

[Profile2]
Name=gone
IsRelative=1
Path=Profiles/ccc.missing

[InstallABC]
Default=Profiles/aaa.default-release
Locked=1
"""


class FirefoxRoot:
    def firefox_root(self, groups=()):
        root = self.dir / "Firefox"
        for name in ("aaa.default-release", "bbb.default", *[g[0] for g in groups]):
            (root / "Profiles" / name).mkdir(parents=True)
        (root / "profiles.ini").write_text(INI)
        if groups:
            (root / "Profile Groups").mkdir()
            db = sqlite3.connect(root / "Profile Groups" / "123.sqlite")
            db.execute("CREATE TABLE Profiles (id INTEGER PRIMARY KEY, path TEXT, name TEXT)")
            db.executemany("INSERT INTO Profiles (path, name) VALUES (?, ?)",
                           [(f"Profiles/{d}", n) for d, n in groups])
            db.commit()
            db.close()
        return root


class ProfileListTests(FirefoxRoot, SandboxTest):
    def test_lists_default_first_and_skips_missing(self):
        root = self.firefox_root()
        ps = gecko.list_profiles(browsers.FIREFOX, root)
        self.assertEqual([(p["name"], p["default"]) for p in ps], [("default-release", True), ("default", False)])

    def test_profile_groups(self):
        root = self.firefox_root(groups=[("ddd.work", "Work")])
        names = [p["name"] for p in gecko.list_profiles(browsers.FIREFOX, root)]
        self.assertEqual(names, ["default-release", "default", "Work"])

    def test_chrome_profiles(self):
        root = self.dir / "Chrome"
        for d in ("Default", "Profile 3"):
            (root / d).mkdir(parents=True)
        (root / "Local State").write_text(json.dumps({"profile": {"last_used": "Profile 3", "info_cache": {
            "Default": {"name": "Personal"}, "Profile 3": {"name": "Work"}, "Profile 9": {"name": "Gone"}}}}))
        ps = chrome.list_profiles(root)
        self.assertEqual([(p["name"], p["default"]) for p in ps], [("Work", True), ("Personal", False)])

    def test_browser_profile_by_name(self):
        root = self.firefox_root()
        target = dataclasses.replace(browsers.FIREFOX, data_root=root)
        args = cli.parse_args(["--browser-profile", "default"])
        self.assertEqual(cli.find_profile(args, target, print), root / "Profiles" / "bbb.default")
        args = cli.parse_args(["--browser-profile", "nope"])
        with self.assertRaises(ToolError) as cm:
            cli.find_profile(args, target, print)
        self.assertIn("default-release, default", str(cm.exception))


class GuidedProfileTests(FirefoxRoot, SandboxTest):
    def setUp(self):
        super().setUp()
        self.root = self.firefox_root()
        self._real = browsers.BROWSERS["firefox"]
        browsers.BROWSERS["firefox"] = dataclasses.replace(self._real, data_root=self.root)
        db = create_places(self.root / "Profiles" / "aaa.default-release" / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Mine", "url": "https://mine.example.com/"})
        db.commit()
        db.close()

    def tearDown(self):
        browsers.BROWSERS["firefox"] = self._real
        super().tearDown()

    def guided(self, answers):
        replies = list(answers)

        def fake_input(prompt):
            if not replies:
                raise EOFError
            return replies.pop(0)

        base = cli.parse_args(["--arc-dir", str(FIXTURE), "-o", str(self.out), "--browser-bin", str(FAKE_FIREFOX),
                               "--timeout", "20"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = guided.run(base, guided.Prompter(fake_input))
        return code, buf.getvalue()

    def test_asks_which_profile(self):
        # all Arc profiles, Firefox, steps 1 + 3 (bookmarks, vertical tabs), profile 2 (the empty one), folder, go
        code, out = self.guided(["1", "1", "1 3", "2", "", ""])
        self.assertEqual(code, 0, out)
        self.assertIn("Firefox has more than one profile", out)
        self.assertIn("1. default-release (aaa.default-release, opens by default, 1 bookmark)", out)
        self.assertIn("2. default (bbb.default, no bookmarks)", out)
        self.assertIn("set up in Firefox (profile default):", out)
        chosen = self.root / "Profiles" / "bbb.default"
        self.assertTrue(prefs.read_prefs(chosen / "prefs.js")["sidebar.verticalTabs"])
        self.assertFalse((self.root / "Profiles" / "aaa.default-release" / "prefs.js").exists())
        self.assertNotIn("already has", out)  # the chosen profile has no bookmarks of its own

    def test_default_is_the_one_firefox_opens(self):
        code, out = self.guided(["1", "1", "3", "", "", ""])
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "Profiles" / "aaa.default-release" / "prefs.js").exists())

    def test_picked_profile_still_asks_to_quit_firefox(self):
        self.system.running.add("firefox")
        code, out = self.guided(["1", "1", "3", "2", "", "", "y"])  # last "y": quit Firefox
        self.assertEqual(code, 0, out)
        self.assertEqual(self.system.quit_calls, ["firefox"])


if __name__ == "__main__":
    import unittest
    unittest.main()
