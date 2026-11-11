"""Edit a Firefox/Zen profile's prefs.js safely (only while the browser is closed).

Firefox rewrites prefs.js when it quits, so edits made while it runs are lost.
We edit prefs.js rather than a persistent user.js so people can still change
these settings later in the browser's own settings.
"""

import json
import os
import re
import shutil
import time
from pathlib import Path

_LINE = re.compile(r'^\s*user_pref\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*(.*?)\s*\)\s*;\s*$')


def format_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"unsupported pref value {value!r}")


def parse_value(text):
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return json.loads(text)
    except ValueError:
        return text


def read_prefs(path):
    """{name: value} for every user_pref line in prefs.js (or user.js)."""
    out = {}
    path = Path(path)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _LINE.match(line)
            if m:
                out[json.loads(f'"{m.group(1)}"')] = parse_value(m.group(2))
    return out


def edit_prefs(path, set_values=None, remove=()):
    """Remove any lines for the given keys, then append the new values. Returns new text."""
    path = Path(path)
    set_values = dict(set_values or {})
    drop = set(remove) | set(set_values)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    kept = []
    for line in lines:
        m = _LINE.match(line)
        if m and json.loads(f'"{m.group(1)}"') in drop:
            continue
        kept.append(line)
    kept += [f"user_pref({json.dumps(k)}, {format_value(v)});" for k, v in set_values.items()]
    text = "\n".join(kept) + "\n"
    tmp = path.with_name(path.name + ".exit-arc.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return text


def backup_file(path, dest_dir, label=None):
    """Copy path into dest_dir with a timestamp. Returns the copy's path, or None if path is missing."""
    path = Path(path)
    if not path.exists():
        return None
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (label or path.name)
    if dest.exists():
        dest = dest_dir / f"{dest.stem}-{time.strftime('%H%M%S')}{dest.suffix}"
    shutil.copy2(path, dest)
    return dest


# --------------------------------------------------------------------------
# The settings each step changes
# --------------------------------------------------------------------------

VERTICAL_TABS = {
    "sidebar.revamp": True,
    "sidebar.verticalTabs": True,
    "sidebar.visibility": "always-show",
}

RESTORE_SESSION = {"browser.startup.page": 3}  # "Open previous windows and tabs"

NEWTAB_PREFIX = "browser.newtabpage.activity-stream."
# Tested on Firefox 159 and Zen 1.24 (both ship the same newtab add-on).
NEWTAB_CLEANUP = {
    "showSponsoredTopSites": False,
    "showSponsored": False,
    "default.sites": "",
    "widgets.enabled": False,
    "showWeather": False,
    "widgets.clocks.enabled": False,
    "widgets.crossword.enabled": False,
    "widgets.pictureOfTheDay.enabled": False,
}
