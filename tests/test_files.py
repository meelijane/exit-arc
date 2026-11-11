"""mozlz4, prefs.js and omni.ja helpers."""
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import helpers  # noqa: F401  (sets sys.path)

from exit_arc import gecko, mozlz4, prefs


class Mozlz4Tests(unittest.TestCase):
    def test_round_trip_sizes(self):
        for n in (0, 1, 14, 15, 16, 269, 270, 271, 5000):
            data = bytes(i % 251 for i in range(n))
            self.assertEqual(mozlz4.decompress(mozlz4.compress(data)), data, n)

    def test_decodes_real_matches(self):
        # literals "abc", then a 9-byte match at offset 3, then literals "XYZWV"
        block = bytes([0x35]) + b"abc" + bytes([3, 0]) + bytes([0x50]) + b"XYZWV"
        raw = mozlz4.MAGIC + (17).to_bytes(4, "little") + block
        self.assertEqual(mozlz4.decompress(raw), b"abcabcabcabcXYZWV")

    def test_long_match_length(self):
        # 1 literal "a", match length 4+15+3=22 at offset 1, then 5 literals
        block = bytes([0x1F]) + b"a" + bytes([1, 0, 3]) + bytes([0x50]) + b"12345"
        raw = mozlz4.MAGIC + (28).to_bytes(4, "little") + block
        self.assertEqual(mozlz4.decompress(raw), b"a" * 23 + b"12345")

    def test_rejects_bad_files(self):
        with self.assertRaises(ValueError):
            mozlz4.decompress(b"notmagic" + b"\0" * 8)
        with self.assertRaises(ValueError):
            mozlz4.decompress(mozlz4.MAGIC + (99).to_bytes(4, "little") + bytes([0x30]) + b"abc")

    def test_json_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.jsonlz4"
            mozlz4.write_json(path, {"emoji": "🏠", "n": [1, 2]})
            self.assertEqual(mozlz4.read_json(path), {"emoji": "🏠", "n": [1, 2]})


class PrefsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "prefs.js"
        self.path.write_text('// header\nuser_pref("sidebar.revamp", false);\nuser_pref("keep.me", "x");\n'
                             'user_pref("sidebar.verticalTabs", false);\nuser_pref("sidebar.verticalTabs", false);\n')

    def tearDown(self):
        self.tmp.cleanup()

    def test_replaces_old_lines_without_duplicates(self):
        prefs.edit_prefs(self.path, prefs.VERTICAL_TABS)
        text = self.path.read_text()
        self.assertEqual(text.count("sidebar.verticalTabs"), 1)
        self.assertEqual(text.count("sidebar.revamp"), 1)
        self.assertIn("// header", text)
        self.assertEqual(prefs.read_prefs(self.path), {"keep.me": "x", "sidebar.revamp": True,
                                                       "sidebar.verticalTabs": True,
                                                       "sidebar.visibility": "always-show"})

    def test_idempotent(self):
        prefs.edit_prefs(self.path, prefs.VERTICAL_TABS)
        once = self.path.read_text()
        prefs.edit_prefs(self.path, prefs.VERTICAL_TABS)
        self.assertEqual(self.path.read_text(), once)

    def test_value_types_and_remove(self):
        prefs.edit_prefs(self.path, {"a.int": 3, "a.str": 'say "hi"', "a.empty": ""}, remove=["keep.me"])
        values = prefs.read_prefs(self.path)
        self.assertEqual((values["a.int"], values["a.str"], values["a.empty"]), (3, 'say "hi"', ""))
        self.assertNotIn("keep.me", values)

    def test_creates_missing_file(self):
        path = Path(self.tmp.name) / "new" / "prefs.js"
        path.parent.mkdir()
        prefs.edit_prefs(path, prefs.RESTORE_SESSION)
        self.assertEqual(prefs.read_prefs(path), {"browser.startup.page": 3})

    def test_backup(self):
        copy = prefs.backup_file(self.path, Path(self.tmp.name) / "bk")
        self.assertEqual(copy.read_text(), self.path.read_text())
        self.assertIsNone(prefs.backup_file(Path(self.tmp.name) / "missing.js", Path(self.tmp.name) / "bk"))


class OmniJaTests(unittest.TestCase):
    def make_app(self, d, source):
        app = Path(d) / "Fake.app"
        omni = app / "Contents" / "Resources" / "browser" / "omni.ja"
        omni.parent.mkdir(parents=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("other/file.txt", "nothing here")
            z.writestr("chrome/browser/builtin-addons/" + gecko.NEWTAB_SOURCE, source)
        omni.write_bytes(b"\x00\x01\x02\x03" + buf.getvalue())  # Mozilla jars start with extra bytes
        return app

    def test_known_and_unknown_names(self):
        with tempfile.TemporaryDirectory() as d:
            app = self.make_app(d, 'const PREFS = ["showSponsored", "widgets.enabled"];')
            known, unknown = gecko.known_pref_names(app, ["showSponsored", "widgets.enabled", "showWeather"])
            self.assertEqual(known, ["showSponsored", "widgets.enabled"])
            self.assertEqual(unknown, ["showWeather"])

    def test_unreadable_means_assume_known(self):
        self.assertEqual(gecko.known_pref_names(None, ["a"]), (["a"], []))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(gecko.known_pref_names(Path(d), ["a"]), (["a"], []))


if __name__ == "__main__":
    unittest.main()
