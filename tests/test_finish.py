"""Default browser and removing Arc: both go through the fake OS, so nothing real changes."""
import io
from contextlib import redirect_stdout

from fake_firefox import add, create_places
from helpers import FAKE_FIREFOX, FIXTURE, SandboxTest

from exit_arc import cli, guided


class DefaultBrowserTests(SandboxTest):
    def test_sets_default(self):
        code, out = self.cli("--to", "zen", "--default-browser", answers=[])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.system.default_requests, ["app.zen-browser.zen"])
        self.assertIn("Zen is now your default browser.", out)
        self.assertIn("macOS is asking", out)

    def test_already_default(self):
        code, out = self.cli("--to", "firefox", "--default-browser")
        self.assertIn("Firefox already is", out)
        self.assertFalse(hasattr(self.system, "default_requests"))

    def test_user_keeps_old_browser(self):
        self.system.accept_default = False
        args = cli.parse_args(["--to", "chrome"])
        lines = []
        cli.make_default(args, cli.BROWSERS["chrome"], lines.append, wait=3)
        self.assertIn("didn't change", lines[-1])

    def test_dry_run(self):
        code, out = self.cli("--to", "zen", "--default-browser", "--dry-run")
        self.assertIn("Would ask macOS", out)
        self.assertFalse(hasattr(self.system, "default_requests"))

    def test_runs_without_touching_the_profile(self):
        code, out = self.cli("--to", "chrome", "--default-browser")
        self.assertEqual(code, 0, out)
        self.assertNotIn("profile:", out)


class RemoveArcTests(SandboxTest):
    def setUp(self):
        super().setUp()
        self.app = self.dir / "Applications" / "Arc.app"
        self.app.mkdir(parents=True)
        self.system.arc_app = self.app

    def trashed(self):
        return getattr(self.system, "trashed", [])

    def test_app_only(self):
        code, out = self.cli("--remove-arc", "app", answers=[True])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.trashed(), [self.app])
        self.assertEqual(self.asked, ["Move Arc to the Trash now?"])
        self.assertIn("Arc is in the Trash.", out)
        self.assertTrue((self.out / "arc-sidebar.md").exists())  # files were written first

    def test_all_includes_data(self):
        code, out = self.cli("--remove-arc", "all", answers=[True])
        self.assertIn(self.app, self.trashed())
        self.assertIn(FIXTURE, self.trashed())
        self.assertIn("history, passwords and cookies were not moved", out)

    def test_declined(self):
        code, out = self.cli("--remove-arc", "app", answers=[False])
        self.assertEqual(self.trashed(), [])
        self.assertIn("left as it is", out)

    def test_dry_run_asks_nothing(self):
        code, out = self.cli("--remove-arc", "all", "--dry-run")
        self.assertEqual(self.asked, [])
        self.assertEqual(self.trashed(), [])

    def test_quits_running_arc_first(self):
        self.system.running.add("arc")
        code, out = self.cli("--remove-arc", "app", answers=[True, True])
        self.assertEqual(self.system.quit_calls, ["arc"])
        self.assertEqual(self.trashed(), [self.app])

    def test_not_after_a_failure(self):
        p = self.profile()
        db = create_places(p / "places.sqlite")
        add(db, 3, {"type": "link", "title": "Keep", "url": "https://keep.example.com/"})
        db.commit()
        db.close()
        code, out = self.cli("--to", "firefox", "--import", "--browser-profile", str(p), "--remove-arc", "app",
                             answers=[True, True])
        self.assertEqual(code, 3)
        self.assertEqual(self.trashed(), [])

    def test_never_without_arc_app(self):
        self.system.arc_app = None
        code, out = self.cli("--remove-arc", "app", answers=[True])
        self.assertIn("nothing to remove", out)
        self.assertEqual(self.trashed(), [])


class GuidedFinishTests(SandboxTest):
    def guided(self, answers, *argv):
        replies = list(answers)

        def fake_input(prompt):
            if not replies:
                raise EOFError
            return replies.pop(0)

        base = cli.parse_args(["--arc-dir", str(FIXTURE), "-o", str(self.out), *argv])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = guided.run(base, guided.Prompter(fake_input))
        return code, buf.getvalue()

    def test_default_browser_hidden_when_already_default(self):
        code, out = self.guided(["1", "1", "0", "", ""])  # Firefox is the fake default
        self.assertEqual(code, 0, out)
        self.assertNotIn("Default browser:", out)

    def test_default_browser_offered(self):
        code, out = self.guided(["1", "3", "3", "", ""])  # Chrome: 1 Bookmarks, 2 Extensions, 3 Default browser
        self.assertEqual(code, 0, out)
        self.assertIn("3. Default browser: make Chrome your default browser", out)
        self.assertEqual(self.system.default_requests, ["com.google.Chrome"])

    def test_remove_question_defaults_to_no(self):
        self.system.arc_app = self.dir / "Arc.app"
        code, out = self.guided(["1", "4", "", "", ""])
        self.assertEqual(code, 0, out)
        self.assertIn("should exit-arc remove Arc", out)
        self.assertFalse(hasattr(self.system, "trashed"))

    def test_remove_app_asks_again(self):
        self.system.arc_app = self.dir / "Arc.app"
        code, out = self.guided(["1", "4", "2", "", "", "y"])
        self.assertEqual(code, 0, out)
        self.assertIn("then move the Arc app to the Trash", out)
        self.assertEqual(self.system.trashed, [self.dir / "Arc.app"])

    def test_no_remove_question_without_arc_app(self):
        code, out = self.guided(["1", "4", "", ""])
        self.assertEqual(code, 0, out)
        self.assertNotIn("remove Arc", out)


if __name__ == "__main__":
    import unittest
    unittest.main()
