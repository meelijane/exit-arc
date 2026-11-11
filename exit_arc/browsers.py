"""The target browsers, and every place exit-arc touches the operating system.

Everything that starts, quits or checks a real browser goes through `system`,
so tests can swap it for a fake and never launch anything real.
"""

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import ToolError

SUPPORT = Path.home() / "Library" / "Application Support"


@dataclass(frozen=True)
class Browser:
    key: str          # --to value
    label: str        # shown to people
    engine: str       # "gecko" or "chromium"
    app_name: str     # for `open -a` / AppleScript
    process: str      # main process name (pgrep -x)
    bundles: tuple    # .app names to look for
    executable: str   # binary inside Contents/MacOS
    data_root: Path   # where profiles live

    def find_app(self):
        for base in (Path("/Applications"), Path.home() / "Applications"):
            for bundle in self.bundles:
                if (base / bundle).exists():
                    return base / bundle
        return None

    def find_bin(self):
        app = self.find_app()
        if app and (app / "Contents" / "MacOS" / self.executable).exists():
            return app / "Contents" / "MacOS" / self.executable
        which = shutil.which(self.executable)
        if which:
            return Path(which)
        raise ToolError(f"Couldn't find {self.label}. Install it, or pass --browser-bin.")


FIREFOX = Browser("firefox", "Firefox", "gecko", "Firefox", "firefox",
                  ("Firefox.app", "Firefox Developer Edition.app", "Firefox Nightly.app"), "firefox",
                  SUPPORT / "Firefox" if sys.platform == "darwin" else Path.home() / ".mozilla" / "firefox")
ZEN = Browser("zen", "Zen", "gecko", "Zen", "zen", ("Zen.app", "Zen Browser.app"), "zen", SUPPORT / "zen")
CHROME = Browser("chrome", "Chrome", "chromium", "Google Chrome", "Google Chrome", ("Google Chrome.app",),
                 "Google Chrome", SUPPORT / "Google" / "Chrome")

BROWSERS = {b.key: b for b in (FIREFOX, ZEN, CHROME)}


class System:
    """Real OS operations. Tests replace `browsers.system` with a fake."""

    def is_running(self, browser):
        try:
            r = subprocess.run(["pgrep", "-x", browser.process], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return False
        return r.returncode == 0

    def quit(self, browser, timeout=30):
        """Ask the browser to quit like Cmd+Q would, then wait for it to exit."""
        subprocess.run(["osascript", "-e", f'tell application "{browser.app_name}" to quit'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running(browser):
                time.sleep(1)  # let it finish writing its files
                return True
            time.sleep(0.5)
        return False

    def is_installed(self, browser):
        return browser.find_app() is not None or shutil.which(browser.executable) is not None

    def launch_headless(self, binary, profile):
        return subprocess.Popen([str(binary), "--headless", "--no-remote", "--profile", str(profile)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_urls(self, browser, urls, binary=None):
        """Open URLs in the browser's normal window (it shows its own install prompts)."""
        app = browser.find_app()
        target = str(app) if app else browser.app_name
        subprocess.run(["open", "-a", target, *urls], check=False)

    def sleep(self, seconds):
        time.sleep(seconds)


system = System()


def ensure_closed(browser, ask, allow_quit=False, log=print):
    """Make sure `browser` isn't running. Offers to quit it (asking first)."""
    if not system.is_running(browser):
        return
    question = (f"{browser.label} is open. Quit it now? It saves your windows first, but tabs only come back "
                f"if it's set to restore your previous session.")
    if allow_quit or ask(question):
        log(f"Quitting {browser.label} ...")
        if system.quit(browser):
            return
        raise ToolError(f"{browser.label} didn't quit. Quit it yourself (Cmd+Q) and run this again.")
    raise ToolError(f"{browser.label} is running. Quit it (Cmd+Q) and run this again.")
