#!/usr/bin/env python3
"""Build dist/exit-arc.pyz: the whole tool as one file people can download and run
with `python3 exit-arc.pyz`."""
import shutil
import tempfile
import zipapp
from pathlib import Path

root = Path(__file__).resolve().parent.parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    shutil.copytree(root / "exit_arc", Path(tmp) / "exit_arc", ignore=shutil.ignore_patterns("__pycache__"))
    target = dist / "exit-arc.pyz"
    zipapp.create_archive(tmp, target, interpreter="/usr/bin/env python3", main="exit_arc.cli:main")
print(f"Built {target}")
