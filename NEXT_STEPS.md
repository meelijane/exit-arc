# Next steps (not built yet)

## Distribution

- **Homebrew core**: the formula lives in the meelijane/homebrew-tap tap; homebrew-core needs a
  notable project first.
- **pipx / PyPI**: `pyproject.toml` already defines the `exit-arc` command, so
  `pipx install exit-arc` works once it's published to PyPI.
- **Tiny macOS app**: one window (SwiftUI, or Tauri) that shows the dry-run
  summary and the capability table, has a browser picker and checkboxes for
  each step, and runs the bundled `.pyz` with `--yes --quit-browser` after its
  own confirmation dialog. Needs signing and notarisation. Full Disk Access
  isn't needed, since everything it touches is in the user's own Library.

## Features

- Create the target profile automatically when the browser has never been opened.
- Firefox: a merge mode for `--import` that folds existing bookmarks into the
  import file, so a profile with bookmarks can be done automatically without
  losing them (tags and keywords would still be lost, which is why it isn't
  the default).
- Chrome: confirm automatic bookmark import against a real Chrome re-save (the
  checksum follows Chromium's algorithm but hasn't been seen round-tripped yet),
  then drop the "experimental" label.
- Zen: carry over Arc space colours as Zen space themes.
- Windows: Arc for Windows keeps `StorableSidebar.json` under
  `%LOCALAPPDATA%\Packages\TheBrowserCompany.Arc_*\LocalCache\Local\Arc`. Parsing
  already works with `--arc-dir`; profile discovery, locks and quitting need
  Windows versions.
- More targets: Safari (HTML import only), Vivaldi/Brave/Edge (same as Chrome).
