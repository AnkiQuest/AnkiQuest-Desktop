# Shared fixtures from AnkiQuest-Server

Byte-for-byte copies of `tests/fixtures/*.json` from AnkiQuest-Server, read
by the add-on tests. CI compares each with the Server commit named in the
`desktop` job of `.github/workflows/ci.yml`.

`tests/fixtures/` still holds the copies the server code in this repository
reads. They go with that code (#306); until then, add-on tests that need a
fixture newer than those read it from here.
