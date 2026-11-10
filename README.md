# arc-to-firefox

Move your [Arc](https://arc.net) sidebar into Firefox: every space, its pinned
tabs and folders, and your Favourites become Firefox bookmarks, laid out on the
Bookmarks Toolbar so they're one click away like they were in Arc.

It's a single Python file with no dependencies. It runs locally, reads Arc's
files without changing them, and sends nothing anywhere.

> Not affiliated with The Browser Company or Mozilla.

## What gets moved

| From Arc | In Firefox |
| --- | --- |
| Favourites (the icons at the top of the sidebar) | Links on the Bookmarks Toolbar |
| Each space (name + emoji, e.g. `🏠 Home`) | A toolbar folder |
| Pinned tabs, including nested folders | Bookmarks inside that folder, same order and nesting |
| Tabs in a split view | Plain bookmarks, one after another |
| Renamed tabs | Keep your name; otherwise the page title, then the URL |
| Multiple Arc profiles | One toolbar folder per profile |
| Open (unpinned) tabs | Only with `--include-unpinned` (always listed in `arc-export.json`) |

**Not moved:** history, passwords, cookies/logins, extensions, Boosts, Easels,
Notes, Little Arc windows, or site permissions. Arc notes and easels have no
URL, so they're counted as "skipped" in the summary. For history and passwords,
use Firefox's own importer (*File > Import From Another Browser*) or a password
manager.

## Requirements

- macOS with Arc's data still on disk (`~/Library/Application Support/Arc`)
- Python 3.8 or newer (`python3 --version`; macOS offers to install it with the
  Command Line Tools if it's missing)
- Firefox, only if you use the automatic import

## Quick start

Download [`arc_to_firefox.py`](arc_to_firefox.py), then see what it finds
(nothing is written):

```bash
python3 arc_to_firefox.py --dry-run
```

```
Favourites: 8 links
🏠 Home: 38 pinned links, 1 folder, 2 open unpinned (not exported)
💼 Projects: 26 pinned links, 2 folders, 0 open unpinned
Total links to bookmark: 72
```

Write the files:

```bash
python3 arc_to_firefox.py -o ~/Desktop/arc-export
```

This creates two files:

- `arc-export.json`: everything it found, for safekeeping or other tools
- `arc-bookmarks.html`: a standard bookmarks file any browser can import

Then pick **one** way to get them into Firefox.

### Option A: import by hand (safe, keeps your bookmarks)

In Firefox: **Bookmarks > Manage Bookmarks** (Shift+Cmd+O) **> Import and
Backup > Import Bookmarks from HTML…** and choose `arc-bookmarks.html`. Your
existing bookmarks stay; the Arc ones are added.

Firefox only puts imported links straight onto the toolbar during a full
replace (Option B). With a manual import they arrive in a folder called
"Bookmarks Toolbar" inside the Bookmarks Menu, which you can drag onto the
toolbar. If you're going this way, `--layout folder` gives a tidier result: one
"Arc" folder holding everything.

### Option B: automatic import (best for a fresh Firefox)

```bash
python3 arc_to_firefox.py -o ~/Desktop/arc-export --import
```

> [!WARNING]
> The automatic import **replaces every bookmark** in the Firefox profile.
> It's meant for a Firefox you've just installed. If the profile already has
> bookmarks of yours, the tool stops and tells you to use Option A, unless you
> add `--replace-existing`. In that case it first saves a backup (a copy of
> `places.sqlite` plus a `bookmarks.html` you can re-import) next to the export.

What it does:

1. Finds the profile Firefox opens by default (from `profiles.ini`).
2. Refuses to run while Firefox is open. Quit it first (Cmd+Q).
3. Writes a temporary `user.js` into the profile that tells Firefox to load
   the bookmarks file on its next start, and to always show the Bookmarks
   Toolbar (skip that with `--no-show-toolbar`). An existing `user.js` is kept
   and restored afterwards.
4. Starts Firefox once, headless (no window), and waits until the bookmarks
   show up in `places.sqlite`.
5. Quits Firefox, removes the temporary `user.js` lines, its copy of the HTML
   file and the one-off prefs, then reports how many links made it.

Open Firefox afterwards and your spaces are on the toolbar.

## Options

```
--dry-run, -n           show counts and what would happen; write nothing
-o, --out DIR           where to write the files (default: current folder)
--layout toolbar|folder toolbar (default): favourites + a folder per space on
                        the Bookmarks Toolbar. folder: everything inside one
                        "Arc" folder in the Bookmarks Menu
--include-unpinned      also bookmark open, unpinned tabs ("Open tabs" subfolder)
--arc-profile NAME      only export this Arc profile (name or folder); repeatable
--arc-dir DIR           read Arc data from somewhere else (e.g. a backup)

--import                load into Firefox automatically (see the warning above)
--firefox-profile DIR   use this Firefox profile instead of the default one
--firefox-bin PATH      path to the firefox executable
--replace-existing      allow replacing a profile that already has bookmarks
--no-backup             don't back up existing Firefox bookmarks first
--no-show-toolbar       leave the toolbar visibility setting alone
-y, --yes               don't ask "Continue?"
--timeout SECONDS       how long to wait for Firefox (default 90)
```

## How it works

Arc keeps its sidebar in `StorableSidebar.json`. The live sidebar is the first
entry in `sidebar.containers` that has `spaces` and `items`. Arc stores maps as
flat lists that alternate key and value (`[id, {...}, id, {...}]`):

- Each **space** has a `title`, an emoji in `customInfo.iconType`, a `profile`
  (`{"default": true}` or a custom profile's `directoryBasename`), and
  `containerIDs` pairing `pinned`/`unpinned` with an item ID.
- Each **item** is a tab (`data.tab.savedURL` / `savedTitle`, with `title` set
  when you renamed it), a folder (`data.list` + `childrenIds`), a split view, or
  something without a URL (notes, easels).
- `topAppsContainerIDs` pairs each profile with its **Favourites** container.
- Profile names come from `User Data/Local State` (`profile.info_cache`). Arc's
  internal `__ARC_SYSTEM_PROFILE` is ignored.

The automatic import uses two standard Firefox prefs,
`browser.places.importBookmarksHTML` and `browser.bookmarks.file`, which make
Firefox load an HTML bookmarks file at startup, replacing what's there.

## Troubleshooting

- **"Arc data not found"**: Arc's folder is missing or somewhere else. Point
  at it with `--arc-dir`.
- **"Firefox is running"**: quit it with Cmd+Q (closing the window isn't
  enough on macOS), then run again.
- **"No Firefox profile found"**: open Firefox once, quit it, then run again.
- **Some links missing after import**: the tool lists them. Firefox can reject
  unusual URLs (Arc-internal `arc://` pages, for example). Everything is still
  in `arc-bookmarks.html` for Option A.
- **Several Firefox installs** (e.g. Developer Edition): it uses the first one
  in `profiles.ini` and says so. Choose with `--firefox-profile`, which you can
  find in Firefox at `about:profiles`.

## Development

```bash
python3 -m unittest discover -s tests
```

The tests use synthetic data in `tests/fixtures/arc` and a fake Firefox
(`tests/fake_firefox.py`) that mimics the startup import, so they never touch
a real Arc or Firefox profile.

## License

[MIT](LICENSE)
