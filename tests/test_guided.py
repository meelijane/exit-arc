"""The question-and-answer flow (exit-arc with no options), with scripted answers."""
import io
import json
from contextlib import redirect_stdout

from fake_firefox import add, create_places
from helpers import FAKE_FIREFOX, FIXTURE, SandboxTest

from exit_arc import cli, guided, mozlz4, prefs, zen


class GuidedTests(SandboxTest):
    def guided(self, answers, *argv):
        """Run the flow; `answers` are typed replies in order. Running out of answers = Ctrl+D."""
        replies = list(answers)
        self.prompts = []

        def fake_input(prompt):
            self.prompts.append(prompt)
            if not replies:
                raise EOFError
            return replies.pop(0)

        base = cli.parse_args(["--arc-dir", str(FIXTURE), "-o", str(self.out), *argv])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = guided.run(base, guided.Prompter(fake_input))
        self.left = replies
        return code, buf.getvalue()

    def zen_args(self):
        return ("--browser-profile", str(self.profile()), "--browser-bin", str(FAKE_FIREFOX), "--timeout", "20")

    # 1 = All profiles; 4 = just files; "" = default folder; "" = go ahead
    def test_files_only(self):
        code, out = self.guided(["1", "4", "", ""])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.left, [])
        self.assertIn("Found in Arc:", out)
        self.assertEqual(out.count("Favourites:"), 2)  # summary shown once per profile, not repeated by cli.run
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         ["arc-bookmarks.html", "arc-export.json", "arc-sidebar.md", "arc-tabs.csv"])
        self.assertEqual(self.amo.queries, [])
        self.assertIn("Done.", out)

    def test_pick_one_profile(self):
        code, out = self.guided(["3", "4", "", ""])  # 3 = Work
        self.assertEqual(code, 0, out)
        data = json.loads((self.out / "arc-export.json").read_text())
        self.assertEqual([p["name"] for p in data["profiles"]], ["Work"])

    def test_zen_everything_by_default(self):
        code, out = self.guided(["1", "2", "", "", "", "y"], *self.zen_args())  # last "y": open install prompts
        self.assertEqual(code, 0, out)
        self.assertIn("1. Bookmarks", out)
        self.assertNotIn("Vertical tabs:", out.split("What should")[1].split("Where should")[0])  # Zen has them
        p = self.dir / "profile"
        d = mozlz4.read_json(p / zen.SESSION_FILE)
        self.assertEqual(sum(1 for t in d["tabs"] if t.get("zenEssential")), 3)
        self.assertNotIn("Change this", "".join(self.prompts))  # "Go ahead?" was the only confirmation
        self.assertEqual(self.system.opened[0][0], "zen")

    def test_pick_some_steps(self):
        # Firefox; steps 3 (vertical tabs) and 4 (new tab page) only
        code, out = self.guided(["1", "1", "3 4", "", ""], *self.zen_args())
        self.assertEqual(code, 0, out)
        values = prefs.read_prefs(self.dir / "profile" / "prefs.js")
        self.assertTrue(values["sidebar.verticalTabs"])
        self.assertFalse((self.dir / "profile" / "places.sqlite").exists())  # no import was run
        self.assertEqual(self.system.opened, [])

    def test_existing_bookmarks_kept_by_default(self):
        p = self.profile()
        db = create_places(p / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        code, out = self.guided(["1", "1", "1 3", "", "", ""], *self.zen_args())  # "" = keep mine
        self.assertEqual(code, 0, out)
        self.assertIn("already has 1 bookmark of yours", out)
        self.assertIn("Import Bookmarks from HTML", out)
        self.assertTrue(prefs.read_prefs(p / "prefs.js")["sidebar.verticalTabs"])

    def test_existing_bookmarks_replaced_when_chosen(self):
        p = self.profile()
        db = create_places(p / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        code, out = self.guided(["1", "1", "1", "2", "", ""], *self.zen_args())
        self.assertEqual(code, 0, out)
        self.assertIn("Bookmarks: all 10 links", out)
        backup = next(self.out.glob("backup-firefox-*"))
        self.assertIn("https://keep.example.com/", (backup / "bookmarks" / "bookmarks.html").read_text())

    def test_not_installed_offers_files(self):
        self.system.installed.discard("chrome")
        code, out = self.guided(["1", "3", "", "", ""])
        self.assertEqual(code, 0, out)
        self.assertIn("Chrome (not installed)", out)
        self.assertIn("isn't installed", out)
        self.assertTrue((self.out / "arc-tabs.csv").exists())

    def test_bad_answers_ask_again(self):
        code, out = self.guided(["1", "9", "x", "4", "", ""])
        self.assertEqual(code, 0, out)
        self.assertIn("Please type a number from 1 to 4.", out)

    def test_saying_no_changes_nothing(self):
        code, out = self.guided(["1", "2", "", "", "n"], *self.zen_args())
        self.assertEqual(code, 1)
        self.assertIn("Nothing was changed", out)
        self.assertFalse(self.out.exists())
        self.assertEqual(list((self.dir / "profile").iterdir()), [])

    def test_ctrl_d_stops(self):
        code, out = self.guided(["1"])
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())

    def test_no_arguments_starts_guided(self):
        called = []
        real = guided.run
        guided.run = lambda base: called.append(base) or 0
        try:
            self.assertEqual(cli.main([]), 0)
        finally:
            guided.run = real
        self.assertEqual(len(called), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
