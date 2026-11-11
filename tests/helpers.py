"""Shared test helpers. Everything is synthetic; no real browser is ever started."""
import io
import os
import stat
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from exit_arc import browsers, cli, extensions  # noqa: E402

FIXTURE = HERE / "fixtures" / "arc"
FAKE_FIREFOX = HERE / "fake_firefox.py"
os.chmod(FAKE_FIREFOX, os.stat(FAKE_FIREFOX).st_mode | stat.S_IXUSR)


class FakeSystem(browsers.System):
    """Stands in for the OS: records quits and opened URLs, only ever launches fake_firefox.py."""

    def __init__(self):
        self.running = set()
        self.quit_calls = []
        self.opened = []
        self.quit_works = True
        self.installed = {"firefox", "zen", "chrome"}

    def is_installed(self, browser):
        return browser.key in self.installed

    def is_running(self, browser):
        return browser.key in self.running

    def quit(self, browser, timeout=30):
        self.quit_calls.append(browser.key)
        if self.quit_works:
            self.running.discard(browser.key)
        return self.quit_works

    def launch_headless(self, binary, profile):
        if Path(binary).resolve() != FAKE_FIREFOX:
            raise AssertionError(f"tests must not start a real browser ({binary})")
        return super().launch_headless(binary, profile)

    def open_urls(self, browser, urls, binary=None):
        self.opened.append((browser.key, list(urls)))

    def sleep(self, seconds):
        time.sleep(min(seconds, 0.1))


class FakeAMO:
    """addons.mozilla.org stand-in: {search term: [results]}."""

    def __init__(self, results=None):
        self.results = results or {}
        self.queries = []

    def search(self, name):
        self.queries.append(name)
        return self.results.get(name, [])


AMO_RESULTS = {
    "Tab Notes Example": [
        {"slug": "tab-notes-copycat", "name": {"en-US": "Tab Notes Example Pro"}, "authors": [{"name": "Someone Else"}],
         "homepage": {"url": {"en-US": "https://copycat.example"}}},
        {"slug": "tab-notes-example", "name": {"en-US": "Tab Notes Example"}, "authors": [{"name": "Example Labs"}],
         "homepage": {"url": {"en-US": "https://tabnotes.example"}}},
    ],
    "Snapshot Helper": [
        {"slug": "snapshot-helper-free", "name": {"en-US": "Snapshot Helper Free"}, "authors": [{"name": "Unrelated"}]},
    ],
}


class SandboxTest(unittest.TestCase):
    """Temp dir + fake OS + fake AMO for every test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.out = self.dir / "out"
        self.system = FakeSystem()
        self._real_system = browsers.system
        browsers.system = self.system
        self.amo = FakeAMO(AMO_RESULTS)
        self._real_amo = extensions.AMO
        extensions.AMO = lambda *a, **k: self.amo

    def tearDown(self):
        browsers.system = self._real_system
        extensions.AMO = self._real_amo
        self._tmp.cleanup()

    def profile(self, name="profile"):
        p = self.dir / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def cli(self, *argv, answers=None):
        """Run the CLI. `answers` is a list of replies to questions (default: refuse everything)."""
        asked = []
        replies = list(answers or [])

        def ask(question, quitting=False):
            asked.append(question)
            return replies.pop(0) if replies else False

        args = cli.parse_args(["--arc-dir", str(FIXTURE), "-o", str(self.out), *argv])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.run(args, ask=ask)
        self.asked = asked
        return code, buf.getvalue()


def titles(nodes):
    return [n["title"] for n in nodes]


def find(nodes, title):
    return next(n for n in nodes if n["title"] == title)


def flat_links(nodes):
    out = []
    for n in nodes:
        out += [n["url"]] if n["type"] == "link" else flat_links(n["children"])
    return out
