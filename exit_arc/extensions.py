"""Find Firefox/Zen versions of Arc's (Chrome) extensions.

There's no official Chrome-ID to Firefox mapping. We use a short hand-checked
list, then (only when asked, with --extensions) search Mozilla's public add-ons
site, addons.mozilla.org (AMO). A search hit only counts as the same extension
when the developer matches: same author name or same website. Anything else is
shown as "maybe" and never installed automatically.

The only data sent to AMO is extension names, and only with --extensions.
Installing always goes through the browser's own "Add ...?" prompt.
"""

import json
import re
import urllib.parse
import urllib.request

from . import __version__

AMO_API = "https://addons.mozilla.org/api/v5/addons"
AMO_PAGE = "https://addons.mozilla.org/firefox/addon/{slug}/"
AMO_XPI = "https://addons.mozilla.org/firefox/downloads/latest/{slug}/latest.xpi"

# Chrome Web Store id -> AMO slug, checked by hand (same developer) on 2026-11-10.
KNOWN = {
    "aeblfdkhhhdcdjpifhhbdiojplfjncoa": "1password-x-password-manager",
    "nngceckbapebfimnlniiiahkandclblb": "bitwarden-password-manager",
    "hdokiejnpimakedhajhdlcegeplioahd": "lastpass-password-manager",
    "ldgfbffkinooeloadekpmfoklnobpien": "raindropio",
    "cjpalhdlnbpafiamejdnhcphjbkeiagm": "ublock-origin",
    "eimadpbcbfnmbkopoojfekhnkhdbieeh": "darkreader",
    "pkehgijcmpdhfbdbbnkijodmdjhbjlgp": "privacy-badger17",
    "kbfnbcaeplbcioakkpcpgfkobkghlhen": "grammarly-1",
    "fmkadmapgofadopljbjfkapdkoienihi": "react-devtools",
    "nhdogjmejiglipccpnnnanhbledajbpd": "vue-js-devtools",
    "gppongmhjkpfnbhagpmjfkannfbllamg": "wappalyzer",
}

# Hints shown when there's no confirmed Firefox version.
HINTS = {
    "fdpohaocaechififmbbbbbknoalclacl": "Firefox has full-page screenshots built in: right-click > Take Screenshot",
    "fcoeoabgfenejglbffodgkkbkcdhcgfn": "use the Claude website or desktop app",
}

_SUFFIXES = {"inc", "llc", "ltd", "limited", "gmbh", "corp", "co", "devs", "dev", "team", "the"}


def _tokens(name):
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in _SUFFIXES}


def _domain(url):
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _text(value):
    if isinstance(value, dict):
        return value.get("en-US") or next(iter(value.values()), "")
    return value or ""


def same_developer(ext, addon):
    """True when an AMO add-on is clearly by the same developer as the Chrome extension."""
    authors = [a.get("name") for a in addon.get("authors") or []]
    if ext.get("author") and any(_tokens(ext["author"]) and _tokens(ext["author"]) == _tokens(a) for a in authors):
        return True
    home = _text((addon.get("homepage") or {}).get("url") if isinstance(addon.get("homepage"), dict)
                 else addon.get("homepage"))
    return bool(ext.get("homepage") and home and _domain(ext["homepage"]) == _domain(home))


def _name_close(ext_name, addon_name):
    a, b = _tokens(ext_name), _tokens(addon_name)
    return bool(a) and len(a & b) >= max(1, min(len(a), 2))


class AMO:
    """Tiny client for addons.mozilla.org. Tests replace fetch_json."""

    def __init__(self, timeout=10):
        self.timeout = timeout

    def fetch_json(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": f"exit-arc/{__version__}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def addon(self, slug):
        return self.fetch_json(f"{AMO_API}/addon/{urllib.parse.quote(slug)}/?lang=en-US")

    def search(self, name):
        q = urllib.parse.urlencode({"q": name, "app": "firefox", "type": "extension", "sort": "users",
                                    "lang": "en-US", "page_size": 5})
        return self.fetch_json(f"{AMO_API}/search/?{q}").get("results", [])


def _match(addon, status="match"):
    slug = addon.get("slug")
    return {"status": status, "slug": slug, "name": _text(addon.get("name")) or slug,
            "url": AMO_PAGE.format(slug=slug), "install": AMO_XPI.format(slug=slug)}


def firefox_availability(ext, amo=None, log=None):
    """{'status': 'match'|'possible'|'none'|..., ...} for one Chrome extension."""
    if ext.get("preinstalled"):
        return {"status": "none", "note": "came with Arc/Chrome"}
    slug = KNOWN.get(ext["id"])
    if slug:
        return _match({"slug": slug, "name": ext["name"]})
    if amo is None:
        return {"status": "unknown", "note": "run with --extensions to look it up"}
    try:
        results = amo.search(ext["name"])
    except Exception as e:  # network trouble: say so, don't fail the run
        if log:
            log(f"  Couldn't search addons.mozilla.org for {ext['name']}: {e}")
        return {"status": "unknown", "note": "lookup failed"}
    for addon in results:
        if _name_close(ext["name"], _text(addon.get("name"))) and same_developer(ext, addon):
            return _match(addon)
    close = [a for a in results if _name_close(ext["name"], _text(a.get("name")))]
    if close:
        m = _match(close[0], "possible")
        m["note"] = "not confirmed to be the same developer"
        if HINTS.get(ext["id"]):
            m["hint"] = HINTS[ext["id"]]
        return m
    return {"status": "none", "note": HINTS.get(ext["id"], "no Firefox version found")}


def annotate(export, lookup=False, amo=None, log=None):
    """Add an 'availability' map (firefox/zen/chrome) to every extension in the export."""
    amo = (amo or AMO()) if lookup else None
    cache = {}
    for p in export["profiles"]:
        for ext in p.get("extensions") or []:
            if ext["id"] not in cache:
                cache[ext["id"]] = firefox_availability(ext, amo, log)
            ff = cache[ext["id"]]
            if ext.get("preinstalled"):
                chrome = {"status": "none", "note": "came with Arc/Chrome"}
            elif ext.get("fromWebStore"):
                chrome = {"status": "match", "name": "Chrome Web Store",
                          "url": f"https://chromewebstore.google.com/detail/{ext['id']}"}
            else:
                chrome = {"status": "none", "note": "not from the Chrome Web Store"}
            ext["availability"] = {"firefox": ff, "zen": ff, "chrome": chrome}
    return export


def unique_extensions(export):
    seen, out = set(), []
    for p in export["profiles"]:
        for e in p.get("extensions") or []:
            if e["id"] not in seen:
                seen.add(e["id"])
                out.append(e)
    return out


def report(export, target):
    """Lines of an 'extension -> status' table for one target."""
    rows = []
    for e in unique_extensions(export):
        a = (e.get("availability") or {}).get(target) or {"status": "unknown"}
        if a["status"] == "match":
            state = "can install" + (f" ({a['name']})" if target != "chrome" else "")
        elif a["status"] == "possible":
            state = f"maybe: {a['name']} ({a['url']}), not installed automatically"
        elif a["status"] == "unknown":
            state = "not checked" + (f" ({a['note']})" if a.get("note") else "")
        else:
            state = "no version for this browser" + (f" ({a['note']})" if a.get("note") else "")
        if a.get("hint") and a["status"] != "none":
            state += f"; tip: {a['hint']}"
        flag = "" if e["enabled"] else " [disabled in Arc]"
        rows.append(f"  {e['name']}{flag}: {state}")
    return rows


def install_urls(export, target):
    urls = []
    for e in unique_extensions(export):
        a = (e.get("availability") or {}).get(target) or {}
        if a.get("status") == "match" and e["enabled"]:
            urls.append(a["install"] if target in ("firefox", "zen") else a["url"])
    return urls
