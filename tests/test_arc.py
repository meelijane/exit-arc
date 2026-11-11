import tempfile
import unittest
from pathlib import Path

from helpers import FIXTURE, find, flat_links, titles

from exit_arc import ToolError, arc


class ReadArcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = arc.read_arc(FIXTURE)
        cls.by_dir = {p["directory"]: p for p in cls.export["profiles"]}

    def test_profiles_named_and_system_profile_ignored(self):
        self.assertEqual(list(self.by_dir), ["Default", "Profile 2"])
        self.assertEqual(self.by_dir["Default"]["name"], "Default")
        self.assertEqual(self.by_dir["Profile 2"]["name"], "Work")
        urls = [u for p in self.export["profiles"] for s in p["spaces"] for u in flat_links(s["pinned"])]
        self.assertNotIn("https://system.example.com/", urls)

    def test_spaces_titles_and_emoji(self):
        spaces = self.by_dir["Default"]["spaces"]
        self.assertEqual([(s["emoji"], s["title"]) for s in spaces], [("🏠", "Home"), ("📚", "Reading")])
        self.assertEqual(self.by_dir["Profile 2"]["spaces"][0]["emoji"], "")

    def test_nested_folders_and_split_view(self):
        home = self.by_dir["Default"]["spaces"][0]["pinned"]
        self.assertEqual(titles(home), ['Docs & "Notes" <b>', "Tools", "Left pane", "Right pane"])
        tools = find(home, "Tools")
        self.assertEqual(titles(tools["children"]), ["Tools page", "Nested"])
        self.assertEqual(find(tools["children"], "Nested")["children"][0]["url"], "https://deep.example.net/path/")

    def test_titles_and_renamed_flag(self):
        reading = self.by_dir["Default"]["spaces"][1]["pinned"]
        self.assertEqual(reading[0]["title"], "https://reading.example.org/article")
        favs = self.by_dir["Default"]["favourites"]
        self.assertEqual(titles(favs), ["Mail", "Cal"])
        self.assertTrue(favs[1]["renamed"])
        self.assertNotIn("renamed", favs[0])

    def test_favourites_per_profile(self):
        self.assertEqual(flat_links(self.by_dir["Profile 2"]["favourites"]), ["https://chat.example.com/"])

    def test_unpinned_kept(self):
        self.assertEqual(flat_links(self.by_dir["Default"]["spaces"][0]["unpinned"]),
                         ["https://open.example.com/unpinned"])

    def test_newcontainerids_only_space(self):
        self.assertEqual(len(self.by_dir["Default"]["spaces"][1]["pinned"]), 1)

    def test_skipped_counts(self):
        self.assertEqual(self.export["skipped"], {"easel": 1, "missing item": 1, "tab without URL": 1})

    def test_filter_profiles(self):
        only = arc.filter_profiles(self.export, ["work"])
        self.assertEqual([p["directory"] for p in only["profiles"]], ["Profile 2"])
        with self.assertRaises(ToolError):
            arc.filter_profiles(self.export, ["nope"])

    def test_missing_arc_dir_is_friendly(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ToolError) as cm:
            arc.read_arc(d)
        self.assertIn("Arc data not found", str(cm.exception))

    def test_works_without_local_state(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "StorableSidebar.json").write_text((FIXTURE / "StorableSidebar.json").read_text())
            export = arc.read_arc(d)
        self.assertEqual([p["directory"] for p in export["profiles"]], ["Default", "Profile 1", "Profile 2"])

    def test_profile_dir_markers(self):
        self.assertEqual(arc.profile_dir({"default": True}), "Default")
        self.assertEqual(arc.profile_dir({"custom": {"_0": {"directoryBasename": "Profile 7"}}}), "Profile 7")
        self.assertEqual(arc.profile_dir(None), "Default")

    def test_cycles_do_not_hang(self):
        data = {"sidebar": {"containers": [{"spaces": [], "topAppsContainerIDs": [{"default": True}, "A"],
                                            "items": ["A", {"id": "A", "childrenIds": ["B"], "data": {}},
                                                      "B", {"id": "B", "childrenIds": ["A"], "data": {"list": {}}}]}]}}
        parser = arc.SidebarParser(arc.pick_container(data))
        self.assertEqual(parser.container("A")[0]["children"], [])


class ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exts = {e["id"]: e for e in arc.read_extensions(FIXTURE, "Default")}

    def test_msg_names_resolved_case_insensitively(self):
        self.assertEqual(self.exts["aeblfdkhhhdcdjpifhhbdiojplfjncoa"]["name"], "1Password – Password Manager")
        self.assertEqual(self.exts["cccccccccccccccccccccccccccccccc"]["name"], "Disabled Thing")

    def test_newest_version_wins(self):
        self.assertEqual(self.exts["aeblfdkhhhdcdjpifhhbdiojplfjncoa"]["version"], "8.10.0")

    def test_states(self):
        self.assertFalse(self.exts["cccccccccccccccccccccccccccccccc"]["enabled"])
        self.assertTrue(self.exts["dddddddddddddddddddddddddddddddd"]["preinstalled"])
        self.assertNotIn("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", self.exts)  # built-in component
        self.assertFalse(self.exts["ffffffffffffffffffffffffffffffff"]["fromWebStore"])  # only in preferences

    def test_author_and_homepage(self):
        e = self.exts["abcdefghijklmnopabcdefghijklmnop"]
        self.assertEqual((e["author"], e["homepage"]), ("Example Labs Inc.", "https://www.tabnotes.example"))

    def test_profile_without_extensions(self):
        self.assertEqual(arc.read_extensions(FIXTURE, "Profile 2"), [])


if __name__ == "__main__":
    unittest.main()
