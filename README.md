# exit-arc

Leaving [Arc](https://arc.net)? exit-arc takes your sidebar with you: every
space, its pinned tabs and folders, your Favourites and your list of
extensions. It can save them as plain files, or set them up in **Firefox**,
**Zen** or **Chrome**.

It's plain Python with no dependencies. It runs on your Mac, only reads Arc's
files, and sends nothing anywhere unless you ask it to look up extensions.

> Not affiliated with The Browser Company, Mozilla, Zen or Google.

## What each browser gets

| | Firefox | Zen | Chrome | Export only |
| --- | --- | --- | --- | --- |
| **Bookmarks** (`--import`): favourites + a folder per space | yes, on the toolbar (replaces existing bookmarks) | yes, same as Firefox | experimental: added to the bookmarks bar, yours kept | HTML, CSV, Markdown, JSON |
| **Spaces** (`--spaces`) | no: use `--import` (a toolbar folder per space) | **yes**: real Zen spaces with your pinned tabs and folders | no: Chrome has no spaces | listed in every format |
| **Favourites** (`--pin-favourites`) | real pinned tabs | **Zen Essentials** | no (Chrome's session files are undocumented) | listed in every format |
| **Vertical tabs** (`--vertical-tabs`) | yes | built in | no | - |
| **New tab cleanup** (`--clean-newtab`) | yes | yes | no | - |
| **Extensions** (`--extensions`) | finds official add-ons; you approve each | same as Firefox | opens each Web Store page; you click Add | listed in Markdown and JSON |
| History, passwords, cookies, extension data | no | no | no | no |

`exit-arc --capabilities` prints the same table.

Not moved: history, passwords, cookies/logins, extension data and settings,
Boosts, Easels, Notes, Little Arc and site permissions. Notes and easels have
no URL, so the summary counts them as "skipped". For history and passwords, use
the browser's own importer or a password manager.

## Requirements

- macOS with Arc's data still on disk (`~/Library/Application Support/Arc`)
- Python 3.8 or newer (`python3 --version`; macOS offers to install it if it's missing)
- The target browser, if you're moving into one. Open it once and quit it
  before using exit-arc, so it has a profile.

## Quick start

From a copy of this repo (a one-file download is planned), see what it finds
without writing anything:

```bash
python3 -m exit_arc --dry-run
```

```
Favourites: 8 links
🏠 Home: 38 pinned links, 1 folder, 2 open unpinned (not bookmarked)
💼 Projects: 26 pinned links, 2 folders, 0 open unpinned
Total links to bookmark: 72
Extensions: 6
```

Export everything to files (this works without any browser installed):

```bash
python3 -m exit_arc -o ~/Desktop/arc-export
```

| File | What's in it |
| --- | --- |
| `arc-sidebar.md` | A readable page: a heading per space, nested folders, Favourites, and a table of your extensions and where they're available |
| `arc-tabs.csv` | One row per tab: `profile, space, folder_path, title, url, kind` (`kind` is favourite / pinned / unpinned) |
| `arc-bookmarks.html` | A standard bookmarks file that any browser can import |
| `arc-export.json` | Everything, for other tools |

Pick formats with `--format csv,md` (default `csv,md,json,html`).

## Moving into a browser

Quit the browser first. If it's open, exit-arc asks before quitting it. Every
file it changes is backed up first into `backup-<browser>-<time>/` inside the
output folder.

### Firefox

```bash
python3 -m exit_arc -o ~/Desktop/arc-export --to firefox --all
```

`--all` runs every step the browser supports. You can also pick steps one by one:

- `--import`: Favourites become toolbar links, and each space becomes a toolbar folder.
- `--pin-favourites`: Favourites also become real pinned tabs. Firefox only
  restores pinned tabs when it restores your last session, so this also turns
  on *Settings > General > Open previous windows and tabs*. Your tabs then stay
  open between restarts, like in Arc.
- `--vertical-tabs`: tabs in a sidebar on the left. You can turn this off later in
  Firefox's settings. After a restart, `prefs.js` only keeps
  `sidebar.verticalTabs`, because Firefox drops values that match its defaults.
- `--clean-newtab`: removes sponsored shortcuts, the default sites (AliExpress,
  Temu, Wikipedia, …), stories and widgets. The setting names are checked
  against your Firefox version first. Tested on Firefox 159.
- `--extensions`: see [Extensions](#extensions).

> [!WARNING]
> **`--import` replaces every bookmark in the Firefox (or Zen) profile.** It's
> meant for a fresh browser. If the profile has bookmarks of your own, exit-arc
> stops before changing anything, unless you add `--replace-existing` (they're
> backed up first, including a `bookmarks.html` you can re-import). To keep
> your bookmarks, skip `--import` and import `arc-bookmarks.html` by hand:
> *Bookmarks > Manage Bookmarks > Import and Backup > Import Bookmarks from
> HTML…*. A manual import puts the toolbar items in a "Bookmarks Toolbar"
> folder in the menu, so `--layout folder` (one "Arc" folder) is tidier that way.

How the bookmark import works: exit-arc writes a temporary `user.js` that tells
Firefox to load the bookmarks file at startup (`browser.places.importBookmarksHTML`
and `browser.bookmarks.file`). It then starts Firefox once, headless (no
window), checks the result in `places.sqlite`, and quits Firefox. Last, it
removes the temporary files and prefs and puts back your saved session and any
`user.js` you already had.

### Zen

```bash
python3 -m exit_arc -o ~/Desktop/arc-export --to zen --all
```

On Zen your Arc layout comes over as Zen's own features:

- `--spaces`: each Arc space becomes a **Zen space**, with its emoji, pinned
  tabs and nested folders. Your own Zen spaces are kept. A space with the same
  name is reused, and links already pinned there are skipped, so running it
  again doesn't add duplicates. A brand-new Zen profile's empty default
  "Space" is replaced.
- `--pin-favourites`: Favourites become **Essentials**.
- `--import` and `--clean-newtab` work as on Firefox. Vertical tabs are built in.

Zen keeps this in `zen-sessions.jsonlz4`, a file Zen doesn't document. exit-arc
writes it in the format Zen 1.24 uses: Zen loaded the spaces, Essentials,
pinned tabs and folders written this way, and saved them back unchanged. A
future Zen version may change the format. If spaces don't appear, restore the
`zen-sessions.jsonlz4` backup and use `--import` instead.

### Chrome

```bash
python3 -m exit_arc -o ~/Desktop/arc-export --to chrome --import --extensions
```

- `--import` (**experimental**) adds your Favourites and a folder per space to
  the end of Chrome's bookmarks bar, and keeps the bookmarks you already have.
  Running it again replaces only the folders exit-arc added. If you use
  Chrome sync, they'll sync to your other devices. If they don't appear, use
  *Bookmarks and Lists > Import Bookmarks and Settings > Bookmarks HTML File*
  with `arc-bookmarks.html`.
- `--extensions` opens each extension's Chrome Web Store page. Arc uses the
  same extension IDs as Chrome, so these are the exact same extensions.
- No spaces, pinned tabs, vertical tabs or new tab cleanup: Chrome either
  doesn't have them or doesn't let other programs set them.

### Extensions

`--extensions` lists the extensions installed in Arc and, for each one,
whether the target browser has it:

- **Chrome**: always the same extension (same ID).
- **Firefox and Zen**: a few well-known extensions are matched from a list
  checked by hand. For the rest, exit-arc searches
  [addons.mozilla.org](https://addons.mozilla.org) and only accepts a result
  when it's by the same developer (same author or website). Close matches by
  someone else are shown as "maybe" and never installed. **Only extension
  names are sent**, and only when you use `--extensions`.

It then offers to open the install prompts. You approve each extension in the
browser itself, and nothing is installed silently. Extension data such as
password vaults and settings doesn't carry over, so sign in again in each one.
Pre-installed extensions (like Google Docs Offline) and Arc's own built-ins
are left out.

## All options

```
-n, --dry-run            show what would happen; write and change nothing
-o, --out DIR            output folder (default: current folder)
--format LIST            csv,md,json,html (default: all four)
--layout toolbar|folder  bookmarks layout (default: toolbar)
--include-unpinned       also bookmark open, unpinned tabs
--arc-dir DIR            Arc data folder (default: ~/Library/Application Support/Arc)
--arc-profile NAME       only this Arc profile (repeatable)
--capabilities           print what each browser supports

--to firefox|zen|chrome  target browser (default: firefox)
--import                 bookmarks: favourites + a folder per space
--spaces                 Zen: real spaces with pinned tabs and folders
--pin-favourites         pinned tabs (Firefox) / Essentials (Zen)
--vertical-tabs          Firefox: vertical tabs
--clean-newtab           Firefox/Zen: no sponsored shortcuts or widgets
--extensions             look up extensions and offer to install them
--all                    every step the target supports
--browser-profile DIR    profile to change (default: the browser's default)
--browser-bin PATH       browser executable
--replace-existing       let --import replace existing Firefox/Zen bookmarks
--no-backup              don't back up files before changing them
--no-show-toolbar        don't set the bookmarks toolbar to "always show"
--quit-browser           quit the browser without asking if it's open
-y, --yes                answer yes to questions (never to quitting the browser)
--timeout SECONDS        how long to wait for the browser (default 90)
```

Multiple Arc profiles are supported: each profile gets its own folder (or Zen
space names get the profile's name added). Use `--arc-profile` to pick one.

## Troubleshooting

- **"Arc data not found"**: point exit-arc at the folder with `--arc-dir`.
- **"… is running"**: quit the browser with Cmd+Q (closing the window isn't
  enough on macOS), or answer yes when exit-arc offers to quit it.
- **"No … profile found"**: open the browser once, quit it, and run exit-arc again.
- **Several Firefox installs** (e.g. Developer Edition): exit-arc uses the
  default one and says which. Choose another with `--browser-profile`; Firefox
  shows each profile's folder at `about:profiles`.
- **Something looks wrong**: everything exit-arc changed is in the
  `backup-<browser>-<time>/` folder. Quit the browser and copy the files back
  into the profile.

## Development

```bash
make test
```

That runs `python3 -m unittest discover -s tests`: tests for the Arc parser,
extension names, every export format, mozlz4, prefs.js editing, pinned-tab
insertion, Zen spaces, Chrome bookmarks and the whole CLI for each browser. They
use synthetic data in `tests/fixtures/arc`, a fake browser
(`tests/fake_firefox.py`), a fake OS layer and a fake addons.mozilla.org. They
never start or quit a real browser and never touch your real profiles. CI
runs them on macOS and Linux (`.github/workflows/test.yml`).

`make pyz` builds `dist/exit-arc.pyz`, the whole tool as one file you can run
with `python3 exit-arc.pyz`.

## License

[MIT](LICENSE)
