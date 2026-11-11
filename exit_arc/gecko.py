"""Firefox and Zen (Gecko) profiles: finding them, reading bookmarks, importing,
pinned tabs (sessionstore) and checking settings names in omni.ja."""

import configparser
import json
import os
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import ToolError, browsers, exporters, mozlz4

# Bookmarks a brand-new Firefox profile ships with. Used only to decide whether
# a profile "already has bookmarks" worth protecting.
DEFAULT_BOOKMARK_HOSTS = ("mozilla.org", "mozilla.com", "firefox.com", "zen-browser.app")
IMPORT_PREFS = ("browser.places.importBookmarksHTML", "browser.bookmarks.file")
SESSION_FILES = ("sessionstore.jsonlz4", "zen-sessions.jsonlz4", "sessionstore-backups/recovery.jsonlz4",
                 "sessionstore-backups/recovery.baklz4")


def _js_string(s):
    return json.dumps(str(s))


def list_profiles(browser, root=None):
    """Every profile the browser knows about: [{"name", "path", "default"}], the default one first.

    Reads profiles.ini and, for Firefox's newer profile manager, the Profile Groups database.
    Profiles whose folder is missing are left out.
    """
    root = Path(root or browser.data_root)
    ini = root / "profiles.ini"
    found = {}
    if ini.exists():
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(ini, encoding="utf-8")
        for sec in cp.sections():
            if sec.startswith("Profile") and cp.has_option(sec, "Path"):
                rel = cp.get(sec, "IsRelative", fallback="1") == "1"
                path = (root / cp.get(sec, "Path")) if rel else Path(cp.get(sec, "Path"))
                found[str(path.resolve())] = {"name": cp.get(sec, "Name", fallback=path.name), "path": path}
    for db_path in sorted((root / "Profile Groups").glob("*.sqlite")):
        try:
            db = sqlite3.connect(f"file:{db_path}?immutable=1", uri=True)
            rows = db.execute("SELECT path, name FROM Profiles").fetchall()
            db.close()
        except sqlite3.Error:
            continue
        for rel_path, name in rows:
            path = Path(rel_path) if os.path.isabs(rel_path) else root / rel_path
            found[str(path.resolve())] = {"name": name or path.name, "path": path}
    try:
        default = str(default_profile(browser, root)[0].resolve())
    except ToolError:
        default = None
    profiles = [dict(p, default=key == default) for key, p in found.items() if p["path"].is_dir()]
    return sorted(profiles, key=lambda p: not p["default"])


def default_profile(browser, root=None):
    """The profile Firefox opens by default: [Install...] Default=, else [Profile*] Default=1."""
    root = Path(root or browser.data_root)
    ini = root / "profiles.ini"
    if not ini.exists():
        raise ToolError(f"No {browser.label} profile found ({ini} is missing). Open {browser.label} once, quit it, "
                        "then run this again (or pass --browser-profile).")
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
        raise ToolError(f"Couldn't work out the default {browser.label} profile from {ini}. Pass --browser-profile.")
    relative = rel_by_path.get(chosen, not os.path.isabs(chosen))
    path = (root / chosen) if relative else Path(chosen)
    note = None
    if len(set(installs)) > 1:
        note = (f"Several {browser.label} installs found; using {chosen}. "
                "Pass --browser-profile to choose another.")
    return path, note


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
    return any(host == h or host.endswith("." + h) for h in DEFAULT_BOOKMARK_HOSTS)


def existing_bookmarks(profile):
    with PlacesSnapshot(profile) as snap:
        marks = snap.bookmarks()
    user = [m for m in marks if not is_default_bookmark(m[1])]
    return len(marks), len(user)


def backup_bookmarks(profile, dest_dir):
    """Copy places.sqlite and write the current bookmarks as importable HTML."""
    dest = Path(dest_dir)
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
    (dest / "bookmarks.html").write_text(exporters.bookmarks_html(roots.get("toolbar", []), menu), encoding="utf-8")
    return dest


def _pref_lines(prefs_text, names):
    return [ln for ln in prefs_text.splitlines() if any(f'user_pref("{n}"' in ln for n in names)]


def import_bookmarks(html_text, expected_urls, profile, binary, show_toolbar=True, timeout=90, log=print):
    """Load html_text into `profile` by starting the browser once, headless, with temporary prefs.

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
    import_file = profile / time.strftime("exit-arc-import-%Y%m%d-%H%M%S.html")
    import_file.write_text(html_text, encoding="utf-8")

    prefs = [
        "// Added temporarily by exit-arc; removed after the import.",
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

    # A headless start can rewrite the saved session (Zen saves an empty sidebar,
    # Firefox may save a blank window). Keep the real one and put it back afterwards.
    saved_sessions = tempfile.mkdtemp(prefix="exit-arc-session-")
    for name in SESSION_FILES:
        if (profile / name).exists():
            dest = Path(saved_sessions) / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(profile / name, dest)

    proc = None
    try:
        log(f"Starting the browser (headless, no window) to import into {profile} ...")
        proc = browsers.system.launch_headless(binary, profile)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and proc.poll() is None:
            if expected <= found_urls():
                break
            browsers.system.sleep(1)
        browsers.system.sleep(2)  # let the browser finish writing
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
        for name in SESSION_FILES:
            kept_copy = Path(saved_sessions) / name
            if kept_copy.exists():
                os.replace(kept_copy, profile / name)
            elif (profile / name).exists() and name == "zen-sessions.jsonlz4":
                (profile / name).unlink()  # didn't exist before; don't keep the empty one
        shutil.rmtree(saved_sessions, ignore_errors=True)
        if prefs_js.exists():
            text = prefs_js.read_text(encoding="utf-8")
            kept = [ln for ln in text.splitlines() if ln not in _pref_lines(text, IMPORT_PREFS)]
            prefs_js.write_text("\n".join(kept + original_pref_lines) + "\n", encoding="utf-8")

    found = found_urls()
    missing = sorted(expected - found)
    return len(expected & found), len(expected), missing


# --------------------------------------------------------------------------
# Pinned tabs (sessionstore.jsonlz4)
# --------------------------------------------------------------------------

SYSTEM_PRINCIPAL = '{"3":{}}'  # what Firefox records for a URL you typed yourself


def tab_state(url, title, now_ms, **extra):
    tab = {
        "entries": [{"url": url, "title": title or url, "triggeringPrincipal_base64": SYSTEM_PRINCIPAL}],
        "index": 1,
        "pinned": True,
        "hidden": False,
        "attributes": {},
        "lastAccessed": now_ms,
        "userContextId": 0,
    }
    tab.update(extra)
    return tab


def tab_url(tab):
    entries = tab.get("entries") or []
    if not entries:
        return None
    i = min(max(int(tab.get("index") or len(entries)), 1), len(entries)) - 1
    return entries[i].get("url")


def empty_session(now_ms):
    return {
        "version": ["sessionrestore", 1],
        "windows": [{"tabs": [], "selected": 1, "_closedTabs": []}],
        "selectedWindow": 1,
        "_closedWindows": [],
        "session": {"lastUpdate": now_ms, "startTime": now_ms, "recentCrashes": 0},
        "global": {},
    }


def add_pinned_tabs(session, links, now_ms=None):
    """Pin (url, title) links in the first window, after any already-pinned tabs.

    Skips URLs that are already pinned and keeps the selected tab the same.
    Returns how many tabs were added.
    """
    now_ms = now_ms or int(time.time() * 1000)
    windows = session.setdefault("windows", [])
    if not windows:
        windows.append({"tabs": [], "selected": 1, "_closedTabs": []})
    win = windows[0]
    tabs = win.setdefault("tabs", [])
    pinned = {normalize_url(tab_url(t) or "") for t in tabs if t.get("pinned")}
    new = []
    for url, title in links:
        key = normalize_url(url)
        if key in pinned:
            continue
        pinned.add(key)
        new.append(tab_state(url, title, now_ms))
    if not new:
        return 0
    at = 0
    while at < len(tabs) and tabs[at].get("pinned"):
        at += 1
    had_tabs = bool(tabs)
    tabs[at:at] = new
    selected = int(win.get("selected") or 1)
    if not had_tabs:
        win["selected"] = 1
    elif selected - 1 >= at:
        win["selected"] = selected + len(new)
    return len(new)


def session_file(profile):
    """The file the browser restores from on its next start."""
    profile = Path(profile)
    main = profile / "sessionstore.jsonlz4"
    if main.exists():
        return main, main
    recovery = profile / "sessionstore-backups" / "recovery.jsonlz4"
    return main, (recovery if recovery.exists() else None)


def pin_tabs(profile, links, backup_dir=None):
    """Write pinned tabs into the profile's session. Returns (added, path)."""
    target, source = session_file(profile)
    now_ms = int(time.time() * 1000)
    session = mozlz4.read_json(source) if source else empty_session(now_ms)
    if backup_dir and source:
        from .prefs import backup_file
        backup_file(source, backup_dir, "sessionstore.jsonlz4")
    added = add_pinned_tabs(session, links, now_ms)
    if added or source != target:
        mozlz4.write_json(target, session)
    return added, target


# --------------------------------------------------------------------------
# Checking which settings this browser version knows (omni.ja)
# --------------------------------------------------------------------------

def read_omni_entry(omni_path, suffix):
    """Read one file out of omni.ja. Mozilla's 'optimized' jars confuse zipfile, so walk local headers."""
    data = Path(omni_path).read_bytes()
    i = 0
    while True:
        i = data.find(b"PK\x03\x04", i)
        if i < 0 or i + 30 > len(data):
            return None
        (_, _, method, _, _, _, csize, _, nlen, xlen) = struct.unpack("<HHHHHIIIHH", data[i + 4:i + 30])
        name = data[i + 30:i + 30 + nlen].decode("utf-8", "replace")
        start = i + 30 + nlen + xlen
        if name.endswith(suffix):
            raw = data[start:start + csize]
            try:
                return zlib.decompress(raw, -15) if method == 8 else raw
            except zlib.error:
                return None
        i = start + max(csize, 1)


NEWTAB_SOURCE = "newtab/lib/ActivityStream.sys.mjs"


def known_pref_names(app_path, names):
    """Return (known, unknown) by looking for each name in the browser's new-tab code.

    If the code can't be read, every name counts as known (we can't tell)."""
    if not app_path:
        return list(names), []
    omni = Path(app_path) / "Contents" / "Resources" / "browser" / "omni.ja"
    try:
        src = read_omni_entry(omni, NEWTAB_SOURCE)
    except OSError:
        src = None
    if not src:
        return list(names), []
    text = src.decode("utf-8", "replace")
    known = [n for n in names if f'"{n}"' in text or f"'{n}'" in text]
    return known, [n for n in names if n not in known]


def app_version(app_path):
    ini = Path(app_path or "") / "Contents" / "Resources" / "application.ini"
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read(ini, encoding="utf-8")
        return cp.get("App", "Version", fallback=None)
    except (configparser.Error, OSError):
        return None
