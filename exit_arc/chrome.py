"""Chrome: add Arc favourites and spaces to the bookmarks bar, and list Web Store pages.

Chrome keeps bookmarks in <profile>/Bookmarks (JSON). We add our folders to
the end of the bookmarks bar and leave everything else alone, so nothing is
replaced. Our nodes are tagged in meta_info so a re-run swaps them instead of
adding duplicates. The file's "checksum" is recomputed the way Chrome does
(MD5 over ids, titles and URLs); Chrome also accepts a missing one.

Not possible on Chrome: pinned tabs (Chrome's session files are an
undocumented binary format) and startup pages (Chrome signs those settings and
resets edits it didn't make). Chrome has no spaces; they become folders.
"""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

from . import ToolError
from .prefs import backup_file

MARK = {"exit_arc": "1"}
ROOT_GUIDS = {
    "bookmark_bar": ("0bc5d13f-2cba-5d74-951f-3f233fe6c908", "Bookmarks bar"),
    "other": ("82b081ec-3dd3-529c-8475-ab6c344590dd", "Other bookmarks"),
    "synced": ("4cf2e351-0e85-532b-bb37-df045d8f8d0f", "Mobile bookmarks"),
}
WEBSTORE_URL = "https://chromewebstore.google.com/detail/{id}"


def chrome_time(t=None):
    """Microseconds since 1601-01-01, as a string (Chrome's format)."""
    return str(int(((t if t is not None else time.time()) + 11644473600) * 1_000_000))


def default_profile(root):
    root = Path(root)
    state = root / "Local State"
    if not state.exists():
        raise ToolError(f"No Chrome profile found ({state} is missing). Open Chrome once, quit it, then run this again.")
    try:
        last = json.loads(state.read_text(encoding="utf-8")).get("profile", {}).get("last_used") or "Default"
    except ValueError:
        last = "Default"
    return root / last


def list_profiles(root):
    """Chrome profiles from Local State: [{"name", "path", "default"}], the last used first."""
    root = Path(root)
    try:
        state = json.loads((root / "Local State").read_text(encoding="utf-8")).get("profile", {})
    except (OSError, ValueError):
        return []
    last = state.get("last_used") or "Default"
    profiles = [{"name": (info or {}).get("name") or d, "path": root / d, "default": d == last}
                for d, info in (state.get("info_cache") or {}).items() if (root / d).is_dir()]
    return sorted(profiles, key=lambda p: not p["default"])


def empty_bookmarks(now):
    roots = {}
    for i, (key, (guid, name)) in enumerate(ROOT_GUIDS.items(), start=1):
        roots[key] = {"children": [], "date_added": now, "date_last_used": "0", "date_modified": "0",
                      "guid": guid, "id": str(i), "name": name, "type": "folder"}
    return {"checksum": "", "roots": roots, "version": 1}


def checksum(data):
    """Chrome's BookmarkCodec checksum: MD5 over id, UTF-16LE title, type and url, depth first."""
    md5 = hashlib.md5()

    def walk(node):
        md5.update(str(node.get("id", "")).encode("utf-8"))
        md5.update((node.get("name") or "").encode("utf-16-le"))
        if node.get("type") == "url":
            md5.update(b"url")
            md5.update((node.get("url") or "").encode("utf-8"))
        else:
            md5.update(b"folder")
            for child in node.get("children") or []:
                walk(child)

    for key in ("bookmark_bar", "other", "synced"):
        if key in data.get("roots", {}):
            walk(data["roots"][key])
    return md5.hexdigest()


def _max_id(node):
    best = int(node.get("id") or 0) if str(node.get("id") or "0").isdigit() else 0
    for child in node.get("children") or []:
        best = max(best, _max_id(child))
    return best


def _strip_ours(node):
    """Remove nodes a previous exit-arc run added. Returns how many were removed."""
    kids = node.get("children") or []
    keep = [c for c in kids if (c.get("meta_info") or {}).get("exit_arc") != "1"]
    removed = len(kids) - len(keep)
    if "children" in node:
        node["children"] = keep
    for c in keep:
        removed += _strip_ours(c)
    return removed


class _Ids:
    def __init__(self, start):
        self.n = start

    def __call__(self):
        self.n += 1
        return str(self.n)


def to_chrome(nodes, ids, now, top=False):
    out = []
    for n in nodes:
        if n["type"] == "link":
            c = {"date_added": now, "date_last_used": "0", "guid": str(uuid.uuid4()), "id": ids(),
                 "name": n["title"] or n["url"], "type": "url", "url": n["url"]}
        else:
            c = {"children": [], "date_added": now, "date_last_used": "0", "date_modified": now,
                 "guid": str(uuid.uuid4()), "id": ids(), "name": n["title"], "type": "folder"}
            c["children"] = to_chrome(n["children"], ids, now)
        if top:
            c["meta_info"] = dict(MARK)
        out.append(c)
    return out


def sync_warning(profile):
    """Chrome sync can merge or undo local bookmark edits. Say so if it looks enabled."""
    try:
        prefs = json.loads((Path(profile) / "Preferences").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    signed_in = bool(prefs.get("account_info")) or bool((prefs.get("google") or {}).get("services", {}).get("signin"))
    if signed_in or (prefs.get("sync") or {}).get("has_setup_completed"):
        return ("This Chrome profile is signed in to a Google account. If bookmark sync is on, Chrome will "
                "sync these new bookmarks to your other devices too.")
    return None


def add_bookmarks(profile, toolbar_nodes, menu_nodes, backup_dir=None, now=None):
    """Add bookmarks to a closed Chrome profile. Returns (added_count, replaced_from_previous_run)."""
    profile = Path(profile)
    path = profile / "Bookmarks"
    now = now or chrome_time()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ToolError(f"Couldn't read Chrome's bookmarks file {path}: {e}")
        if backup_dir:
            backup_file(path, backup_dir, "Bookmarks")
    else:
        profile.mkdir(parents=True, exist_ok=True)
        data = empty_bookmarks(now)
    roots = data.setdefault("roots", {})
    for key, (guid, name) in ROOT_GUIDS.items():
        roots.setdefault(key, {"children": [], "date_added": now, "date_last_used": "0", "date_modified": "0",
                               "guid": guid, "id": str(len(roots) + 1), "name": name, "type": "folder"})
    replaced = sum(_strip_ours(r) for r in roots.values() if isinstance(r, dict))
    ids = _Ids(max(_max_id(r) for r in roots.values() if isinstance(r, dict)))
    bar = to_chrome(toolbar_nodes, ids, now, top=True)
    other = to_chrome(menu_nodes, ids, now, top=True)
    roots["bookmark_bar"]["children"] += bar
    roots["other"]["children"] += other
    roots["bookmark_bar"]["date_modified"] = now
    data["checksum"] = checksum(data)
    tmp = path.with_name("Bookmarks.exit-arc.tmp")
    tmp.write_text(json.dumps(data, indent=3, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

    def count(ns):
        return sum(1 if n["type"] == "url" else count(n["children"]) for n in ns)

    return count(bar) + count(other), replaced


def webstore_urls(extensions):
    return [WEBSTORE_URL.format(id=e["id"]) for e in extensions if e.get("fromWebStore") and not e.get("preinstalled")]


def enable_vertical_tabs(profile, backup_dir=None):
    """Turn on Chrome's vertical tabs (the `vertical_tabs.enabled` setting) in a closed profile.

    Returns True if it changed something, False if it was already on.
    """
    path = Path(profile) / "Preferences"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        raise ToolError(f"Chrome's settings file {path} isn't valid JSON, so it was left alone.")
    section = data.get("vertical_tabs")
    if not isinstance(section, dict):
        section = data["vertical_tabs"] = {}
    if section.get("enabled") is True:
        return False
    if backup_dir and path.exists():
        backup_file(path, backup_dir, "Preferences")
    section["enabled"] = True
    tmp = path.with_name("Preferences.exit-arc.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    return True
