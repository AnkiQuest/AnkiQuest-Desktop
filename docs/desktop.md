# Desktop compatibility and packages

AnkiQuest supports Anki 24.11 and newer with Qt 6. CI pins the oldest supported
release (24.11, Python 3.9) and the current release (26.09.4, Python 3.12).
The manifest keeps `min_point_version: 241100`; there is no known incompatible
newer release that needs a maximum version.

## Run the checks

Use a separate virtual environment for each Anki version:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r tests/requirements-anki-26.9.4.txt
python -m pyflakes addon
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
cargo run --manifest-path tools/package-addon/Cargo.toml -- --output ankiquest.ankiaddon
```

On Windows, activate `.venv\Scripts\Activate.ps1` and set
`$env:QT_QPA_PLATFORM = "offscreen"` before running the tests. For the oldest
version, create another environment with `tests/requirements-anki-24.11.txt`.
The current `aqt[qt]` extra pins its matching Qt, WebEngine and SIP packages;
the older requirements explicitly pin those packages. Do not install an
unbounded PyQt/WebEngine combination on top of these environments.

The two **Desktop (Anki …)** jobs use Rust only to build the archive the
smoke installs (`tools/package-addon`, as releases do). Each checks:

- Every add-on unit test, including real Qt dialogs in separate processes.
- The whole packaged add-on, installed through Anki's real `AddonManager` into
  a temporary profile with a real collection, task manager, progress manager,
  menus and main window. The smoke checks the add-on's `gui_hooks` and direct
  `mw` attribute paths, renders the deck-list entry and calls the scheduler,
  timebox and timer APIs. It does not start Chromium or claim to test a full
  interactive Anki session.
- Recorded server responses in `test_desktop_contract.py`, plus the activity,
  board and social fixture tests. These exercise profile/upload day verdicts,
  rank/share words, every board shape, notifications, activity, goals, decks,
  capabilities and conquered-card actions. `wins.json` cross-checks the win
  IDs used by notification shares and card-image URLs; desktop does not list
  `/api/wins` itself. The recordings come from AnkiQuest-Server master (see
  [Server data](#server-data)), where the server regenerates and verifies
  them.
- Upload/reconcile/refresh regressions in `test_deck_completion.py` and
  `test_addon_uploads.py`; feedback, conquest paths and web navigation in
  `test_desktop_board.py`; clipboard text in `test_addon_sharing.py` and
  `qt_moments.py`.

The **Add-on archive** job publishes `ankiquest-addon` as a downloadable PR
artifact. PR and release builds use the same packager, `tools/package-addon`;
`--ankiweb` builds the AnkiWeb upload. Archives omit local
`meta.json`, caches, tests and hidden files, and include `version.json`,
`build.json` and a manifest `human_version`. The latter is verified through Anki's installed
metadata, and Settings shows the same version. A source checkout says
**Local copy**. Stable releases still require an owner-created `addon-N` tag;
a PR artifact does not publish a stable release.

When Anki releases a new version, update the current requirements file and CI
matrix together, keeping the oldest job until its support is deliberately
changed. Verify the release's own Qt extra, both full test jobs and a normal
interactive study session before claiming support. Add an upper version
bound only for a reproduced incompatibility.

## Server data

The add-on tests run against AnkiQuest-Server `master`. They read:

- `tests/fixtures/*.json`: Server's `tests/fixtures/`, the rules both
  clients test against.
- `tests/api-examples/*.json`: Server's `docs/api/examples/`.

Neither is committed. The packager copies them from a shallow, sparse
clone of `master`, and the **Desktop** jobs do so before the tests:

```sh
cargo run --manifest-path tools/package-addon/Cargo.toml -- server-data
```

To test a server change before it reaches `master`, copy from its
checkout instead:

```sh
cargo run --manifest-path tools/package-addon/Cargo.toml -- server-data --from ../AnkiQuest-Server
```

Never add a fixture or example here: change Server first. A server change
that breaks these tests is fixed in the same change, or the add-on is
updated right after.

## Companion pictures

The add-on's pictures (`addon/art/<name>.png` and the faces
`addon/<companion>_face.png`) and Anki-tan's licence for hers
(`addon/art/LICENSE-Anki-tan.md`) are not committed. They come from the
`addon-art.zip` asset of the [AnkiQuest-Art](https://github.com/AnkiQuest/AnkiQuest-Art)
release that `ankiquest-art.json` pins, with its SHA-256. AnkiQuest-Sync
updates the pin when Art publishes a release; don't edit it by hand.

The packager unpacks the pictures and the licence into `addon/` before
every build, replacing those of an earlier run, and fails if the licence
is missing. To run the add-on or its tests from a
checkout, fetch them once, and again after the pin changes:

```sh
cargo run --locked --manifest-path tools/package-addon/Cargo.toml -- art
```

The asset is downloaded with `curl` into `ANKIQUEST_ART_CACHE`, by default
`ankiquest-art` in the user's cache folder, under its SHA-256, so later
builds work offline. Every use checks the hash against the pin. To try a
release that is not published yet, set `ANKIQUEST_ART_DIR` to a folder
holding its assets (from AnkiQuest-Art's `tools/release/build.sh`); they
are checked against the pin the same way.

Where a companion has no master for a pose, the add-on shows the fallback
the pinned AnkiQuest-Art release's `poses.json` (copied beside the code by
`-- art`) names; a core pose not drawn yet shows the core pose its
`core_fallbacks` name, read by `addon/moods.py`.

## API audit

Checked against the installed 24.11 and 26.09.4 APIs:

| API | Finding |
| --- | --- |
| `QNetworkCookie` | Neither `aqt.qt` exports it. Keep the direct `PyQt6.QtNetwork` import; Qt 6 is already required. The Qt import test checks it on both versions. |
| `mw.progress.timer` | Both accept `repeat` and `parent`. The smoke calls that signature; the old `TypeError` fallbacks are removed. |
| `mw.col.startTimebox()` | Both expose this collection API; the smoke calls it on a real collection. |
| `col.get_config("rollover", 4)` | Both map this legacy key to scheduling preferences. The smoke sets a non-default rollover of 7 through `set_preferences()` and reads 7 through this call. |
| `gui_hooks` / `mw` | The smoke checks names collected from the add-on source against real objects. Timers and collection behavior have additional regression coverage. |

## Update ownership and AnkiWeb

The packager writes the update source into the archive's `build.json`:
`--updates github` for the GitHub release and nightly archives, `none` for
`--ankiweb` (AnkiWeb updates add-ons itself) and for every build that does not
ask (`--ankiweb --updates github` is refused). The add-on reads it once into
`updates.UpdateSource`. With `none` there is no daily check, no **Check for
updates** entry, no channel picker and no download or install; Settings shows
**Updates: none**. A missing or unknown `build.json`, as in a source copy, is
`none`. Anki identifies AnkiWeb installations by their numeric add-on
directory; those are `none` whatever `build.json` says.

GitHub builds show **Updates: github** and keep the stable/nightly choice and
daily checks. The live [AnkiWeb listing](https://ankiweb.net/shared/info/414948448)
uses code **414948448**. CI publishes an `ankiquest-ankiweb-addon` artifact
with that numeric package ID and a conflict with the GitHub `ankiquest`
package; the GitHub artifact declares the reverse conflict. Repeat updates
never declare their own package as a conflict.

GitHub builds are published under names that carry their minimum Anki
(`updates.BUILDS`). A copy reads the names for the newest minimum its Anki
meets and falls back to older ones, so raising the minimum publishes the new
builds under new names only and leaves the old names on the last build for the
old minimum. The 24.11 builds are `ankiquest-24.11.ankiaddon` and
`addon-nightly-24.11.json`; `ankiquest.ankiaddon` and `addon-nightly.json`
are the 23.10 builds. This matters because Anki's installer replaces an
add-on's files before it reports the archive incompatible; copies since #400
also check the manifest first.

Anki preserves a disabled installation when updating it. Remove the other
copy before switching channels, restart, and sign in with the same account
and server. Account upload checkpoints live in the Anki profile, so they
survive the installation-directory change. Keep a collection backup.
See the [listing update procedure](ankiweb-listing.md#updating-the-listing).

References: [Anki add-on sharing](https://docs.ankiweb.net/addons/sharing.html),
[Anki 26.09.4](https://github.com/ankitects/anki/releases/tag/26.09.4),
[aqt package metadata](https://pypi.org/project/aqt/26.9.4/).

## Language and shared wording

Desktop follows Anki's selected language, including Qt's localized short
date and time formats for inbox messages, last upload, reminder-hour
pickers and closing-week clocks. Timestamps still use the computer's local time zone. Integer
counts share a private plural helper: French uses the singular for zero
and one; English, Spanish, German and European Portuguese use it for one.
These are the [CLDR integer rules](https://unicode.org/cldr/charts/50/supplemental/language_plural_rules.html).

The Portuguese table uses European Portuguese (`Guardar`, `Partilhar`,
`tu`), matching the server and Android settings/sharing wording. Anki's
Brazilian Portuguese selection continues to use this table; date and time
formats follow its selected region. A separate Brazilian catalog would
need a complete translation, not isolated switches to `Salvar`.

`tests/fixtures/desktop-wording.json` records reviewed Android strings for
the same settings groups, moments and sharing screens, with the source
commit. The translation test checks these across all four languages.
After reviewing Android changes, update the fixture in AnkiQuest-Server
and the desktop wording together (see [Server data](#server-data)); CI
does not fetch a moving Android branch. Positional Android
placeholders are normalized to Python placeholders. Identical English
labels in different contexts (such as a noun versus a reply button) are
not automatically copied.

One generated catalog was considered. Keep the per-feature Python tables
for now: Android resource keys/plurals, server message contexts and the
add-on's English keys are not interchangeable. A JSON runtime catalog
alone would still duplicate the other two. The small shared-wording
fixture makes deliberate alignment reviewable without changing package
loading or replacing every translation key.

## Background request ownership

Every callback must still own its starting profile and account before it
changes UI or saved state. A newer request owns its own slot, so an old
completion cannot clear it. Profile close and sign-out invalidate pending
work; collection work keeps the original collection instead of reading a
new `mw.col` when its queued worker starts.

Home shares its private request owner across goal, capability and address
requests. Copies shares one owner across polling, sending and offer actions,
with a dialog lifetime for imports and dismissals. Preview owns both its
collection and its cache. Inbox additionally owns a filter/row revision.
Keep these private implementations separate: one cross-module helper would
need optional dialog, cache, query and row-revision rules and would hide the
different lifetimes it is meant to protect.

Regressions in `test_home_request_ownership.py`, `qt_copies.py`,
`test_addon_preview_lifecycle.py` and `qt_activity.py` delay replies through
account/profile changes, overlapping requests and closed/deleted windows.
Cancelled downloads remove their temporary package and never open an
importer in a different profile.
