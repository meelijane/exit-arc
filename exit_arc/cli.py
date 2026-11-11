"""exit-arc command line."""

import argparse
import sys
import time
from pathlib import Path

from . import ToolError, __version__, arc, browsers, chrome, exporters, extensions, gecko, prefs, zen
from .browsers import BROWSERS

STEPS = ("import", "spaces", "pin-favourites", "vertical-tabs", "clean-newtab", "extensions", "default-browser")
# Steps that don't change the browser profile (so they don't need it closed).
OUTSIDE_PROFILE = ("extensions", "default-browser")

# What each target can do. (level, note); level is "yes", "experimental", "built in" or "no".
CAPABILITIES = {
    "import": {
        "firefox": ("yes", "favourites + a toolbar folder per space; REPLACES the profile's bookmarks"),
        "zen": ("yes", "same as Firefox; REPLACES the profile's bookmarks"),
        "chrome": ("experimental", "adds folders to the bookmarks bar, keeps yours"),
    },
    "spaces": {
        "firefox": ("no", "Firefox has no spaces; --import makes a toolbar folder per space"),
        "zen": ("yes", "real Zen spaces with your pinned tabs and folders"),
        "chrome": ("no", "Chrome has no spaces; --import makes a folder per space"),
    },
    "pin-favourites": {
        "firefox": ("yes", "real pinned tabs; also turns on 'Open previous windows and tabs'"),
        "zen": ("yes", "favourites become Zen Essentials"),
        "chrome": ("no", "Chrome's session files are an undocumented format"),
    },
    "vertical-tabs": {
        "firefox": ("yes", "tabs in a sidebar on the left"),
        "zen": ("built in", "Zen already has vertical tabs"),
        "chrome": ("experimental", "turns on Chrome's vertical tabs"),
    },
    "clean-newtab": {
        "firefox": ("yes", "removes sponsored shortcuts, stories and widgets"),
        "zen": ("yes", "same as Firefox"),
        "chrome": ("no", ""),
    },
    "extensions": {
        "firefox": ("yes", "finds official add-ons; you approve each install in Firefox"),
        "zen": ("yes", "same add-ons as Firefox; you approve each install"),
        "chrome": ("yes", "opens each extension's Web Store page; you click Add"),
    },
    "default-browser": {
        "firefox": ("yes", "macOS asks you to confirm"),
        "zen": ("yes", "macOS asks you to confirm"),
        "chrome": ("yes", "macOS asks you to confirm"),
    },
}

STEP_LABELS = {
    "import": "Bookmarks (favourites + spaces)",
    "spaces": "Spaces as real spaces",
    "pin-favourites": "Favourites as pinned tabs",
    "vertical-tabs": "Vertical tabs",
    "clean-newtab": "New tab page cleanup",
    "extensions": "Extensions",
    "default-browser": "Default browser",
}

MANUAL_IMPORT = {
    "firefox": "Firefox > Bookmarks > Manage Bookmarks (Shift+Cmd+O) > Import and Backup > "
               "Import Bookmarks from HTML... > choose {html}",
    "zen": "Zen > Bookmarks > Manage Bookmarks (Shift+Cmd+O) > Import and Backup > "
           "Import Bookmarks from HTML... > choose {html}",
    "chrome": "Chrome > Bookmarks and Lists > Import Bookmarks and Settings > "
              "Bookmarks HTML File > choose {html}",
}


def supported(step, target):
    return CAPABILITIES[step][target][0] in ("yes", "experimental")


def capability_table():
    targets = ("firefox", "zen", "chrome")
    width = max(len(v) for v in STEP_LABELS.values())
    lines = [f'{"":{width}}  ' + "".join(f"{BROWSERS[t].label:<14}" for t in targets) + "Export only"]
    for step in STEPS:
        cells = "".join(f"{CAPABILITIES[step][t][0]:<14}" for t in targets)
        export_only = {"import": "HTML, CSV, Markdown, JSON", "extensions": "listed in Markdown/JSON"}.get(step, "-")
        lines.append(f"{STEP_LABELS[step]:<{width}}  {cells}{export_only}")
    lines.append(f'{"History, passwords, cookies":<{width}}  ' + "".join(f'{"no":<14}' for _ in targets) + "-")
    return lines


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="exit-arc",
        description="Export your Arc sidebar to files, and optionally move it into Firefox, Zen or Chrome. "
                    "Run exit-arc with no options to be asked questions instead.",
        epilog="History, passwords, cookies and extension data are never touched. "
               "Run with --capabilities to see what each browser supports.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-n", "--dry-run", action="store_true", help="show what would happen; write and change nothing")
    p.add_argument("-o", "--out", type=Path, default=Path.cwd(), help="output folder (default: current folder)")
    p.add_argument("--format", default="csv,md,json,html",
                   help="files to write, comma-separated from csv,md,json,html (default: all)")
    p.add_argument("--layout", choices=("toolbar", "folder"), default="toolbar",
                   help="bookmarks layout: toolbar (default) = favourites + a toolbar folder per space; "
                        "folder = one 'Arc' folder in the bookmarks menu")
    p.add_argument("--include-unpinned", action="store_true", help="also bookmark open, unpinned tabs")
    p.add_argument("--arc-dir", type=Path, default=arc.DEFAULT_ARC_DIR, help="Arc data folder (default: %(default)s)")
    p.add_argument("--arc-profile", action="append", metavar="NAME", help="only this Arc profile; repeatable")
    p.add_argument("--capabilities", action="store_true", help="show what each browser supports, then exit")

    g = p.add_argument_group("moving into a browser (the browser must be closed)")
    g.add_argument("--to", choices=sorted(BROWSERS), default="firefox", help="target browser (default: firefox)")
    g.add_argument("--import", dest="do_import", action="store_true", help="bookmarks: favourites + one folder per space")
    g.add_argument("--spaces", action="store_true", help="Zen: recreate Arc spaces with their pinned tabs and folders")
    g.add_argument("--pin-favourites", action="store_true",
                   help="favourites as pinned tabs (Firefox) or Essentials (Zen)")
    g.add_argument("--vertical-tabs", action="store_true", help="Firefox: turn on vertical tabs")
    g.add_argument("--clean-newtab", action="store_true", help="remove sponsored shortcuts and widgets from new tabs")
    g.add_argument("--extensions", action="store_true",
                   help="look up your Arc extensions for the target and offer to install them "
                        "(sends extension names to addons.mozilla.org for Firefox/Zen)")
    g.add_argument("--default-browser", action="store_true",
                   help="make the target your default browser (macOS asks you to confirm)")
    g.add_argument("--all", action="store_true", help="every step the target browser supports")
    g.add_argument("--remove-arc", choices=("app", "all"),
                   help="when everything else worked, move Arc to the Trash: 'app' = just the app, "
                        "'all' = the app and its data (asks first, even with --yes)")
    g.add_argument("--browser-profile", "--firefox-profile", dest="browser_profile", type=Path,
                   help="profile to change: its folder or its name (default: the one the browser opens)")
    g.add_argument("--browser-bin", "--firefox-bin", dest="browser_bin", type=Path, help="browser executable")
    g.add_argument("--replace-existing", action="store_true",
                   help="let --import replace a Firefox/Zen profile's existing bookmarks (backed up first)")
    g.add_argument("--no-backup", action="store_true", help="don't back up files before changing them")
    g.add_argument("--no-show-toolbar", dest="show_toolbar", action="store_false",
                   help="don't switch the bookmarks toolbar to 'always show'")
    g.add_argument("--quit-browser", action="store_true", help="quit the target browser without asking if it's open")
    g.add_argument("-y", "--yes", action="store_true", help="answer yes to questions (except quitting the browser)")
    g.add_argument("--timeout", type=int, default=90, help="seconds to wait for the browser (default: %(default)s)")
    return p.parse_args(argv)


def make_ask(assume_yes):
    def ask(question, quitting=False):
        if assume_yes and not quitting:
            return True
        try:
            return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            return False
    return ask


def chosen_steps(args):
    if args.all:
        return list(STEPS)
    picked = {"import": args.do_import, "spaces": args.spaces, "pin-favourites": args.pin_favourites,
              "vertical-tabs": args.vertical_tabs, "clean-newtab": args.clean_newtab, "extensions": args.extensions,
              "default-browser": args.default_browser}
    return [s for s in STEPS if picked[s]]


def _favourite_links(export):
    def flat(nodes):
        for n in nodes:
            if n["type"] == "link":
                yield (n["url"], n["title"])
            else:
                yield from flat(n["children"])
    return [link for p in export["profiles"] for link in flat(p["favourites"])]


def run(args, ask=None, log=print):
    ask = ask or make_ask(args.yes)
    if args.capabilities:
        for line in capability_table():
            log(line)
        return 0
    formats = exporters.parse_formats(args.format)
    target = BROWSERS[args.to]
    steps = chosen_steps(args)

    export = arc.filter_profiles(arc.read_arc(args.arc_dir), args.arc_profile)
    arc.add_extensions(export, args.arc_dir)
    lookup = "extensions" in steps and target.engine == "gecko"
    if lookup and extensions.unique_extensions(export):
        log("Looking up your extensions on addons.mozilla.org (only their names are sent) ...")
    extensions.annotate(export, lookup=lookup, log=log)

    if not getattr(args, "guided", False):  # the guided flow has already shown this
        for line in exporters.summary(export, args.include_unpinned):
            log(line)
        log(f"Extensions: {len(extensions.unique_extensions(export))}")

    paths = {f: args.out / exporters.FILENAMES[f] for f in formats}
    html_text = exporters.build_html(export, args.layout, args.include_unpinned)
    if args.dry_run:
        log("\n[dry run] Would write: " + ", ".join(str(p) for p in paths.values()))
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        for fmt, path in paths.items():
            path.write_text(exporters.render(export, fmt, args.layout, args.include_unpinned), encoding="utf-8")
            log(f"Wrote {path}")
    html_path = paths.get("html")

    if not steps:
        if html_path and not args.dry_run and not getattr(args, "guided", False):
            log(f"\nTo add these to {target.label} by hand: " + MANUAL_IMPORT[target.key].format(html=html_path))
            log("Or let exit-arc do it: see --help (e.g. --import, --all).")
        code = 0
    else:
        code = move(args, export, target, steps, html_text, html_path, ask, log)
    if code == 0 and getattr(args, "remove_arc", None):
        remove_arc(args, ask, log)
    return code


def remove_arc(args, ask, log):
    """Move Arc (and, with 'all', its data) to the Trash. Always asks, even with --yes."""
    app = browsers.system.app_path(browsers.ARC)
    paths = [app] if app else []
    if args.remove_arc == "all":
        data = browsers.arc_data_paths()
        if Path(args.arc_dir).expanduser() not in data:
            data.append(Path(args.arc_dir).expanduser())
        paths += [p for p in data if p.exists()]
    if not paths:
        log("\nArc: nothing to remove (Arc.app isn't in Applications).")
        return
    log("\nRemoving Arc. These go to the Trash, so you can put them back until you empty it:")
    for p in paths:
        log(f"  {p}")
    if args.remove_arc == "all":
        log("Arc's history, passwords and cookies were not moved to the new browser. If you want them, "
            "keep Arc's data (remove just the app) or export them from Arc first.")
    else:
        log("Arc's data stays on this Mac, so the files you exported can be made again.")
    if args.dry_run:
        log("[dry run] Arc was not removed.")
        return
    if not ask("Move Arc to the Trash now?", quitting=True):
        log("Arc was left as it is.")
        return
    browsers.ensure_closed(browsers.ARC, lambda q: ask(q, quitting=True), args.quit_browser, log)
    failed = [p for p in paths if not browsers.system.trash(p)]
    if failed:
        log("Couldn't move these to the Trash; drag them there yourself:")
        for p in failed:
            log(f"  {p}")
    else:
        log("Arc is in the Trash.")


def move(args, export, target, steps, html_text, html_path, ask, log):
    guided = getattr(args, "guided", False)  # the questions already showed the plan
    if not guided:
        log(f"\nPlan for {target.label}:")
    todo = []
    for step in steps:
        level, note = CAPABILITIES[step][target.key]
        if guided:
            todo += [step] if level in ("yes", "experimental") else []
        elif level in ("yes", "experimental"):
            todo.append(step)
            log(f"  {STEP_LABELS[step]}: will do" + (" (experimental)" if level == "experimental" else "")
                + (f" - {note}" if note else ""))
        else:
            log(f"  {STEP_LABELS[step]}: skipped - " + (f"{level}: {note}" if note else level))
    if not todo:
        return 0

    # Extensions-only runs don't need the profile at all.
    profile_steps = [s for s in todo if s not in OUTSIDE_PROFILE]
    profile = None
    if profile_steps:
        profile = find_profile(args, target, log)
        log(f"\n{target.label} profile: {profile}")
        problem = preflight(args, target, profile, profile_steps, html_path, log, ask)
        if problem:
            return problem
        if args.dry_run:
            log("[dry run] The profile was not changed.")
        elif not getattr(args, "confirmed", False) and not ask(f"Change this {target.label} profile now?"):
            log("Cancelled. Nothing was changed.")
            return 1
        else:
            backups = None if args.no_backup else args.out / time.strftime(f"backup-{target.key}-%Y%m%d-%H%M%S")
            code = apply_profile_steps(args, export, target, profile, profile_steps, html_text, html_path,
                                       backups, log)
            if backups and backups.exists():
                log(f"Backups of everything changed: {backups}")
            if code:
                return code
    if "extensions" in todo:
        offer_extensions(args, export, target, ask, log)
    if "default-browser" in todo:
        make_default(args, target, log)
    return 0


def make_default(args, target, log, wait=60):
    """Ask macOS to make `target` the default browser, then report what the user chose."""
    system = browsers.system
    bundle = system.bundle_id(target)
    if not bundle:
        log(f"\nDefault browser: couldn't find {target.label}'s app, so this was skipped.")
        return
    if (system.default_browser() or "").lower() == bundle.lower():
        log(f"\nDefault browser: {target.label} already is.")
        return
    if args.dry_run:
        log(f"\n[dry run] Would ask macOS to make {target.label} your default browser.")
        return
    if not system.set_default_browser(bundle):
        log(f"\nDefault browser: macOS didn't accept the change. Set it in System Settings > Desktop & Dock > "
            "Default web browser.")
        return
    log(f"\nmacOS is asking whether to make {target.label} your default browser. Choose \"Use {target.label}\".")
    for _ in range(wait):
        if (system.default_browser() or "").lower() == bundle.lower():
            log(f"{target.label} is now your default browser.")
            return
        system.sleep(1)
    log(f"Your default browser didn't change. You can set it later in System Settings > Desktop & Dock > "
        "Default web browser.")


def list_profiles(target):
    if target.engine == "chromium":
        return chrome.list_profiles(target.data_root)
    return gecko.list_profiles(target)


def find_profile(args, target, log):
    if args.browser_profile:
        path = Path(args.browser_profile).expanduser()
        if path.is_dir() or path.is_absolute() or "/" in str(args.browser_profile):
            return path
        # Not a folder: treat it as a profile name, like the ones Firefox shows at about:profiles.
        named = [p for p in list_profiles(target) if p["name"].lower() == str(args.browser_profile).lower()]
        if len(named) == 1:
            return named[0]["path"]
        have = ", ".join(p["name"] for p in list_profiles(target)) or "none"
        raise ToolError(f"No {target.label} profile called {args.browser_profile!r}. Found: {have}")
    if target.engine == "chromium":
        return chrome.default_profile(target.data_root)
    profile, note = gecko.default_profile(target)
    if note:
        log(note)
    return profile


def chrome_in_use(profile):
    import os
    lock = Path(profile).parent / "SingletonLock"
    if os.path.islink(lock):
        try:
            pid = int(os.readlink(lock).rsplit("-", 1)[1])
            os.kill(pid, 0)
            return True
        except (IndexError, ValueError, ProcessLookupError):
            return False
        except PermissionError:
            return True
    return False


def preflight(args, target, profile, steps, html_path, log, ask):
    """Checks that must pass before anything changes. Returns an exit code to stop, or None."""
    if not args.dry_run:
        # Only the default profile can belong to the running app; an explicit --browser-profile
        # is checked through its lock file instead (so you can test on a spare profile).
        if not args.browser_profile or getattr(args, "picked_profile", False):
            browsers.ensure_closed(target, lambda q: ask(q, quitting=True), args.quit_browser, log)
    in_use = chrome_in_use(profile) if target.engine == "chromium" else gecko.profile_in_use(profile)
    if in_use:
        raise ToolError(f"{target.label} is using the profile {profile}. Quit {target.label} and run this again.")
    if "import" in steps and target.engine == "gecko":
        total, user = gecko.existing_bookmarks(profile)
        log(f"It has {total} bookmarks ({user} of yours, {total - user} {target.label} defaults).")
        if user and not args.replace_existing:
            log(f"\nThe automatic bookmark import REPLACES all bookmarks in the profile, so nothing was changed.")
            if html_path:
                log("Import by hand instead, which keeps your bookmarks:\n  "
                    + MANUAL_IMPORT[target.key].format(html=html_path))
            log("Or re-run with --replace-existing to back them up and replace them.")
            return 3
        if args.dry_run:
            log(f"[dry run] Would {'back up and ' if total and not args.no_backup else ''}replace them.")
    if "pin-favourites" in steps and target.key == "firefox":
        log("Note: pinned tabs only come back if Firefox restores your previous session, so this also turns on "
            "Settings > General > 'Open previous windows and tabs'.")
    return None


def apply_profile_steps(args, export, target, profile, steps, html_text, html_path, backups, log):
    profile = Path(profile)
    if target.engine == "chromium":
        if "import" in steps:
            warning = chrome.sync_warning(profile)
            if warning:
                log(warning)
            toolbar, menu = exporters.build_tree(export, args.layout, args.include_unpinned)
            added, replaced = chrome.add_bookmarks(profile, toolbar, menu, backups)
            log(f"Added {added} links to Chrome's bookmarks bar"
                + (f" (replacing {replaced} items from an earlier exit-arc run)" if replaced else "") + ".")
            log("This is experimental. If they don't show up, import by hand: "
                + MANUAL_IMPORT["chrome"].format(html=html_path or "arc-bookmarks.html"))
        if "vertical-tabs" in steps:
            if chrome.enable_vertical_tabs(profile, backups):
                log("Vertical tabs: on (experimental). If Chrome still shows tabs along the top, turn vertical tabs "
                    "on in Chrome itself.")
            else:
                log("Vertical tabs: already on.")
        return 0

    code = 0
    if "import" in steps:
        total, _ = gecko.existing_bookmarks(profile)
        if total and backups:
            gecko.backup_bookmarks(profile, backups / "bookmarks")
        binary = args.browser_bin or target.find_bin()
        urls = exporters.exported_urls(export, args.include_unpinned)
        found, expected, missing = gecko.import_bookmarks(html_text, urls, profile, binary, args.show_toolbar,
                                                          args.timeout, log)
        if found == expected:
            log(f"Bookmarks: all {expected} links are in {target.label}.")
        else:
            log(f"Bookmarks: {found} of {expected} links made it. Missing:")
            for u in missing[:20]:
                log(f"  {u}")
            code = 4

    if target.key == "zen" and ("spaces" in steps or "pin-favourites" in steps):
        r = zen.apply(profile, export, spaces="spaces" in steps, essentials="pin-favourites" in steps,
                      backup_dir=backups)
        if "spaces" in steps:
            log(f"Zen spaces: {r['spaces_added']} added, {r['spaces_reused']} already there; "
                f"{r['pinned']} pinned tabs and {r['folders']} folders added.")
        if "pin-favourites" in steps:
            log(f"Zen Essentials: {r['essentials']} added.")

    new_prefs = {}
    if "pin-favourites" in steps and target.key == "firefox":
        added, path = gecko.pin_tabs(profile, _favourite_links(export), backups)
        new_prefs.update(prefs.RESTORE_SESSION)
        log(f"Pinned tabs: {added} added to {path.name}.")
    if "vertical-tabs" in steps:
        new_prefs.update(prefs.VERTICAL_TABS)
    if "clean-newtab" in steps:
        names = list(prefs.NEWTAB_CLEANUP)
        app = args.browser_bin.parents[2] if args.browser_bin and len(args.browser_bin.parents) > 2 else target.find_app()
        known, unknown = gecko.known_pref_names(app, names)
        if unknown:
            log(f"New tab: this {target.label} version doesn't use {', '.join(unknown)}; skipping those.")
        new_prefs.update({prefs.NEWTAB_PREFIX + n: prefs.NEWTAB_CLEANUP[n] for n in known})
    if new_prefs:
        prefs_js = profile / "prefs.js"
        if backups:
            prefs.backup_file(prefs_js, backups, "prefs.js")
        prefs.edit_prefs(prefs_js, new_prefs)
        if "vertical-tabs" in steps:
            log("Vertical tabs: on. (After Firefox restarts, prefs.js only keeps sidebar.verticalTabs; "
                "the others match Firefox's defaults.)")
        if "clean-newtab" in steps:
            log("New tab page: sponsored shortcuts, default sites and widgets turned off.")
    return code


def offer_extensions(args, export, target, ask, log):
    log(f"\nExtensions for {target.label}:")
    rows = extensions.report(export, target.key)
    for r in rows or ["  (none installed in Arc)"]:
        log(r)
    urls = extensions.install_urls(export, target.key)
    if not urls:
        return
    log("Extension data (logins, settings) doesn't carry over: sign in again in each one.")
    if args.browser_profile:
        log(f"Note: install pages open in {target.label}'s default profile, not {args.browser_profile}.")
    if args.dry_run:
        log(f"[dry run] Would open {len(urls)} install page(s) in {target.label}.")
        return
    verb = "install prompts" if target.engine == "gecko" else "Web Store pages"
    if ask(f"Open {len(urls)} {verb} in {target.label} now? You approve each one there."):
        browsers.system.open_urls(target, urls)
        log(f"Opened {len(urls)} {verb} in {target.label}. Approve each one there.")
    else:
        log("Skipped. The links are in the Markdown and JSON exports.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        if not argv:  # no options: ask questions instead
            from . import guided
            return guided.run(parse_args([]))
        return run(parse_args(argv))
    except ToolError as e:
        print(f"exit-arc: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
