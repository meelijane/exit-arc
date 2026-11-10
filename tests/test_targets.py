"""Zen spaces/Essentials, Chrome bookmarks, and extension matching."""
import hashlib
import json
import unittest

from helpers import AMO_RESULTS, FIXTURE, FakeAMO, SandboxTest

from exit_arc import arc, chrome, exporters, extensions, gecko, mozlz4, zen


def fixture_export():
    export = arc.read_arc(FIXTURE)
    arc.add_extensions(export, FIXTURE)
    return export


class ZenTests(SandboxTest):
    def session(self, p):
        return mozlz4.read_json(p / zen.SESSION_FILE)

    def test_fresh_profile(self):
        p = self.profile()
        r = zen.apply(p, fixture_export(), now_ms=1000)
        self.assertEqual(r, {"spaces_added": 3, "spaces_reused": 0, "pinned": 7, "folders": 3, "essentials": 3})
        d = self.session(p)
        self.assertEqual([(s["name"], s["icon"]) for s in d["spaces"]],
                         [("Home (Default)", "🏠"), ("Reading (Default)", "📚"), ("Projects (Work)", None)])
        home = d["spaces"][0]["uuid"]
        ess = [t for t in d["tabs"] if t["zenEssential"]]
        self.assertEqual([gecko.tab_url(t) for t in ess],
                         ["https://mail.example.com/", "https://calendar.example.com/", "https://chat.example.com/"])
        self.assertTrue(all(t["pinned"] for t in d["tabs"]))
        self.assertEqual(ess[1]["zenStaticLabel"], "Cal")  # renamed in Arc
        self.assertNotIn("zenStaticLabel", ess[0])
        self.assertEqual(d["tabs"][:3], ess)  # essentials first

        folders = {f["name"]: f for f in d["folders"]}
        self.assertIsNone(folders["Tools"]["parentId"])
        self.assertEqual(folders["Nested"]["parentId"], folders["Tools"]["id"])
        self.assertEqual(folders["Tools"]["workspaceId"], home)
        self.assertEqual(len(folders["Empty folder"]["emptyTabIds"]), 1)
        self.assertEqual({g["id"] for g in d["groups"]}, {f["id"] for f in d["folders"]})
        deep = next(t for t in d["tabs"] if gecko.tab_url(t) == "https://deep.example.net/path/")
        self.assertEqual(deep["groupId"], folders["Nested"]["id"])
        # The folder after the first tab records it as its previous sibling.
        first = next(t for t in d["tabs"] if gecko.tab_url(t) == "https://Example.com")
        self.assertEqual(folders["Tools"]["prevSiblingInfo"], {"type": "tab", "id": first["zenSyncId"]})

    def test_rerun_adds_nothing(self):
        p = self.profile()
        zen.apply(p, fixture_export())
        before = self.session(p)
        r = zen.apply(p, fixture_export())
        self.assertEqual(r, {"spaces_added": 0, "spaces_reused": 3, "pinned": 0, "folders": 0, "essentials": 0})
        self.assertEqual(len(self.session(p)["tabs"]), len(before["tabs"]))

    def test_keeps_existing_and_drops_blank_default(self):
        p = self.profile()
        mozlz4.write_json(p / zen.SESSION_FILE, {"spaces": [{"uuid": "d", "name": "Space"}], "tabs": [
            {"entries": [{"url": "https://welcome.example/"}], "index": 1, "zenWorkspace": "d"}]})
        zen.apply(p, arc.filter_profiles(fixture_export(), ["Default"]), backup_dir=self.dir / "bk")
        d = self.session(p)
        self.assertEqual([s["name"] for s in d["spaces"]], ["Home", "Reading"])
        welcome = d["tabs"][-1]
        self.assertEqual(welcome["zenWorkspace"], d["spaces"][0]["uuid"])
        self.assertTrue((self.dir / "bk" / zen.SESSION_FILE).exists())

    def test_user_spaces_are_kept(self):
        p = self.profile()
        mozlz4.write_json(p / zen.SESSION_FILE, {"spaces": [{"uuid": "u", "name": "Mine", "icon": "⭐"}], "tabs": [
            {"entries": [{"url": "https://mine.example/"}], "index": 1, "pinned": True, "zenWorkspace": "u"}]})
        zen.apply(p, arc.filter_profiles(fixture_export(), ["Work"]), essentials=False)
        d = self.session(p)
        self.assertEqual([s["name"] for s in d["spaces"]], ["Mine", "Projects"])
        self.assertEqual(gecko.tab_url(d["tabs"][0]), "https://mine.example/")
        self.assertFalse(any(t.get("zenEssential") for t in d["tabs"]))


class ChromeTests(SandboxTest):
    def tree(self):
        return exporters.build_tree(fixture_export(), "toolbar")

    def bookmarks(self, p):
        return json.loads((p / "Bookmarks").read_text())

    def test_new_bookmarks_file(self):
        p = self.profile("Chrome/Default")
        added, replaced = chrome.add_bookmarks(p, *self.tree(), now="1")
        self.assertEqual((added, replaced), (10, 0))
        d = self.bookmarks(p)
        bar = d["roots"]["bookmark_bar"]["children"]
        self.assertEqual([c["name"] for c in bar], ["Default", "Work"])
        self.assertEqual(bar[0]["meta_info"], {"exit_arc": "1"})
        self.assertEqual(d["checksum"], chrome.checksum(d))
        ids = []

        def walk(n):
            ids.append(n["id"])
            for c in n.get("children", []):
                walk(c)
        for r in d["roots"].values():
            walk(r)
        self.assertEqual(len(ids), len(set(ids)))

    def test_keeps_existing_and_rerun_replaces_ours(self):
        p = self.profile("Chrome/Default")
        data = chrome.empty_bookmarks("1")
        data["roots"]["bookmark_bar"]["children"].append(
            {"id": "50", "name": "Mine", "type": "url", "url": "https://mine.example/", "guid": "g", "date_added": "1"})
        (p / "Bookmarks").write_text(json.dumps(data))
        chrome.add_bookmarks(p, *self.tree(), backup_dir=self.dir / "bk")
        chrome.add_bookmarks(p, *self.tree())
        bar = self.bookmarks(p)["roots"]["bookmark_bar"]["children"]
        self.assertEqual([c["name"] for c in bar], ["Mine", "Default", "Work"])
        self.assertTrue((self.dir / "bk" / "Bookmarks").exists())
        self.assertGreater(int(bar[1]["id"]), 50)

    def test_checksum_matches_chromium_algorithm(self):
        data = {"roots": {
            "bookmark_bar": {"id": "1", "name": "Bar", "type": "folder", "children": [
                {"id": "4", "name": "Ä", "type": "url", "url": "https://a.example/"}]},
            "other": {"id": "2", "name": "Other", "type": "folder", "children": []},
            "synced": {"id": "3", "name": "Mobile", "type": "folder", "children": []}}}
        md5 = hashlib.md5()
        for part in (b"1", "Bar".encode("utf-16-le"), b"folder", b"4", "Ä".encode("utf-16-le"), b"url",
                     b"https://a.example/", b"2", "Other".encode("utf-16-le"), b"folder",
                     b"3", "Mobile".encode("utf-16-le"), b"folder"):
            md5.update(part)
        self.assertEqual(chrome.checksum(data), md5.hexdigest())

    def test_default_profile_and_sync_warning(self):
        root = self.dir / "Chrome"
        root.mkdir()
        (root / "Local State").write_text(json.dumps({"profile": {"last_used": "Profile 3"}}))
        self.assertEqual(chrome.default_profile(root), root / "Profile 3")
        p = self.profile("Chrome/Profile 3")
        self.assertIsNone(chrome.sync_warning(p))
        (p / "Preferences").write_text(json.dumps({"account_info": [{"email": "someone@example.com"}]}))
        self.assertIn("signed in", chrome.sync_warning(p))

    def test_webstore_urls(self):
        exts = arc.read_extensions(FIXTURE, "Default")
        urls = chrome.webstore_urls(exts)
        self.assertIn("https://chromewebstore.google.com/detail/aeblfdkhhhdcdjpifhhbdiojplfjncoa", urls)
        self.assertNotIn("https://chromewebstore.google.com/detail/dddddddddddddddddddddddddddddddd", urls)
        self.assertNotIn("https://chromewebstore.google.com/detail/ffffffffffffffffffffffffffffffff", urls)


class ExtensionMatchTests(unittest.TestCase):
    def annotated(self, amo=None):
        export = fixture_export()
        extensions.annotate(export, lookup=amo is not None, amo=amo)
        return {e["id"]: e["availability"] for e in export["profiles"][0]["extensions"]}

    def test_offline_uses_known_list_only(self):
        a = self.annotated()
        self.assertEqual(a["aeblfdkhhhdcdjpifhhbdiojplfjncoa"]["firefox"]["slug"], "1password-x-password-manager")
        self.assertEqual(a["abcdefghijklmnopabcdefghijklmnop"]["firefox"]["status"], "unknown")
        self.assertEqual(a["dddddddddddddddddddddddddddddddd"]["firefox"]["status"], "none")

    def test_lookup_matches_same_developer_only(self):
        amo = FakeAMO(AMO_RESULTS)
        a = self.annotated(amo)
        self.assertEqual(a["abcdefghijklmnopabcdefghijklmnop"]["firefox"]["slug"], "tab-notes-example")
        self.assertEqual(a["abcdefghijklmnopabcdefghijklmnop"]["zen"]["status"], "match")
        self.assertEqual(a["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"]["firefox"]["status"], "possible")
        self.assertEqual(a["ffffffffffffffffffffffffffffffff"]["firefox"]["status"], "none")
        self.assertNotIn("1Password – Password Manager", amo.queries)  # known: no lookup
        self.assertNotIn("Docs Offline Example", amo.queries)  # pre-installed: no lookup

    def test_chrome_availability(self):
        a = self.annotated()
        self.assertEqual(a["aeblfdkhhhdcdjpifhhbdiojplfjncoa"]["chrome"]["status"], "match")
        self.assertEqual(a["ffffffffffffffffffffffffffffffff"]["chrome"]["status"], "none")

    def test_install_urls_skip_disabled_and_unconfirmed(self):
        export = fixture_export()
        extensions.annotate(export, lookup=True, amo=FakeAMO(AMO_RESULTS))
        self.assertEqual(extensions.install_urls(export, "firefox"), [
            "https://addons.mozilla.org/firefox/downloads/latest/1password-x-password-manager/latest.xpi",
            "https://addons.mozilla.org/firefox/downloads/latest/tab-notes-example/latest.xpi"])
        self.assertEqual(len(extensions.install_urls(export, "chrome")), 3)  # 1Password, Tab Notes, Snapshot

    def test_lookup_failure_is_not_fatal(self):
        class Broken:
            def search(self, name):
                raise OSError("offline")
        a = self.annotated(Broken())
        self.assertEqual(a["abcdefghijklmnopabcdefghijklmnop"]["firefox"], {"status": "unknown",
                                                                            "note": "lookup failed"})

    def test_same_developer_rules(self):
        ext = {"author": "Mussabekov Rustem", "homepage": "https://app.raindrop.io"}
        self.assertTrue(extensions.same_developer(ext, {"authors": [{"name": "Rustem Mussabekov"}]}))
        self.assertTrue(extensions.same_developer({"homepage": "https://app.raindrop.io"},
                                                  {"homepage": {"url": {"en-US": "https://raindrop.io"}}}))
        self.assertFalse(extensions.same_developer({"author": "A"}, {"authors": [{"name": "B"}]}))


if __name__ == "__main__":
    unittest.main()
