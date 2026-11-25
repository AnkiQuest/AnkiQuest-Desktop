> Anki is hard, free and effective.
>
> Duolingo is easy, commercial and ineffective.
>
> If you ask a random successful language learner what software to use they'll probably suggest Anki.
>
> —lsusr, [Invisible Choices, Made by Default](https://www.lesswrong.com/s/3xKXGh9RXaYTYZYgZ/p/k6nncsXAZD3bK6fe3)

<p align="center">
<img alt="" src="docs/graphics/banner_readme.png"/>
</p>

<a href="https://github.com/AnkiQuest/AnkiQuest-Desktop/releases/latest"><img src="https://img.shields.io/github/v/release/AnkiQuest/AnkiQuest-Desktop" alt="release"/></a>
<a href="https://ankiweb.net/shared/info/414948448"><img src="https://img.shields.io/badge/AnkiWeb-414948448-2a6db0" alt="AnkiWeb add-on"/></a>
<a href="https://github.com/AnkiQuest/AnkiQuest-Desktop/actions/workflows/ci.yml"><img src="https://github.com/AnkiQuest/AnkiQuest-Desktop/actions/workflows/ci.yml/badge.svg?branch=master" alt="CI"/></a>
<a href="https://github.com/AnkiQuest/AnkiQuest-Desktop/actions/workflows/addon.yml"><img src="https://github.com/AnkiQuest/AnkiQuest-Desktop/actions/workflows/addon.yml/badge.svg?branch=master" alt="Desktop add-on"/></a>
<a href="https://github.com/AnkiQuest/AnkiQuest-Desktop/commits/master"><img src="https://img.shields.io/github/commit-activity/m/AnkiQuest/AnkiQuest-Desktop" alt="commit-activity"/></a>
<a href="https://github.com/AnkiQuest/AnkiQuest-Desktop/graphs/contributors"><img src="https://img.shields.io/github/contributors/AnkiQuest/AnkiQuest-Desktop" alt="contributors"/></a>
<a href="https://github.com/AnkiQuest/AnkiQuest-Desktop/blob/master/LICENSE"><img src="https://img.shields.io/github/license/AnkiQuest/AnkiQuest-Desktop" alt="license"/></a>

# AnkiQuest-Desktop

The AnkiQuest add-on for Anki desktop.

AnkiQuest leaves Anki's scheduling unchanged and adds streaks, friends and leaderboards to keep you studying.

AnkiQuest adds XP, streaks, daily quests, friends and leaderboards to Anki. Clients send review history without card content; sharing a conquered card label or a deck copy is an explicit choice. AnkiQuest has three repositories:

- [AnkiQuest-Server](https://github.com/AnkiQuest/AnkiQuest-Server): the server and its website.
- [AnkiQuest-Desktop](https://github.com/AnkiQuest/AnkiQuest-Desktop): the Anki desktop add-on.
- [AnkiQuest-Android](https://github.com/AnkiQuest/AnkiQuest-Android): the Android app, a fork of AnkiDroid.

## Install

1. Create an account on an AnkiQuest server, such as [ankiquest.org](https://ankiquest.org). To run your own, see [AnkiQuest-Server](https://github.com/AnkiQuest/AnkiQuest-Server).
2. In Anki 23.10 or newer (Qt 6), open **Tools → Add-ons → Get Add-ons** and enter **414948448** ([AnkiWeb listing](https://ankiweb.net/shared/info/414948448)). Restart Anki, then choose **Tools → AnkiQuest → Settings → Account**. AnkiWeb manages updates. The [GitHub package](https://github.com/AnkiQuest/AnkiQuest-Desktop/releases/latest) remains available; remove the other installation before switching channels and sign in with the same AnkiQuest account.
3. Study as usual. Open **Tools → AnkiQuest → Friends** to manage friends and groups, preview a group invitation, or start a friend goal. The website's **Friends** page is also available.

## Development

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r tests/requirements-anki-26.9.4.txt
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
cargo run --manifest-path tools/package-addon/Cargo.toml -- --output ankiquest.ankiaddon
```

### Screenshots and banner

`docs/screenshots/desktop-*.png` and the banner are drawn, not captured by hand. `tests/draw_screenshots.py` renders each add-on screen offscreen from the fake players and server replies in `tests/screenshots/data.json`, with a fixed clock, the fonts in `tests/screenshots/fonts` and fixed window sizes. `ankiquest-banner`, the banner tool every AnkiQuest repository shares ([AnkiQuest-Dev](https://github.com/AnkiQuest/AnkiQuest-Dev#readme-banner-and-social-preview)), draws `docs/graphics/banner_readme.png` and `social_preview.png` from those screenshots and the duo master of the AnkiQuest-Art release pinned in `ankiquest-art.json`, unzipped from its `masters.zip` into `art/`; `docs/graphics/banner.toml` lists its inputs. CI's "Screenshots" and "banner" jobs draw all of them again and fail when a committed file differs in any pixel. After changing a screen, regenerate them on Ubuntu 24.04 with the 26.9.4 requirements installed (`--record` runs `tests/draw_screenshots.py` first):

```sh
(
  set -eu
  art_stage=$(mktemp -d)
  art_tag=$(node -p 'require("./ankiquest-art.json").tag')
  for art_asset in masters.zip manifest.json; do
    curl -fsSL -o "$art_stage/$art_asset" \
      "https://github.com/AnkiQuest/AnkiQuest-Art/releases/download/$art_tag/$art_asset"
    art_hash=$(node -p 'require("./ankiquest-art.json").assets[process.argv[1]]' "$art_asset")
    printf '%s  %s\n' "$art_hash" "$art_stage/$art_asset" | sha256sum --check
  done
  mkdir -p art
  unzip -qo "$art_stage/masters.zip" -d art
  cp "$art_stage/manifest.json" art/manifest.json
) &&
cargo run --locked --manifest-path tools/package-addon/Cargo.toml -- art &&
cargo run --release --manifest-path ../AnkiQuest-Dev/tools/banner/Cargo.toml -- --server . --record
```

Another system or Qt draws slightly different text, so CI fails on pictures drawn there. A failing run keeps its drawings as the `screenshots` and `banner` artifacts.

[Desktop compatibility, tests and packages](docs/desktop.md) has the supported Anki versions, the CI jobs and the release steps. The tests read the shared fixtures and API examples of AnkiQuest-Server `master`; `cargo run --locked --manifest-path tools/package-addon/Cargo.toml -- server-data` copies them into `tests/` ([Server data](docs/desktop.md#server-data)). The companion pictures come from the [AnkiQuest-Art](https://github.com/AnkiQuest/AnkiQuest-Art) release pinned in `ankiquest-art.json`; `cargo run --locked --manifest-path tools/package-addon/Cargo.toml -- art` puts them in `addon/` ([Companion pictures](docs/desktop.md#companion-pictures)).

## License

AGPL-3.0-or-later.

Anki-tan (the add-on's `art/anki_tan_*` pictures, and her masters in AnkiQuest-Art's `anki-tan/`) is by [Shigeyuki](https://www.patreon.com/Shigeyuki), from the [Anki-tan asset pack](https://shigeyukey.github.io/shige-addons-wiki/Anki-tan.html), licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Derivatives of her art are CC BY-SA 4.0 too.
