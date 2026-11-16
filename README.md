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

AnkiQuest adds XP, streaks, daily quests, friends and leaderboards to Anki. Clients send review history without card content; sharing a conquered card label or a deck copy is an explicit choice. AnkiQuest has three repositories:

- [AnkiQuest-Server](https://github.com/AnkiQuest/AnkiQuest-Server): the server and its website.
- [AnkiQuest-Desktop](https://github.com/AnkiQuest/AnkiQuest-Desktop): the Anki desktop add-on.
- [AnkiQuest-Android](https://github.com/AnkiQuest/AnkiQuest-Android): the Android app, a fork of AnkiDroid.

## Install

1. Create an account on an AnkiQuest server, such as [ankiquest.rationality-munich.com](https://ankiquest.rationality-munich.com). To run your own, see [AnkiQuest-Server](https://github.com/AnkiQuest/AnkiQuest-Server).
2. In Anki 23.10 or newer (Qt 6), open **Tools → Add-ons → Get Add-ons** and enter **414948448** ([AnkiWeb listing](https://ankiweb.net/shared/info/414948448)). Restart Anki, then choose **Tools → AnkiQuest → Settings → Account**. AnkiWeb manages updates. The [GitHub package](https://github.com/AnkiQuest/AnkiQuest-Desktop/releases/latest) remains available; remove the other installation before switching channels and sign in with the same AnkiQuest account.
3. Study as usual. Open **Tools → AnkiQuest → Friends** to manage friends and groups, preview a group invitation, or start a friend goal. The website's **Friends** page is also available.

## Development

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r tests/requirements-anki-26.9.4.txt
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
cargo run -p ankiquest-xtask -- package-addon --output ankiquest.ankiaddon
```

[Desktop compatibility, tests and packages](docs/desktop.md) has the supported Anki versions, the CI jobs and the release steps. The server code still in this repository moves to AnkiQuest-Server (#306); change it there.

## License

AGPL-3.0-only.

Anki-tan (`addon/art/anki_tan_*`, `static/anki-tan/`) is by [Shigeyuki](https://www.patreon.com/Shigeyuki), from the [Anki-tan asset pack](https://shigeyukey.github.io/shige-addons-wiki/Anki-tan.html), licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Derivatives of her art are CC BY-SA 4.0 too.
