"""Keep the Claude skill and plugin manifest in step with the CLI."""
import json
import re
import unittest

from helpers import ROOT

from exit_arc import __version__, cli


class SkillTests(unittest.TestCase):
    def test_every_option_in_the_skill_exists(self):
        text = (ROOT / "skills" / "exit-arc" / "SKILL.md").read_text()
        options = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", text))
        parser_options = set()
        for action in cli.build_parser()._actions:
            parser_options.update(action.option_strings)
        self.assertTrue(options)
        self.assertEqual(sorted(options - parser_options), [])

    def test_pyproject_version_matches(self):
        import re as _re
        text = (ROOT / "pyproject.toml").read_text()
        self.assertEqual(_re.search(r'(?m)^version = "([^"]+)"', text).group(1), __version__)

    def test_plugin_version_matches(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], __version__)


if __name__ == "__main__":
    unittest.main()
