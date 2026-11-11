#!/usr/bin/env python3
"""Render the link-preview image and favicons with headless Chrome (no other tools needed).

    python3 site/og/build.py

Writes site/public/og.png (1200x630), apple-touch-icon.png (180x180) and favicon.ico (16/32/48).
"""
import struct
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / "public"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def shoot(html_path, out, width, height, transparent=False):
    with tempfile.TemporaryDirectory() as profile:
        cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
               f"--user-data-dir={profile}", "--force-device-scale-factor=1",
               f"--window-size={width},{height}", f"--screenshot={out}", "--virtual-time-budget=2000"]
        if transparent:
            cmd.append("--default-background-color=00000000")
        subprocess.run(cmd + [html_path.as_uri()], check=True, capture_output=True, timeout=60)


def icon_page(size):
    page = Path(tempfile.mkstemp(suffix=".html")[1])
    page.write_text(f'<html><body style="margin:0;background:transparent">'
                    f'<img src="{(PUBLIC / "favicon.svg").as_uri()}" width="{size}" height="{size}" '
                    f'style="display:block"></body></html>')
    return page


def ico(pngs):
    """An .ico file holding PNG images: [(size, png_bytes)]."""
    header = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    entries, data = b"", b""
    for size, png in pngs:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    return header + entries + data


shoot(HERE / "card.html", PUBLIC / "og.png", 1200, 630)
pngs = []
with tempfile.TemporaryDirectory() as tmp:
    for size in (180, 48, 32, 16):
        out = Path(tmp) / f"{size}.png"
        page = icon_page(size)
        shoot(page, out, size, size, transparent=True)
        page.unlink()
        if size == 180:
            (PUBLIC / "apple-touch-icon.png").write_bytes(out.read_bytes())
        else:
            pngs.append((size, out.read_bytes()))
(PUBLIC / "favicon.ico").write_bytes(ico(sorted(pngs)))
print("Wrote og.png, apple-touch-icon.png, favicon.ico")
