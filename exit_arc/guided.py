"""The question-and-answer flow you get when you run `exit-arc` with no options."""

import copy
from pathlib import Path

from . import ToolError, arc, browsers, cli, exporters, extensions, gecko
from .browsers import BROWSERS

DEFAULT_OUT = Path("~/Desktop/arc-export")

# What each step is called in the questions, and what it does in each browser.
LABELS = {
    "import": "Bookmarks",
    "spaces": "Spaces",
    "pin-favourites": "Favourites",
    "vertical-tabs": "Vertical tabs",
    "clean-newtab": "New tab page",
    "extensions": "Extensions",
    "default-browser": "Default browser",
}
DESCRIPTIONS = {
    ("import", "firefox"): "your Favourites and a folder per space on the bookmarks toolbar",
    ("import", "zen"): "your Favourites and a folder per space on the bookmarks toolbar",
    ("import", "chrome"): "a folder per space on the bookmarks bar, keeping yours (experimental)",
    ("spaces", "zen"): "each Arc space as a Zen space, with its pinned tabs and folders",
    ("pin-favourites", "firefox"): "your Favourites as pinned tabs (Firefox will also reopen your last tabs)",
    ("pin-favourites", "zen"): "your Favourites as Zen Essentials",
    ("vertical-tabs", "firefox"): "tabs in a sidebar on the left, like Arc",
    ("clean-newtab", "firefox"): "no sponsored shortcuts, stories or widgets on new tabs",
    ("clean-newtab", "zen"): "no sponsored shortcuts, stories or widgets on new tabs",
    ("extensions", "firefox"): "look up your extensions on addons.mozilla.org (only their names are sent), "
                               "then open install prompts you approve",
    ("extensions", "zen"): "look up your extensions on addons.mozilla.org (only their names are sent), "
                           "then open install prompts you approve",
    ("extensions", "chrome"): "open each extension's Chrome Web Store page",
    ("default-browser", "firefox"): "make Firefox your default browser (macOS asks you to confirm)",
    ("default-browser", "zen"): "make Zen your default browser (macOS asks you to confirm)",
    ("default-browser", "chrome"): "make Chrome your default browser (macOS asks you to confirm)",
}
FLAGS = {"import": "do_import", "spaces": "spaces", "pin-favourites": "pin_favourites",
         "vertical-tabs": "vertical_tabs", "clean-newtab": "clean_newtab", "extensions": "extensions",
         "default-browser": "default_browser"}


class Cancelled(Exception):
    pass


class Prompter:
    """Asks questions on the terminal. Tests pass their own `input_fn`."""

    def __init__(self, input_fn=input, log=print):
        self.input_fn = input_fn
        self.log = log

    def read(self, prompt):
        try:
            return self.input_fn(prompt).strip()
        except EOFError:
            raise Cancelled()

    def menu(self, question, options, default=None):
        """options: [(key, label)]. Returns the chosen key."""
        self.log(f"\n{question}")
        for i, (_, label) in enumerate(options, 1):
            self.log(f"  {i}. {label}")
        keys = [k for k, _ in options]
        hint = f" [{keys.index(default) + 1}]" if default in keys else ""
        while True:
            reply = self.read(f"Type a number{hint}: ")
            if not reply and default in keys:
                return default
            if reply.isdigit() and 1 <= int(reply) <= len(options):
                return keys[int(reply) - 1]
            self.log(f"Please type a number from 1 to {len(options)}.")

    def many(self, question, options):
        """Pick any of options. Enter = all of them, 0 = none."""
        self.log(f"\n{question}")
        for i, (_, label) in enumerate(options, 1):
            self.log(f"  {i}. {label}")
        keys = [k for k, _ in options]
        while True:
            reply = self.read("Press Enter for all of them, or type the numbers you want (like 1 3), or 0 for none: ")
            if not reply:
                return keys
            parts = reply.replace(",", " ").split()
            if parts == ["0"]:
                return []
            if all(p.isdigit() and 1 <= int(p) <= len(options) for p in parts):
                picked = {int(p) for p in parts}
                return [k for i, k in enumerate(keys, 1) if i in picked]
            self.log(f"Please type numbers from 1 to {len(options)}, separated by spaces.")

    def text(self, question, default):
        reply = self.read(f"\n{question} [{default}]: ")
        return reply or str(default)

    def confirm(self, question, default=False):
        reply = self.read(f"{question} {'[Y/n]' if default else '[y/N]'} ").lower()
        if not reply:
            return default
        return reply in ("y", "yes")


def run(base_args, prompter=None, log=print):
    """Ask what to do, then run it. `base_args` is parse_args([]) (tests add --arc-dir etc.)."""
    p = prompter or Prompter(log=log)
    try:
        return _run(base_args, p, log)
    except Cancelled:
        log("\nStopped. Nothing was changed.")
        return 1


def _run(base, p, log):
    log("exit-arc moves your Arc sidebar to another browser, or saves it as files.")
    log("It only reads Arc's files. Press Ctrl+C to stop at any time.")

    export = arc.read_arc(base.arc_dir)
    arc.add_extensions(export, base.arc_dir)
    args = copy.copy(base)
    args.arc_profile = None

    # 1. Which Arc profile (only asked when there's more than one)
    if len(export["profiles"]) > 1:
        options = [("all", "All of them")] + [(pr["directory"], pr["name"]) for pr in export["profiles"]]
        pick = p.menu("You have more than one Arc profile. Which should come over?", options, default="all")
        if pick != "all":
            args.arc_profile = [pick]
            export = arc.filter_profiles(export, args.arc_profile)

    log("\nFound in Arc:")
    for line in exporters.summary(export):
        log(f"  {line}")
    log(f"  Extensions: {len(extensions.unique_extensions(export))}")

    # 2. Which browser
    options = []
    for key in ("firefox", "zen", "chrome"):
        b = BROWSERS[key]
        options.append((key, b.label + ("" if browsers.system.is_installed(b) else " (not installed)")))
    options.append(("files", "No browser: just save the files"))
    choice = p.menu("Where are you moving to?", options)
    target = BROWSERS.get(choice)
    if target and not browsers.system.is_installed(target):
        log(f"\n{target.label} isn't installed. Install it, open it once and quit it, then run exit-arc again.")
        if not p.confirm("Save the files for now?", default=True):
            raise Cancelled()
        target = None

    # 3. What to set up there
    steps = []
    keep_bookmarks = False
    if target:
        available = [s for s in cli.STEPS if cli.supported(s, target.key)]
        bundle = browsers.system.bundle_id(target)
        if not bundle or (browsers.system.default_browser() or "").lower() == bundle.lower():
            available.remove("default-browser")  # already the default, or not something we can set
        steps = p.many(f"What should exit-arc set up in {target.label}?",
                       [(s, f"{LABELS[s]}: {DESCRIPTIONS[(s, target.key)]}") for s in available])
        if [s for s in steps if s not in cli.OUTSIDE_PROFILE]:
            try:
                profile = cli.find_profile(args, target, lambda *_: None)
                if "import" in steps and target.engine == "gecko":
                    _, mine = gecko.existing_bookmarks(profile)
                    if mine:
                        keep_bookmarks = _ask_about_bookmarks(p, target, mine, args)
                        if keep_bookmarks:
                            steps.remove("import")
            except ToolError as e:
                log(f"\n{e}")
                if not p.confirm("Save the files for now?", default=True):
                    raise Cancelled()
                target, steps = None, []

    # 4. Remove Arc afterwards? (never part of "all of them")
    remove = None
    if browsers.system.app_path(browsers.ARC):
        remove = p.menu("When it's done, should exit-arc remove Arc from this Mac? It goes to the Trash, "
                        "so you can put it back.",
                        [("no", "No, keep Arc"),
                         ("app", "Remove the Arc app, keep its data (history, passwords, cookies)"),
                         ("all", "Remove the Arc app and its data")], default="no")
        remove = None if remove == "no" else remove
    args.remove_arc = remove

    # 5. Where the files go
    out = Path(p.text("Where should the files go?", base.out if base.out != Path.cwd() else DEFAULT_OUT))
    args.out = out.expanduser()

    # 6. Check, then go
    log("\nReady to:")
    log(f"  save your sidebar as files in {args.out}")
    if steps:
        log(f"  set up in {target.label}: " + ", ".join(LABELS[s] for s in steps))
        if [s for s in steps if s not in cli.OUTSIDE_PROFILE]:
            log(f"  ({target.label} needs to be closed; everything changed is backed up first)")
    if remove:
        log("  then move " + ("the Arc app" if remove == "app" else "the Arc app and its data")
            + " to the Trash (it asks once more first)")
    if not p.confirm("Go ahead?", default=True):
        raise Cancelled()

    args.to = target.key if target else "firefox"
    args.all = False
    for step, flag in FLAGS.items():
        setattr(args, flag, step in steps)
    args.guided = True
    args.confirmed = True
    log("")
    code = cli.run(args, ask=lambda q, quitting=False: p.confirm(q), log=log)
    if code:
        return code

    html = args.out / exporters.FILENAMES["html"]
    if keep_bookmarks or (target and not steps):
        log(f"\nTo add the bookmarks to {target.label} yourself:\n  " + cli.MANUAL_IMPORT[target.key].format(html=html))
    log(f"\nDone. Open {args.out / exporters.FILENAMES['md']} to see everything that was in Arc.")
    if steps:
        log(f"Open {target.label} to see the rest.")
    return 0


def _ask_about_bookmarks(p, target, mine, args):
    """The automatic import replaces every bookmark. Returns True to keep them (import by hand instead)."""
    choice = p.menu(f"{target.label} already has {exporters.plural(mine, 'bookmark')} of yours. "
                    "Adding bookmarks automatically replaces all of them.",
                    [("keep", "Keep mine: I'll import the bookmarks file myself (exit-arc shows you how)"),
                     ("replace", "Replace mine (a backup is saved first)")], default="keep")
    args.replace_existing = choice == "replace"
    return choice == "keep"
