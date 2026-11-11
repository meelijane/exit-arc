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
| **Bookmarks**: favourites + a folder per space | yes, on the toolbar (replaces existing bookmarks; asks first) | yes, same as Firefox | experimental: added to the bookmarks bar, yours kept | HTML, CSV, Markdown, JSON |
| **Spaces** | no: you get a toolbar folder per space | **yes**: real Zen spaces with your pinned tabs and folders | no: Chrome has no spaces | listed in every format |
| **Favourites** | real pinned tabs | **Zen Essentials** | no (Chrome's session files are undocumented) | listed in every format |
| **Vertical tabs** | yes | built in | experimental | - |
| **New tab cleanup** | yes | yes | no | - |
| **Extensions** | finds official add-ons; you approve each | same as Firefox | opens each Web Store page; you click Add | listed in Markdown and JSON |
| **Default browser** | yes (macOS asks you to confirm) | yes | yes | - |
| History, passwords, cookies, extension data | no | no | no | no |

Not moved: history, passwords, cookies/logins, extension data and settings,
Boosts, Easels, Notes, Little Arc and site permissions. Notes and easels have
no URL, so the summary counts them as "skipped". For history and passwords, use
the browser's own importer or a password manager.

## Requirements

- macOS with Arc's data still on disk (`~/Library/Application Support/Arc`)
- Python 3.8 or newer. Macs with Homebrew already have it (`python3 --version`); otherwise
  macOS offers to install it the first time you run `python3`.
- The target browser, if you're moving into one. Open it once and quit it
  before using exit-arc, so it has a profile.

## How to use it

Install it with [Homebrew](https://brew.sh):

```bash
brew install meelijane/tap/exit-arc
```

Then run it:

```bash
exit-arc
```

Without Homebrew: download `exit-arc.pyz` from the
[latest release](https://github.com/meelijane/exit-arc/releases/latest) and run `python3 exit-arc.pyz`.

It asks a few questions, then does the rest:

1. **Which Arc profile?** Only asked if you have more than one. The default is all of them.
2. It shows what it found: your Favourites, and each space with its pinned tabs and folders.
3. **Where are you moving to?** Firefox, Zen, Chrome, or no browser (just save the files).
4. **What should it set up there?** It lists only what that browser supports. Press Enter for all
   of them, or type the numbers you want.
   This includes making it your **default browser** (macOS asks you to confirm), unless it already is.
5. If the browser has more than one profile: **which profile?** Each one is listed with its folder and
   how many bookmarks it has. The default is the one the browser opens.
6. If that profile already has bookmarks of yours: **keep them or replace them?** Adding bookmarks
   automatically replaces all of them, so the default is to keep yours and import the bookmarks
   file yourself (it shows you how).
7. **Remove Arc when it's done?** The default is no. See [Removing Arc](#removing-arc).
8. **Where should the files go?** The default is `~/Desktop/arc-export`.
9. **Go ahead?** If the browser is open, it then asks before quitting it.

Nothing changes until you say yes at the end. Everything it changes in the browser is backed up first,
into `backup-<browser>-<time>/` in the same folder as the files.

### The files

Whichever browser you pick, it always saves these:

| File | What's in it |
| --- | --- |
| `arc-sidebar.md` | A readable page: a heading per space, nested folders, Favourites, and a table of your extensions and where they're available |
| `arc-tabs.csv` | One row per tab: `profile, space, folder_path, title, url, kind` (`kind` is favourite / pinned / unpinned) |
| `arc-bookmarks.html` | A standard bookmarks file that any browser can import |
| `arc-export.json` | Everything, for other tools |

## What happens in each browser

### Firefox

- **Bookmarks**: Favourites become toolbar links, and each space becomes a toolbar folder.
- **Favourites**: also become real pinned tabs. Firefox only restores pinned tabs when it restores your
  last session, so this also turns on *Settings > General > Open previous windows and tabs*. Your tabs
  then stay open between restarts, like in Arc.
- **Vertical tabs**: tabs in a sidebar on the left. You can turn this off later in Firefox's settings.
- **New tab page**: removes sponsored shortcuts, the default sites (AliExpress, Temu, Wikipedia, …),
  stories and widgets. The setting names are checked against your Firefox version first. Tested on
  Firefox 159.
- **Extensions**: see [Extensions](#extensions).

> [!WARNING]
> **Adding bookmarks automatically replaces every bookmark in the Firefox (or Zen) profile.** If the
> profile has bookmarks of your own, exit-arc asks first and keeps them unless you choose to replace them
> (they're backed up first, including a `bookmarks.html` you can re-import). To import by hand and keep
> yours: *Bookmarks > Manage Bookmarks > Import and Backup > Import Bookmarks from HTML…* and choose
> `arc-bookmarks.html`.

How the bookmark import works: exit-arc writes a temporary `user.js` that tells Firefox to load the
bookmarks file at startup (`browser.places.importBookmarksHTML` and `browser.bookmarks.file`). It then
starts Firefox once, headless (no window), checks the result in `places.sqlite`, and quits Firefox. Last,
it removes the temporary files and prefs and puts back your saved session and any `user.js` you already had.

### Zen

On Zen your Arc layout comes over as Zen's own features:

- **Spaces**: each Arc space becomes a **Zen space**, with its emoji, pinned tabs and nested folders. Your
  own Zen spaces are kept. A space with the same name is reused, and links already pinned there are
  skipped, so running it again doesn't add duplicates. A brand-new Zen profile's empty default "Space"
  is replaced.
- **Favourites**: become **Essentials**.
- **Bookmarks** and **New tab page** work as on Firefox. Vertical tabs are built in.

Zen keeps this in `zen-sessions.jsonlz4`, a file Zen doesn't document. exit-arc writes it in the format
Zen 1.24 uses: Zen loaded the spaces, Essentials, pinned tabs and folders written this way, and saved them
back unchanged. A future Zen version may change the format. If spaces don't appear, restore the
`zen-sessions.jsonlz4` backup and use Bookmarks instead.

### Chrome

- **Bookmarks** (**experimental**): adds your Favourites and a folder per space to the end of Chrome's
  bookmarks bar, and keeps the bookmarks you already have. Running it again replaces only the folders
  exit-arc added. If you use Chrome sync, they'll sync to your other devices. If they don't appear, use
  *Bookmarks and Lists > Import Bookmarks and Settings > Bookmarks HTML File* with `arc-bookmarks.html`.
- **Extensions**: opens each extension's Chrome Web Store page. Arc uses the same extension IDs as
  Chrome, so these are the exact same extensions.
- **Vertical tabs** (**experimental**): turns on Chrome's vertical tabs setting (`vertical_tabs.enabled`
  in the profile's `Preferences`, backed up first). On Chrome 157 the setting stays on after a restart. If Chrome still shows tabs
  along the top, turn vertical tabs on in Chrome itself.
- No spaces, pinned tabs or new tab cleanup: Chrome either doesn't have them or doesn't let other
  programs set them.

### Extensions

exit-arc lists the extensions installed in Arc and, for each one, whether the browser you picked has it:

- **Chrome**: always the same extension (same ID).
- **Firefox and Zen**: a few well-known extensions are matched from a list checked by hand. For the rest,
  exit-arc searches [addons.mozilla.org](https://addons.mozilla.org) and only accepts a result when it's
  by the same developer (same author or website). Close matches by someone else are shown as "maybe" and
  never installed. **Only extension names are sent**, and only if you choose Extensions.

It then asks before opening the install prompts. You approve each extension in the browser itself, and
nothing is installed silently. Extension data such as password vaults and settings doesn't carry over,
so sign in again in each one. Pre-installed extensions (like Google Docs Offline) and Arc's own
built-ins are left out.

### Default browser

macOS doesn't let programs change your default browser silently: it shows its own "Do you want to
change your default web browser?" box, and nothing changes unless you choose the new browser there.
You can also change it later in *System Settings > Desktop & Dock > Default web browser*.

### Removing Arc

If you choose to, exit-arc removes Arc after everything else has worked:

- **The app only**: moves `Arc.app` to the Trash. Arc's data (history, passwords, cookies, your
  sidebar) stays on your Mac, so you can reinstall Arc or run exit-arc again later.
- **The app and its data**: also moves Arc's data folder, caches and settings to the Trash. Arc's
  history, passwords and cookies are **not** moved to your new browser, so export them from Arc first
  if you want them.

Everything goes to the Trash, so you can put it back until you empty it. exit-arc quits Arc first
(asking before it does), and it always asks once more before moving anything, even with `--yes`.
If Arc syncs with an Arc account, your account and its synced data stay online.

## Use it with Claude

This repo is also a Claude Code plugin with an `exit-arc` skill. With it, you can ask Claude to "help
me move off Arc": Claude installs exit-arc if needed, shows you what's in Arc, asks which browser and
steps you want, and runs it. It leaves removing Arc to you.

```
/plugin marketplace add meelijane/exit-arc
/plugin install exit-arc@exit-arc
```

The skill itself is [`skills/exit-arc/SKILL.md`](skills/exit-arc/SKILL.md).

## Running it without questions

For scripts, every answer can be given as an option instead. With any option, exit-arc asks nothing
except before quitting a browser and before opening extension installs (`--yes` skips the second).

```bash
exit-arc --dry-run                                # show what it finds, change nothing
exit-arc -o ~/Desktop/arc-export                  # just save the files
exit-arc -o ~/Desktop/arc-export --to zen --all   # everything Zen supports
```

```
-n, --dry-run            show what would happen; write and change nothing
-o, --out DIR            output folder (default: current folder)
--format LIST            csv,md,json,html (default: all four)
--layout toolbar|folder  bookmarks layout (default: toolbar)
--include-unpinned       also bookmark open, unpinned tabs
--arc-dir DIR            Arc data folder (default: ~/Library/Application Support/Arc)
--arc-profile NAME       only this Arc profile (repeatable)
--capabilities           print what each browser supports (the table above)

--to firefox|zen|chrome  target browser (default: firefox)
--import                 bookmarks: favourites + a folder per space
--spaces                 Zen: real spaces with pinned tabs and folders
--pin-favourites         pinned tabs (Firefox) / Essentials (Zen)
--vertical-tabs          vertical tabs (Firefox; Chrome experimental)
--clean-newtab           Firefox/Zen: no sponsored shortcuts or widgets
--extensions             look up extensions and offer to install them
--default-browser        make the target your default browser (macOS asks you to confirm)
--all                    every step the target supports
--remove-arc app|all     afterwards, move Arc (app, or app + data) to the Trash; always asks
--browser-profile NAME   profile to change, by name or folder (default: the browser's default)
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
- **Several profiles**: exit-arc asks which one to set up. Without the questions, it uses the one the
  browser opens; choose another with `--browser-profile NAME` (or its folder). Firefox lists its
  profiles at `about:profiles`.
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

### Releasing

```bash
python3 scripts/bump_version.py 0.4.3
git commit -am "exit-arc 0.4.3"
git tag -a v0.4.3 -m "What changed, for the release notes"
git push --follow-tags
```

Pushing the tag runs `.github/workflows/release.yml`: it checks the tag matches the version, runs the
tests, builds `exit-arc.pyz` and publishes the GitHub release with the tag's message as the notes.
The Homebrew cask in [meelijane/homebrew-tap](https://github.com/meelijane/homebrew-tap) checks for
new releases every six hours and updates itself.

## License

[MIT](LICENSE)
