#!/usr/bin/env python3
"""arc-to-firefox: move your Arc browser sidebar (spaces, pinned tabs, folders,
favourites) into Firefox bookmarks.

Python 3.8+ standard library only. Run with --help for usage.

What it reads (never writes):
  ~/Library/Application Support/Arc/StorableSidebar.json
  ~/Library/Application Support/Arc/User Data/Local State   (profile names)

What it writes:
  <out>/arc-export.json        everything it found, grouped by Arc profile
  <out>/arc-bookmarks.html     Netscape bookmarks file Firefox can import

With --import it also loads that file into a Firefox profile automatically.
That import REPLACES the profile's bookmarks, so the tool backs them up and
refuses to touch a profile that already has bookmarks unless you pass
--replace-existing.
"""

from __future__ import annotations

import argparse
import configparser
import html
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

__version__ = "0.1.0"

DEFAULT_ARC_DIR = Path.home() / "Library" / "Application Support" / "Arc"
ARC_SYSTEM_PROFILE = "__ARC_SYSTEM_PROFILE"

# Bookmarks a brand-new Firefox profile ships with. Used only to decide whether
# a profile "already has bookmarks" worth protecting.
FIREFOX_DEFAULT_HOSTS = ("mozilla.org", "mozilla.com", "firefox.com")

IMPORT_PREFS = ("browser.places.importBookmarksHTML", "browser.bookmarks.file")


class ToolError(Exception):
    """A problem we can explain to the user (printed without a traceback)."""


# --------------------------------------------------------------------------
# Reading Arc
# --------------------------------------------------------------------------

def pairs(seq):
    """Arc stores maps as flat alternating lists: [key, value, key, value, ...]."""
    seq = seq or []
    return [(seq[i], seq[i + 1]) for i in range(0, len(seq) - 1, 2)]


def key_name(key):
    """Container keys are either strings ('pinned') or one-key dicts ({'pinned': {}})."""
    if isinstance(key, str):
        return key
    if isinstance(key, dict) and key:
        return next(iter(key))
    return None


def profile_dir(profile_obj):
    """Map an Arc profile marker to a Chromium profile directory name.

    {'default': True}                                       -> 'Default'
    {'custom': {'_0': {'directoryBasename': 'Profile 2'}}}  -> 'Profile 2'
    """
    def find(o):
        if isinstance(o, dict):
            if isinstance(o.get("directoryBasename"), str):
                return o["directoryBasename"]
            for v in o.values():
                r = find(v)
                if r:
                    return r
        return None

    return find(profile_obj) or "Default"


def load_profile_names(arc_dir):
    """Return {directory: display name} from Arc's Chromium 'Local State'."""
    path = Path(arc_dir) / "User Data" / "Local State"
    names = {}
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))["profile"]["info_cache"]
    except (OSError, ValueError, KeyError, TypeError):
        return names
    for directory, info in cache.items():
        name = (info or {}).get("name") or directory
        if name == ARC_SYSTEM_PROFILE:
            continue
        if directory == "Default" and info.get("is_using_default_name"):
            name = "Default"
        names[directory] = name
    return names


def pick_container(sidebar):
    """The live sidebar is the first container that has both spaces and items."""
    containers = (sidebar.get("sidebar") or {}).get("containers") or []
    for c in containers:
        if isinstance(c, dict) and "spaces" in c and "items" in c:
            return c
    raise ToolError("Couldn't find spaces in StorableSidebar.json. Has Arc's file format changed?")


def space_emoji(space):
    icon = ((space.get("customInfo") or {}).get("iconType") or {})
    if icon.get("emoji_v2"):
        return icon["emoji_v2"]
    if isinstance(icon.get("emoji"), int):
        try:
            return chr(icon["emoji"])
        except (ValueError, OverflowError):
            pass
    return ""


class SidebarParser:
    def __init__(self, container):
        self.items = {x["id"]: x for x in container.get("items", []) if isinstance(x, dict) and "id" in x}
        self.skipped = {}

    def _skip(self, kind):
        self.skipped[kind] = self.skipped.get(kind, 0) + 1

    def nodes(self, item_id, seen=None):
        """Return a list of nodes for one Arc item (a list, because split views flatten)."""
        seen = set() if seen is None else seen
        if item_id in seen:
            return []
        seen = seen | {item_id}
        it = self.items.get(item_id)
        if it is None:
            self._skip("missing item")
            return []
        data = it.get("data") or {}
        if "tab" in data:
            tab = data["tab"] or {}
            url = tab.get("savedURL")
            if not url:
                self._skip("tab without URL")
                return []
            title = it.get("title") or tab.get("savedTitle") or url
            return [{"type": "link", "title": title, "url": url}]
        if "list" in data:
            return [{"type": "folder", "title": it.get("title") or "Untitled folder",
                     "children": self.children(it, seen)}]
        if "splitView" in data:
            return self.children(it, seen)  # a split view is just tabs side by side
        if it.get("childrenIds"):
            return self.children(it, seen)
        self._skip(next(iter(data), "unknown"))  # notes, easels, etc. have no URL
        return []

    def children(self, it, seen=None):
        out = []
        for cid in (it or {}).get("childrenIds") or []:
            out.extend(self.nodes(cid, seen))
        return out

    def container(self, container_id):
        if not container_id:
            return []
        return self.children(self.items.get(container_id))


def read_arc(arc_dir=DEFAULT_ARC_DIR):
    """Parse Arc's sidebar into a plain dict (the arc-export.json structure)."""
    arc_dir = Path(arc_dir).expanduser()
    path = arc_dir / "StorableSidebar.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ToolError(f"Arc data not found at {path}. Is Arc installed? Use --arc-dir to point elsewhere.")
    except ValueError as e:
        raise ToolError(f"Couldn't read {path}: {e}")

    container = pick_container(raw)
    parser = SidebarParser(container)
    names = load_profile_names(arc_dir)
    profiles = {}

    def profile(directory):
        if directory not in profiles:
            profiles[directory] = {"directory": directory, "name": names.get(directory, directory),
                                   "favourites": [], "spaces": []}
        return profiles[directory]

    for prof_obj, cid in pairs(container.get("topAppsContainerIDs")):
        if isinstance(cid, str):
            directory = profile_dir(prof_obj)
            if directory in names or not names:
                profile(directory)["favourites"] = parser.container(cid)

    for space in container.get("spaces", []):
        if not isinstance(space, dict):
            continue
        directory = profile_dir(space.get("profile"))
        if names and directory not in names:
            continue  # e.g. Arc's internal system profile
        ids = {}
        for k, v in pairs(space.get("containerIDs")) + pairs(space.get("newContainerIDs")):
            name = key_name(k)
            if name and isinstance(v, str):
                ids.setdefault(name, v)
        profile(directory)["spaces"].append({
            "title": space.get("title") or "Untitled space",
            "emoji": space_emoji(space),
            "pinned": parser.container(ids.get("pinned")),
            "unpinned": parser.container(ids.get("unpinned")),
        })

    ordered = sorted(profiles.values(), key=lambda p: (p["directory"] != "Default", p["directory"]))
    return {
        "tool": f"arc-to-firefox {__version__}",
        "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(path),
        "profiles": ordered,
        "skipped": parser.skipped,
    }


def filter_profiles(export, wanted):
    if not wanted:
        return export
    wanted_l = {w.lower() for w in wanted}
    keep = [p for p in export["profiles"] if p["name"].lower() in wanted_l or p["directory"].lower() in wanted_l]
    if not keep:
        have = ", ".join(f'{p["name"]} ({p["directory"]})' for p in export["profiles"]) or "none"
        raise ToolError(f"No Arc profile matches {', '.join(wanted)}. Found: {have}")
    return {**export, "profiles": keep}


# --------------------------------------------------------------------------
# Counting / summary
# --------------------------------------------------------------------------

def count_links(nodes):
    return sum(1 if n["type"] == "link" else count_links(n["children"]) for n in nodes)


def count_folders(nodes):
    return sum(1 + count_folders(n["children"]) for n in nodes if n["type"] == "folder")


def iter_urls(nodes):
    for n in nodes:
        if n["type"] == "link":
            yield n["url"]
        else:
            yield from iter_urls(n["children"])


def exported_urls(export, include_unpinned=False):
    urls = []
    for p in export["profiles"]:
        urls += iter_urls(p["favourites"])
        for s in p["spaces"]:
            urls += iter_urls(s["pinned"])
            if include_unpinned:
                urls += iter_urls(s["unpinned"])
    return urls


def space_label(space):
    return f'{space["emoji"]} {space["title"]}'.strip()


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def summary(export, include_unpinned=False):
    lines = []
    multi = len(export["profiles"]) > 1
    for p in export["profiles"]:
        indent = "  " if multi else ""
        if multi:
            folder = "" if p["name"] == p["directory"] else f' ({p["directory"]})'
            lines.append(f'Profile: {p["name"]}{folder}')
        lines.append(f'{indent}Favourites: {plural(count_links(p["favourites"]), "link")}')
        for s in p["spaces"]:
            unpinned = count_links(s["unpinned"])
            extra = f", {unpinned} open unpinned" + ("" if include_unpinned or not unpinned else " (not exported)")
            lines.append(f'{indent}{space_label(s)}: {plural(count_links(s["pinned"]), "pinned link")}, '
                         f'{plural(count_folders(s["pinned"]), "folder")}{extra}')
    lines.append(f"Total links to bookmark: {len(exported_urls(export, include_unpinned))}")
    if export.get("skipped"):
        bits = ", ".join(f"{v} {k}" for k, v in sorted(export["skipped"].items()))
        lines.append(f"Skipped (nothing to bookmark): {bits}")
    return lines


# --------------------------------------------------------------------------
# Netscape bookmarks HTML
# --------------------------------------------------------------------------

def _esc(s):
    return html.escape(s or "", quote=True)


def _html_nodes(nodes, depth):
    pad = "    " * depth
    out = []
    for n in nodes:
        if n["type"] == "link":
            out.append(f'{pad}<DT><A HREF="{_esc(n["url"])}">{_esc(n["title"] or n["url"])}</A>')
        else:
            out += _html_folder(n["title"], n["children"], depth)
    return out


def _html_folder(title, children, depth, attrs=""):
    pad = "    " * depth
    return ([f"{pad}<DT><H3{attrs}>{_esc(title)}</H3>", f"{pad}<DL><p>"]
            + _html_nodes(children, depth + 1) + [f"{pad}</DL><p>"])


def _space_folders(profile, include_unpinned):
    folders = []
    for s in profile["spaces"]:
        children = list(s["pinned"])
        if include_unpinned and s["unpinned"]:
            children.append({"type": "folder", "title": "Open tabs (unpinned)", "children": s["unpinned"]})
        folders.append({"type": "folder", "title": space_label(s), "children": children})
    return folders


def build_tree(export, layout="toolbar", include_unpinned=False):
    """Return (toolbar_nodes, menu_nodes) for the chosen layout."""
    multi = len(export["profiles"]) > 1
    if layout == "toolbar":
        # Favourites as plain toolbar links, then one toolbar folder per space.
        # With several Arc profiles, each profile gets its own toolbar folder.
        toolbar = []
        for p in export["profiles"]:
            nodes = list(p["favourites"]) + _space_folders(p, include_unpinned)
            if multi:
                toolbar.append({"type": "folder", "title": p["name"], "children": nodes})
            else:
                toolbar += nodes
        return toolbar, []
    if layout == "folder":
        def contents(p):
            nodes = [{"type": "folder", "title": "Favourites", "children": p["favourites"]}] if p["favourites"] else []
            return nodes + _space_folders(p, include_unpinned)
        if multi:
            children = [{"type": "folder", "title": p["name"], "children": contents(p)} for p in export["profiles"]]
        else:
            children = contents(export["profiles"][0]) if export["profiles"] else []
        return [], [{"type": "folder", "title": "Arc", "children": children}]
    raise ToolError(f"Unknown layout {layout!r}")


def bookmarks_html(toolbar, menu):
    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- Generated by arc-to-firefox. -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks Menu</H1>",
        "<DL><p>",
    ]
    if toolbar:
        lines += _html_folder("Bookmarks Toolbar", toolbar, 1, ' PERSONAL_TOOLBAR_FOLDER="true"')
    lines += _html_nodes(menu, 1)
    lines.append("</DL><p>")
    return "\n".join(lines) + "\n"


def build_html(export, layout="toolbar", include_unpinned=False):
    return bookmarks_html(*build_tree(export, layout, include_unpinned))


# --------------------------------------------------------------------------
# Firefox profile discovery
# --------------------------------------------------------------------------

def firefox_root():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Firefox"
    return Path.home() / ".mozilla" / "firefox"


def default_firefox_profile(root=None):
    """The profile Firefox opens by default: [Install...] Default=, else [Profile*] Default=1."""
    root = Path(root or firefox_root())
    ini = root / "profiles.ini"
    if not ini.exists():
        raise ToolError(f"No Firefox profile found ({ini} is missing). Open Firefox once, quit it, "
                        "then run this again (or pass --firefox-profile).")
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(ini, encoding="utf-8")

    rel_by_path = {}
    fallback = None
    for sec in cp.sections():
        if sec.startswith("Profile") and cp.has_option(sec, "Path"):
            path = cp.get(sec, "Path")
            rel_by_path[path] = cp.get(sec, "IsRelative", fallback="1") == "1"
            if cp.get(sec, "Default", fallback="0") == "1" and fallback is None:
                fallback = path

    installs = [cp.get(s, "Default") for s in cp.sections() if s.startswith("Install") and cp.has_option(s, "Default")]
    chosen = installs[0] if installs else fallback
    if not chosen:
        raise ToolError(f"Couldn't work out the default Firefox profile from {ini}. Pass --firefox-profile.")
    relative = rel_by_path.get(chosen, not os.path.isabs(chosen))
    path = (root / chosen) if relative else Path(chosen)
    note = None
    if len(set(installs)) > 1:
        note = (f"Several Firefox installs found; using {chosen}. "
                "Pass --firefox-profile to choose another.")
    return path, note


def find_firefox_bin():
    candidates = []
    if sys.platform == "darwin":
        for base in (Path("/Applications"), Path.home() / "Applications"):
            for app in ("Firefox.app", "Firefox Developer Edition.app", "Firefox Nightly.app"):
                candidates.append(base / app / "Contents" / "MacOS" / "firefox")
    which = shutil.which("firefox")
    if which:
        candidates.append(Path(which))
    for c in candidates:
        if c.exists():
            return c
    raise ToolError("Couldn't find Firefox. Install it, or pass --firefox-bin /path/to/firefox.")


def firefox_running():
    try:
        r = subprocess.run(["pgrep", "-x", "firefox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return False
    return r.returncode == 0


def profile_in_use(profile):
    """True if a live Firefox holds this profile's lock."""
    lock = Path(profile) / "lock"
    if os.path.islink(lock):
        target = os.readlink(lock)
        try:
            pid = int(target.rsplit("+", 1)[1])
            os.kill(pid, 0)
            return True
        except (IndexError, ValueError, ProcessLookupError):
            pass
        except PermissionError:
            return True
    parent = Path(profile) / ".parentlock"
    if parent.exists():
        try:
            import fcntl
            with open(parent, "rb") as f:
                fcntl.lockf(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
                fcntl.lockf(f, fcntl.LOCK_UN)
        except ImportError:
            pass
        except OSError:
            return True
    return False


# --------------------------------------------------------------------------
# Reading Firefox bookmarks (places.sqlite)
# --------------------------------------------------------------------------

ROOT_GUIDS = {"toolbar_____": "toolbar", "menu________": "menu", "unfiled_____": "unfiled", "mobile______": "mobile"}


def normalize_url(url):
    """Compare URLs the way Firefox stores them (lower-case scheme/host, '/' path)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, parts.fragment))


class PlacesSnapshot:
    """Copy places.sqlite (+WAL) aside and read the copy, so Firefox's lock never matters."""

    def __init__(self, profile):
        self.src = Path(profile) / "places.sqlite"

    def __enter__(self):
        self.tmp = tempfile.mkdtemp(prefix="arc2ff-")
        self.conn = None
        if self.src.exists():
            for suffix in ("", "-wal"):
                f = Path(str(self.src) + suffix)
                if f.exists():
                    shutil.copy2(f, Path(self.tmp) / ("places.sqlite" + suffix))
            try:
                self.conn = sqlite3.connect(str(Path(self.tmp) / "places.sqlite"))
                self.conn.execute("SELECT 1 FROM moz_bookmarks LIMIT 1")
            except sqlite3.Error:
                self.conn = None  # not created yet / mid-write
        return self

    def __exit__(self, *exc):
        if self.conn:
            self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bookmarks(self):
        """[(root, url, title)] for every URL bookmark outside the tags tree."""
        if not self.conn:
            return []
        q = """
        WITH RECURSIVE tree(id, root) AS (
            SELECT id, guid FROM moz_bookmarks WHERE guid IN ({roots})
            UNION ALL
            SELECT b.id, tree.root FROM moz_bookmarks b JOIN tree ON b.parent = tree.id
        )
        SELECT tree.root, p.url, b.title FROM moz_bookmarks b
        JOIN tree ON tree.id = b.id JOIN moz_places p ON p.id = b.fk
        WHERE b.type = 1
        """.format(roots=",".join("?" * len(ROOT_GUIDS)))
        try:
            return [(ROOT_GUIDS.get(r, r), u, t) for r, u, t in self.conn.execute(q, list(ROOT_GUIDS))]
        except sqlite3.Error:
            return []

    def tree(self):
        """{root: [nodes]} for writing a backup HTML file."""
        if not self.conn:
            return {}
        rows = self.conn.execute(
            "SELECT b.id, b.type, b.parent, b.position, b.title, b.guid, p.url FROM moz_bookmarks b "
            "LEFT JOIN moz_places p ON p.id = b.fk ORDER BY b.parent, b.position").fetchall()
        kids = {}
        for r in rows:
            kids.setdefault(r[2], []).append(r)

        def build(pid):
            out = []
            for bid, typ, _, _, title, _, url in kids.get(pid, []):
                if typ == 1 and url and not url.startswith("place:"):
                    out.append({"type": "link", "title": title or url, "url": url})
                elif typ == 2:
                    out.append({"type": "folder", "title": title or "", "children": build(bid)})
            return out

        return {ROOT_GUIDS[g]: build(bid) for bid, _, _, _, _, g, _ in rows if g in ROOT_GUIDS}


def is_default_bookmark(url):
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in FIREFOX_DEFAULT_HOSTS)


def existing_bookmarks(profile):
    with PlacesSnapshot(profile) as snap:
        marks = snap.bookmarks()
    user = [m for m in marks if not is_default_bookmark(m[1])]
    return len(marks), len(user)


def backup_firefox_bookmarks(profile, dest_dir):
    """Copy places.sqlite and write the current bookmarks as importable HTML."""
    dest = Path(dest_dir) / time.strftime("firefox-bookmarks-backup-%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(profile) / "places.sqlite"
    for suffix in ("", "-wal"):
        f = Path(str(src) + suffix)
        if f.exists():
            shutil.copy2(f, dest / f.name)
    with PlacesSnapshot(profile) as snap:
        roots = snap.tree()
    menu = roots.get("menu", [])
    for name, title in (("unfiled", "Other Bookmarks"), ("mobile", "Mobile Bookmarks")):
        if roots.get(name):
            menu = menu + [{"type": "folder", "title": title, "children": roots[name]}]
    (dest / "bookmarks.html").write_text(bookmarks_html(roots.get("toolbar", []), menu), encoding="utf-8")
    return dest


# --------------------------------------------------------------------------
# Importing into Firefox
# --------------------------------------------------------------------------

def _js_string(s):
    return json.dumps(str(s))


def _pref_lines(prefs_text, names):
    return [ln for ln in prefs_text.splitlines() if any(f'user_pref("{n}"' in ln for n in names)]


def import_into_firefox(html_text, expected_urls, profile, firefox_bin, show_toolbar=True,
                        timeout=90, log=print):
    """Load html_text into `profile` by starting Firefox once with temporary prefs.

    Returns (found, expected, missing_urls). Caller must have made sure Firefox
    isn't using the profile and that replacing its bookmarks is OK.
    """
    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    expected = {normalize_url(u) for u in expected_urls}
    user_js = profile / "user.js"
    prefs_js = profile / "prefs.js"
    original_user_js = user_js.read_text(encoding="utf-8") if user_js.exists() else None
    original_pref_lines = _pref_lines(prefs_js.read_text(encoding="utf-8"), IMPORT_PREFS) if prefs_js.exists() else []
    import_file = profile / time.strftime("arc-to-firefox-import-%Y%m%d-%H%M%S.html")
    import_file.write_text(html_text, encoding="utf-8")

    prefs = [
        "// Added temporarily by arc-to-firefox; removed after the import.",
        'user_pref("browser.places.importBookmarksHTML", true);',
        f'user_pref("browser.bookmarks.file", {_js_string(import_file)});',
    ]
    if show_toolbar:
        prefs.append('user_pref("browser.toolbars.bookmarks.visibility", "always");')
    user_js.write_text((original_user_js.rstrip("\n") + "\n" if original_user_js else "") + "\n".join(prefs) + "\n",
                       encoding="utf-8")

    def found_urls():
        with PlacesSnapshot(profile) as snap:
            return {normalize_url(u) for _, u, _ in snap.bookmarks()}

    proc = None
    try:
        log(f"Starting Firefox (headless) to import into {profile} ...")
        proc = subprocess.Popen([str(firefox_bin), "--headless", "--no-remote", "--profile", str(profile)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and proc.poll() is None:
            if expected <= found_urls():
                break
            time.sleep(1)
        time.sleep(2)  # let Firefox finish writing
    finally:
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        # Undo every temporary change, even if something went wrong above.
        if original_user_js is None:
            user_js.unlink(missing_ok=True)
        else:
            user_js.write_text(original_user_js, encoding="utf-8")
        import_file.unlink(missing_ok=True)
        if prefs_js.exists():
            text = prefs_js.read_text(encoding="utf-8")
            kept = [ln for ln in text.splitlines() if ln not in _pref_lines(text, IMPORT_PREFS)]
            prefs_js.write_text("\n".join(kept + original_pref_lines) + "\n", encoding="utf-8")

    found = found_urls()
    missing = sorted(expected - found)
    return len(expected & found), len(expected), missing


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

MANUAL_STEPS = """\
To add these to Firefox without replacing anything, import the file by hand:
  Firefox > Bookmarks > Manage Bookmarks (Shift+Cmd+O)
  > Import and Backup > Import Bookmarks from HTML... > choose {html}"""


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="arc-to-firefox",
        description="Export Arc spaces, pinned tabs, folders and favourites to Firefox bookmarks.",
        epilog="Exports only sidebar links. History, passwords, cookies and extensions are not touched.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--arc-dir", type=Path, default=DEFAULT_ARC_DIR, help="Arc data folder (default: %(default)s)")
    p.add_argument("--arc-profile", action="append", metavar="NAME",
                   help="only export this Arc profile (name or folder, e.g. 'Work' or 'Profile 1'); repeatable")
    p.add_argument("-o", "--out", type=Path, default=Path.cwd(), help="output folder (default: current folder)")
    p.add_argument("--layout", choices=("toolbar", "folder"), default="toolbar",
                   help="toolbar: favourites + one toolbar folder per space (default); "
                        "folder: everything inside one 'Arc' folder in the Bookmarks Menu")
    p.add_argument("--include-unpinned", action="store_true",
                   help="also bookmark each space's open, unpinned tabs (in an 'Open tabs' subfolder)")
    p.add_argument("-n", "--dry-run", action="store_true", help="show what would happen; write nothing")
    g = p.add_argument_group("automatic Firefox import (replaces the profile's bookmarks)")
    g.add_argument("--import", dest="do_import", action="store_true",
                   help="load the bookmarks into Firefox automatically (Firefox must be closed)")
    g.add_argument("--firefox-profile", type=Path, help="Firefox profile folder (default: the one Firefox opens)")
    g.add_argument("--firefox-bin", type=Path, help="path to the firefox executable")
    g.add_argument("--replace-existing", action="store_true",
                   help="allow importing into a profile that already has bookmarks (they're backed up first)")
    g.add_argument("--no-backup", action="store_true", help="skip the backup of existing Firefox bookmarks")
    g.add_argument("--no-show-toolbar", dest="show_toolbar", action="store_false",
                   help="don't switch the bookmarks toolbar to 'always show'")
    g.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    g.add_argument("--timeout", type=int, default=90, help="seconds to wait for Firefox (default: %(default)s)")
    return p.parse_args(argv)


def confirm(question):
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def run(args, log=print):
    export = filter_profiles(read_arc(args.arc_dir), args.arc_profile)
    for line in summary(export, args.include_unpinned):
        log(line)
    urls = exported_urls(export, args.include_unpinned)
    html_text = build_html(export, args.layout, args.include_unpinned)
    json_path = args.out / "arc-export.json"
    html_path = args.out / "arc-bookmarks.html"

    if args.dry_run:
        log(f"\n[dry run] Would write {json_path} and {html_path} ({args.layout} layout).")
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(export, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        html_path.write_text(html_text, encoding="utf-8")
        log(f"\nWrote {json_path}\nWrote {html_path}")

    if not args.do_import:
        if not args.dry_run:
            log("\n" + MANUAL_STEPS.format(html=html_path))
        return 0

    # ---- automatic import ----
    if args.firefox_profile:
        profile, note = args.firefox_profile.expanduser(), None
    else:
        profile, note = default_firefox_profile()
        if firefox_running():
            raise ToolError("Firefox is running. Quit it (Cmd+Q) and run this again.")
    if note:
        log(note)
    if profile_in_use(profile):
        raise ToolError(f"Firefox is using the profile {profile}. Quit Firefox and run this again.")
    firefox_bin = args.firefox_bin or find_firefox_bin()
    total, user = existing_bookmarks(profile)
    log(f"\nFirefox profile: {profile}")
    log(f"It has {total} bookmarks ({user} of yours, {total - user} Firefox defaults).")

    if user and not args.replace_existing:
        log("\nThe automatic import REPLACES all bookmarks in the profile, so it stopped here.")
        log(MANUAL_STEPS.format(html=html_path))
        log("Or re-run with --replace-existing to back them up and replace them.")
        return 3

    if args.dry_run:
        log(f"[dry run] Would {'back up and ' if total and not args.no_backup else ''}replace them with "
            f"{len(set(urls))} links using {firefox_bin}.")
        return 0

    log("\nWARNING: this REPLACES every bookmark in that Firefox profile with your Arc links.")
    if not args.yes and not confirm("Continue?"):
        log("Cancelled. Nothing in Firefox was changed.")
        return 1
    if total and not args.no_backup:
        dest = backup_firefox_bookmarks(profile, args.out)
        log(f"Backed up existing bookmarks to {dest} (bookmarks.html can be re-imported from the Library window).")

    found, expected, missing = import_into_firefox(html_text, urls, profile, firefox_bin,
                                                   args.show_toolbar, args.timeout, log)
    if found == expected:
        log(f"Done: all {expected} links are in Firefox. Temporary files removed.")
        return 0
    log(f"Imported {found} of {expected} links. Not found in Firefox afterwards:")
    for u in missing[:20]:
        log(f"  {u}")
    if len(missing) > 20:
        log(f"  ... and {len(missing) - 20} more")
    log("Temporary files removed. You can import the rest by hand:")
    log(MANUAL_STEPS.format(html=html_path).split("\n", 1)[1])
    return 4


def main(argv=None):
    args = parse_args(argv)
    try:
        return run(args)
    except ToolError as e:
        print(f"arc-to-firefox: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
