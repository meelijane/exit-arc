"""Read Arc's sidebar (spaces, pinned tabs, folders, favourites) and extension list.

Arc stores its sidebar in StorableSidebar.json. Maps there are flat lists that
alternate key and value ([key, value, key, value, ...]). Nothing here writes to
Arc's folder.
"""

import json
import time
from pathlib import Path

from . import ToolError, __version__

DEFAULT_ARC_DIR = Path.home() / "Library" / "Application Support" / "Arc"
ARC_SYSTEM_PROFILE = "__ARC_SYSTEM_PROFILE"


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
            node = {"type": "link", "title": title, "url": url}
            if it.get("title"):
                node["renamed"] = True  # the user gave this tab its own name in Arc
            return [node]
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
        "tool": f"exit-arc {__version__}",
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
# Extensions
# --------------------------------------------------------------------------

# Chromium's Manifest::Location values.
USER_LOCATIONS = {1, 4, 8}            # web store, unpacked, command line
DEFAULT_LOCATIONS = {2, 3, 6, 7, 9}   # pre-installed / external / policy (e.g. Google Docs Offline)
COMPONENT_LOCATIONS = {5, 10}         # built into the browser (PDF viewer, Arc internals): never listed


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _version_key(name):
    return [int(p) if p.isdigit() else 0 for p in name.split("_")[0].split(".")]


def localized(value, ext_dir, default_locale):
    """Resolve '__MSG_key__' using _locales/<locale>/messages.json (keys are case-insensitive)."""
    if not isinstance(value, str) or not (value.startswith("__MSG_") and value.endswith("__")):
        return value
    key = value[6:-2].lower()
    for locale in (default_locale, "en", "en_US", "en_GB"):
        if not locale:
            continue
        messages = _read_json(Path(ext_dir) / "_locales" / locale / "messages.json") or {}
        for k, v in messages.items():
            if k.lower() == key and isinstance(v, dict) and v.get("message"):
                return v["message"]
    return None


def read_extensions(arc_dir, profile_directory):
    """List the extensions installed in one Arc profile (built-in components are left out)."""
    pdir = Path(arc_dir) / "User Data" / profile_directory
    settings = {}
    for name in ("Preferences", "Secure Preferences"):
        prefs = _read_json(pdir / name) or {}
        settings.update(((prefs.get("extensions") or {}).get("settings")) or {})

    found = {}
    ext_root = pdir / "Extensions"
    if ext_root.is_dir():
        for id_dir in sorted(p for p in ext_root.iterdir() if p.is_dir()):
            versions = sorted((v for v in id_dir.iterdir() if (v / "manifest.json").is_file()),
                              key=lambda v: _version_key(v.name))
            if versions:
                manifest = _read_json(versions[-1] / "manifest.json") or {}
                found[id_dir.name] = (versions[-1], manifest)
    for ext_id, info in settings.items():  # also extensions only known from preferences
        if ext_id not in found and isinstance((info or {}).get("manifest"), dict):
            found[ext_id] = (None, info["manifest"])

    out = []
    for ext_id, (ext_dir, manifest) in found.items():
        info = settings.get(ext_id) or {}
        location = info.get("location", 1)
        if location in COMPONENT_LOCATIONS:
            continue
        locale = manifest.get("default_locale")
        name = (localized(manifest.get("name"), ext_dir, locale) if ext_dir else None) or manifest.get("name") or ext_id
        if name.startswith("__MSG_"):
            name = ext_id
        author = manifest.get("author")
        if isinstance(author, dict):
            author = author.get("name") or author.get("email")
        reasons = info.get("disable_reasons")
        disabled = bool(reasons) if reasons is not None else info.get("state") == 0
        out.append({
            "id": ext_id,
            "name": name,
            "version": manifest.get("version"),
            "author": author,
            "homepage": manifest.get("homepage_url"),
            "enabled": not disabled,
            "preinstalled": location in DEFAULT_LOCATIONS,
            "fromWebStore": bool(info.get("from_webstore", location == 1)),
        })
    return sorted(out, key=lambda e: e["name"].lower())


def add_extensions(export, arc_dir):
    for p in export["profiles"]:
        p["extensions"] = read_extensions(arc_dir, p["directory"])
    return export
