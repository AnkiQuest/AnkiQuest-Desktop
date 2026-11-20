# Fixtures ahead of the Server snapshot

Byte-for-byte copies of AnkiQuest-Server's `tests/fixtures/*.json` from a
Server commit newer than the pin in `tests/ankiquest-server.sha`, for the
few fixtures the add-on already implements there. CI compares each with
the commit named in the `desktop` job of `.github/workflows/ci.yml`.

When the pin reaches that commit, move each file into `tests/fixtures/`
and point its tests there; then this folder goes.
