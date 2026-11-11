#!/usr/bin/env python3
"""Set exit-arc's version everywhere it's written: python3 scripts/bump_version.py 0.4.3"""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
    sys.exit("usage: scripts/bump_version.py X.Y.Z")
new = sys.argv[1]

init = root / "exit_arc" / "__init__.py"
init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{new}"', init.read_text()))

pyproject = root / "pyproject.toml"
pyproject.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{new}"', pyproject.read_text(), count=1))

plugin = root / ".claude-plugin" / "plugin.json"
data = json.loads(plugin.read_text())
data["version"] = new
plugin.write_text(json.dumps(data, indent=2) + "\n")

print(f"Version is now {new}. Next:\n"
      f"  git commit -am 'exit-arc {new}' && git tag -a v{new} -m 'What changed...' && git push --follow-tags")
