import csv
import io
import json
import unittest

from fake_firefox import parse_bookmarks_html
from helpers import FIXTURE, find, flat_links, titles

from exit_arc import ToolError, arc, exporters, extensions


def fixture_export():
    export = arc.read_arc(FIXTURE)
    arc.add_extensions(export, FIXTURE)
    return export


class HtmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = fixture_export()

    def test_toolbar_layout_multi_profile(self):
        tree = parse_bookmarks_html(exporters.build_html(self.export, "toolbar"))
        self.assertEqual(tree["menu"], [])
        self.assertEqual(titles(tree["toolbar"]), ["Default", "Work"])
        default = tree["toolbar"][0]["children"]
        self.assertEqual(titles(default), ["Mail", "Cal", "🏠 Home", "📚 Reading"])
        self.assertEqual(find(default, "🏠 Home")["children"][0]["title"], 'Docs & "Notes" <b>')
        self.assertEqual(len(flat_links(tree["toolbar"])), 10)

    def test_toolbar_layout_single_profile_is_flat(self):
        one = arc.filter_profiles(self.export, ["Default"])
        tree = parse_bookmarks_html(exporters.build_html(one, "toolbar"))
        self.assertEqual(titles(tree["toolbar"]), ["Mail", "Cal", "🏠 Home", "📚 Reading"])

    def test_folder_layout(self):
        one = arc.filter_profiles(self.export, ["Default"])
        tree = parse_bookmarks_html(exporters.build_html(one, "folder"))
        self.assertEqual(tree["toolbar"], [])
        self.assertEqual(tree["menu"][0]["title"], "Arc")
        self.assertEqual(titles(tree["menu"][0]["children"]), ["Favourites", "🏠 Home", "📚 Reading"])
        multi = parse_bookmarks_html(exporters.build_html(self.export, "folder"))
        self.assertEqual(titles(multi["menu"][0]["children"]), ["Default", "Work"])

    def test_include_unpinned(self):
        tree = parse_bookmarks_html(exporters.build_html(self.export, "toolbar", include_unpinned=True))
        home = find(tree["toolbar"][0]["children"], "🏠 Home")
        self.assertEqual(find(home["children"], "Open tabs (unpinned)")["children"][0]["url"],
                         "https://open.example.com/unpinned")

    def test_escaping(self):
        text = exporters.build_html(self.export)
        self.assertIn('HREF="https://example.org/tools?a=1&amp;b=2"', text)
        self.assertIn("Docs &amp; &quot;Notes&quot; &lt;b&gt;", text)
        self.assertIn('PERSONAL_TOOLBAR_FOLDER="true"', text)


class CsvTests(unittest.TestCase):
    def test_one_row_per_tab_with_quoting(self):
        rows = list(csv.reader(io.StringIO(exporters.build_csv(fixture_export()))))
        self.assertEqual(rows[0], ["profile", "space", "folder_path", "title", "url", "kind"])
        body = rows[1:]
        self.assertEqual(len(body), 11)  # 3 favourites + 7 pinned + 1 unpinned
        self.assertIn(["Default", "🏠 Home", "", 'Docs & "Notes" <b>', "https://Example.com", "pinned"], body)
        self.assertIn(["Default", "🏠 Home", "Tools / Nested", "Deep link", "https://deep.example.net/path/",
                       "pinned"], body)
        self.assertIn(["Work", "", "", "Chat", "https://chat.example.com/", "favourite"], body)
        self.assertIn(["Default", "🏠 Home", "", "An open tab", "https://open.example.com/unpinned", "unpinned"], body)
        self.assertIn('"Docs & ""Notes"" <b>"', exporters.build_csv(fixture_export()))


class MarkdownTests(unittest.TestCase):
    def test_structure(self):
        md = exporters.build_markdown(fixture_export())
        self.assertIn("## Profile: Work", md)
        self.assertIn("### 🏠 Home", md)
        self.assertIn("### Favourites", md)
        self.assertIn("- **Tools**\n  - [Tools page](https://example.org/tools?a=1&b=2)\n  - **Nested**\n"
                      "    - [Deep link](https://deep.example.net/path/)", md)
        self.assertIn(r'- [Docs & "Notes" \<b\>](https://Example.com)', md)
        self.assertIn("#### Open tabs (unpinned)", md)
        self.assertIn("**Empty folder** (empty folder)", md)

    def test_extensions_section(self):
        export = extensions.annotate(fixture_export())
        md = exporters.build_markdown(export)
        self.assertIn("| Extension | Firefox | Zen | Chrome |", md)
        self.assertIn("| 1Password – Password Manager | yes ([1Password – Password Manager]"
                      "(https://addons.mozilla.org/firefox/addon/1password-x-password-manager/))", md)
        self.assertIn("Disabled Thing (disabled)", md)
        self.assertIn("Docs Offline Example (came with Arc)", md)
        self.assertIn("not checked", md)

    def test_url_with_parens_is_wrapped(self):
        self.assertEqual(exporters._md_url("https://x.example/a_(b)"), "<https://x.example/a_(b)>")


class JsonAndFormatTests(unittest.TestCase):
    def test_json_round_trips(self):
        data = json.loads(exporters.build_json(fixture_export()))
        self.assertEqual([p["name"] for p in data["profiles"]], ["Default", "Work"])
        self.assertEqual(len(data["profiles"][0]["extensions"]), 6)

    def test_parse_formats(self):
        self.assertEqual(exporters.parse_formats("csv, markdown,csv"), ["csv", "md"])
        with self.assertRaises(ToolError):
            exporters.parse_formats("pdf")

    def test_summary(self):
        text = "\n".join(exporters.summary(fixture_export()))
        self.assertIn("🏠 Home: 5 pinned links, 2 folders, 1 open unpinned (not bookmarked)", text)
        self.assertIn("Profile: Work (Profile 2)", text)
        self.assertIn("Total links to bookmark: 10", text)


if __name__ == "__main__":
    unittest.main()
