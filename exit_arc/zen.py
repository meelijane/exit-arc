"""Zen: Arc spaces become Zen spaces (with pinned tabs and folders), and Arc
Favourites become Zen Essentials.

Zen 1.2x keeps its sidebar in <profile>/zen-sessions.jsonlz4:
  {"spaces": [...], "tabs": [...], "groups": [...], "folders": [...], ...}
Tabs carry "zenWorkspace" (space uuid), "zenEssential" and "pinned". A Zen
folder is a Firefox tab group (tabs point at it with "groupId") plus a matching
"folders" record; nested folders point at their parent with "parentId".
Checked against Zen 1.24.1b: it loads these files and saves them back intact.

Existing Zen data is kept: new spaces are added after yours, a space with the
same name is reused, and URLs already pinned there are skipped. The only thing
removed is the empty default "Space" a brand-new Zen profile starts with.
"""

import time
import uuid
from pathlib import Path

from . import mozlz4
from .gecko import normalize_url, tab_state, tab_url
from .prefs import backup_file

SESSION_FILE = "zen-sessions.jsonlz4"


def default_theme():
    return {"type": "gradient", "gradientColors": [], "opacity": 0.5, "texture": 0}


def load(profile):
    path = Path(profile) / SESSION_FILE
    data = mozlz4.read_json(path) if path.exists() else {}
    for key in ("tabs", "spaces", "folders", "groups", "splitViewData"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def _drop_blank_default_space(data):
    """A new Zen profile has one empty space called 'Space'. Replace it rather than add to it."""
    if len(data["spaces"]) != 1 or data["spaces"][0].get("name") != "Space":
        return None
    sid = data["spaces"][0]["uuid"]
    if any(t.get("pinned") and t.get("zenWorkspace") == sid for t in data["tabs"]):
        return None
    data["spaces"] = []
    return sid


class _Builder:
    def __init__(self, data, now_ms):
        self.data = data
        self.now = now_ms
        self.n = 0
        self.added_tabs = 0
        self.added_folders = 0

    def next_id(self):
        self.n += 1
        return f"{self.now}-{self.n}"

    def tab(self, link, space, **extra):
        fields = {"zenWorkspace": space, "zenSyncId": str(uuid.uuid4()), "zenEssential": False}
        fields.update(extra)
        t = tab_state(link["url"], link["title"], self.now, **fields)
        if link.get("renamed"):
            t["zenStaticLabel"] = link["title"]
        return t

    def space_items(self, nodes, space, existing_urls, parent=None, group=None, existing_folders=()):
        """Return the tabs for nodes, adding groups/folders as it goes."""
        tabs = []
        prev = None  # (type, id) of the previous sibling inside this container
        for n in nodes:
            if n["type"] == "folder" and parent is None and n["title"] in existing_folders:
                continue  # already brought over by an earlier run
            if n["type"] == "link":
                key = normalize_url(n["url"])
                if group is None and key in existing_urls:
                    continue
                existing_urls.add(key)
                extra = {"groupId": group} if group else {}
                t = self.tab(n, space, **extra)
                tabs.append(t)
                self.added_tabs += 1
                prev = ("tab", t["zenSyncId"])
            else:
                gid = self.next_id()
                child_tabs = self.space_items(n["children"], space, existing_urls, parent=gid, group=gid)
                empty_ids = []
                if not any(t.get("groupId") == gid for t in child_tabs):
                    # A folder needs one tab of its own to exist; Zen hides "empty" ones.
                    blank = tab_state("about:blank", "", self.now, zenWorkspace=space, zenSyncId=str(uuid.uuid4()),
                                      zenEssential=False, zenIsEmpty=True, groupId=gid)
                    child_tabs.insert(0, blank)
                    empty_ids.append(blank["zenSyncId"])
                self.data["groups"].append({"id": gid, "name": n["title"], "color": "zen-workspace-color",
                                            "collapsed": False, "pinned": True, "saveOnWindowClose": True})
                self.data["folders"].append({
                    "pinned": True, "essential": False, "splitViewGroup": False, "id": gid, "name": n["title"],
                    "collapsed": False, "saveOnWindowClose": True, "parentId": parent,
                    "prevSiblingInfo": {"type": prev[0], "id": prev[1]} if prev else {"type": "start", "id": None},
                    "emptyTabIds": empty_ids, "userIcon": None, "isLiveFolder": False, "workspaceId": space,
                })
                self.added_folders += 1
                tabs += child_tabs
                prev = ("group", gid)
        return tabs


def _flatten(nodes):
    for n in nodes:
        if n["type"] == "link":
            yield n
        else:
            yield from _flatten(n["children"])


def apply(profile, export, spaces=True, essentials=True, backup_dir=None, now_ms=None):
    """Write Arc spaces/favourites into a closed Zen profile. Returns a summary dict."""
    profile = Path(profile)
    now_ms = now_ms or int(time.time() * 1000)
    path = profile / SESSION_FILE
    if backup_dir and path.exists():
        backup_file(path, backup_dir, SESSION_FILE)
    data = load(profile)
    dropped = _drop_blank_default_space(data) if spaces else None
    b = _Builder(data, now_ms)
    multi = len(export["profiles"]) > 1
    old_tabs = data["tabs"]
    new_essentials, new_pinned = [], []
    result = {"spaces_added": 0, "spaces_reused": 0, "pinned": 0, "folders": 0, "essentials": 0}

    space_ids = []
    if spaces:
        for p in export["profiles"]:
            for s in p["spaces"]:
                name = s["title"] + (f' ({p["name"]})' if multi else "")
                icon = s["emoji"] or None
                match = next((x for x in data["spaces"] if x.get("name") == name and x.get("icon") == icon), None)
                if match:
                    sid = match["uuid"]
                    result["spaces_reused"] += 1
                else:
                    sid = str(uuid.uuid4())
                    data["spaces"].append({"uuid": sid, "name": name, "icon": icon, "theme": default_theme(),
                                           "containerTabId": 0})
                    result["spaces_added"] += 1
                space_ids.append(sid)
                existing = {normalize_url(tab_url(t) or "") for t in old_tabs
                            if t.get("pinned") and not t.get("zenEssential") and t.get("zenWorkspace") == sid
                            and not t.get("groupId")}
                folders = {f.get("name") for f in data["folders"] if f.get("workspaceId") == sid and not f.get("parentId")}
                new_pinned += b.space_items(s["pinned"], sid, existing, existing_folders=folders)
    result["pinned"] = b.added_tabs
    result["folders"] = b.added_folders

    if essentials:
        home = space_ids[0] if space_ids else (data["spaces"][0]["uuid"] if data["spaces"] else None)
        have = {normalize_url(tab_url(t) or "") for t in old_tabs if t.get("zenEssential")}
        for p in export["profiles"]:
            for link in _flatten(p["favourites"]):
                key = normalize_url(link["url"])
                if key in have:
                    continue
                have.add(key)
                new_essentials.append(b.tab(link, home, zenEssential=True))
        result["essentials"] = len(new_essentials)

    if dropped:  # move the default space's (unpinned) tabs into the first new space
        for t in old_tabs:
            if t.get("zenWorkspace") == dropped:
                t["zenWorkspace"] = space_ids[0] if space_ids else None

    old_essentials = [t for t in old_tabs if t.get("zenEssential")]
    old_pinned = [t for t in old_tabs if t.get("pinned") and not t.get("zenEssential")]
    old_other = [t for t in old_tabs if not t.get("pinned")]
    data["tabs"] = old_essentials + new_essentials + old_pinned + new_pinned + old_other
    data["lastCollected"] = now_ms
    mozlz4.write_json(path, data)
    return result
