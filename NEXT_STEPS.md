# Next steps (not built yet)

Ideas for making this easier for people who don't use a terminal.

## Packaging

- **Homebrew formula** (`brew install arc-to-firefox`): the script is
  stdlib-only, so a formula just installs the file and a `python@3` dependency.
  Start with a personal tap (`homebrew-tap` repo) before submitting to core.
- **pipx / PyPI**: `pyproject.toml` already defines the `arc-to-firefox`
  command, so `pipx install arc-to-firefox` works once it's published.
- **Tiny macOS app**: a one-window SwiftUI app (or Tauri) that shows the
  dry-run summary, lets you pick toolbar/folder layout, and has two buttons:
  "Save bookmarks file" and "Import into Firefox". It can bundle the script and
  call it with `--yes`, or port the ~300 lines of logic to Swift. Needs code
  signing + notarisation to avoid Gatekeeper warnings, and Full Disk Access is
  *not* required (both folders are in the user's Library).

## Features

- Create a Firefox profile automatically when Firefox has never been opened
  (currently it asks you to open and quit Firefox once).
- A merge mode for `--import` that folds existing bookmarks into the import
  file, so a profile with bookmarks can be done automatically without losing
  them (tags and keywords would still be lost, which is why it's not default).
- Windows support: Arc for Windows keeps `StorableSidebar.json` under
  `%LOCALAPPDATA%\Packages\TheBrowserCompany.Arc_*\LocalCache\Local\Arc`.
  `--arc-dir` may already work there; the Firefox launch/lock code needs a test.
- Other targets (Zen, Chrome, Safari) are mostly a different "import" step;
  the HTML file already works with all of them.
