---
name: exit-arc
description: Move someone off the Arc browser on macOS. Exports their Arc spaces, pinned tabs, folders, Favourites and extension list, and sets them up in Firefox, Zen or Chrome (bookmarks, Zen spaces and Essentials, pinned tabs, vertical tabs, new tab cleanup, extension installs, default browser), using the open-source `exit-arc` command. Use when someone wants to leave Arc, switch from Arc to Firefox/Zen/Chrome, or export or back up their Arc sidebar.
---

# Moving someone off Arc with exit-arc

`exit-arc` (https://github.com/meelijane/exit-arc) reads Arc's sidebar from
`~/Library/Application Support/Arc` and either saves it as files or sets it up in another
browser. It is macOS only. It never moves history, passwords, cookies or extension data.

Run it with options, as below. With no options it asks questions on the terminal, which you
can't answer from a tool call.

## 1. Make sure it's installed

```bash
exit-arc --version || brew install meelijane/tap/exit-arc
```

Without Homebrew, download `exit-arc.pyz` from
https://github.com/meelijane/exit-arc/releases/latest and run it with
`python3 exit-arc.pyz` instead of `exit-arc`.

## 2. Show them what's in Arc (changes nothing)

```bash
exit-arc --dry-run
```

This prints each Arc profile's Favourites and spaces with link and folder counts, plus the
number of extensions. Show them that summary. If they have several Arc profiles, ask whether
they want all of them or one (`--arc-profile NAME`).

## 3. Ask where they're going and what they want

Ask which browser: Firefox, Zen, Chrome, or none (just the files). `exit-arc --capabilities`
prints what each browser supports. Then ask which of these steps they want, offering only the
ones the browser supports:

| Step | Option | Firefox | Zen | Chrome |
| --- | --- | --- | --- | --- |
| Bookmarks: Favourites + a folder per space | `--import` | yes | yes | experimental |
| Spaces as real Zen spaces, with pinned tabs and folders | `--spaces` | - | yes | - |
| Favourites as pinned tabs (Firefox) or Essentials (Zen) | `--pin-favourites` | yes | yes | - |
| Vertical tabs | `--vertical-tabs` | yes | built in | experimental |
| No sponsored shortcuts or widgets on new tabs | `--clean-newtab` | yes | yes | - |
| Find their extensions and open install pages | `--extensions` | yes | yes | yes |
| Make it the default browser | `--default-browser` | yes | yes | yes |

Choose the steps one by one, not with `--all`, so you only do what they agreed to.

Before you run anything, tell them:

- **Firefox or Zen bookmarks replace every bookmark in that profile.** exit-arc refuses
  (exit code 3) if the profile already has bookmarks of their own. Add `--replace-existing`
  only if they agree to have them replaced; a backup is saved first. Otherwise leave out
  `--import` and give them `arc-bookmarks.html` to import by hand. exit-arc prints how.
- `--extensions` sends their extension **names** to addons.mozilla.org for Firefox and Zen. Ask
  first. Each install still needs their approval in the browser, and extension data (logins,
  settings) doesn't carry over.
- `--pin-favourites` on Firefox also turns on "Open previous windows and tabs".
- `--default-browser` makes macOS show its own "change default browser?" box. They have to
  choose the new browser there.

If the browser has several profiles, list them (Firefox shows them at `about:profiles`) and
pass the one they choose as `--browser-profile NAME`. By default exit-arc uses the profile the
browser opens.

## 4. The browser must be closed

exit-arc only changes a browser that isn't running. Ask them to quit it themselves (Cmd+Q). If
they'd rather exit-arc quit it, add `--quit-browser`, but only after they say yes: it quits the
browser right away, and tabs only come back if the browser restores its last session.

## 5. Run it

Use `--yes` so exit-arc doesn't stop at its own "Change this profile now?" question; the
person has already agreed to each step. For example, for Zen:

```bash
exit-arc -o ~/Desktop/arc-export --to zen --import --spaces --pin-favourites --clean-newtab --yes
```

Or, for just the files:

```bash
exit-arc -o ~/Desktop/arc-export
```

It always writes `arc-sidebar.md` (a readable page), `arc-tabs.csv`, `arc-bookmarks.html` and
`arc-export.json` to the output folder. Everything it changes in the browser is backed up first
into `backup-<browser>-<time>/` in that folder.

Exit codes: 0 done, 1 cancelled or error, 3 refused because of existing bookmarks, 4 some
bookmarks didn't make it (it lists them).

## 6. Afterwards

Tell them what changed, where the files and backups are, and that they can open the browser.
To undo anything, they quit the browser and copy the backed-up files back into the profile.

## Things you don't do for them

- **Don't remove Arc.** `--remove-arc` moves Arc (and optionally all its data) to the Trash, and
  Arc's history, passwords and cookies are not moved anywhere. If they want this, tell them to run
  `exit-arc` themselves in Terminal and choose it there. The option always asks for confirmation
  in their own terminal, so it can't be answered from here.
- Don't empty the Trash, delete backups or edit browser profiles by hand.
- Don't run it on a profile they didn't choose.
