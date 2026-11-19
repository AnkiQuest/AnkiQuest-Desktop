AnkiQuest-Server's copies of the shared fixtures this add-on tests against. CI compares each file
with the Server commit pinned in `.github/workflows/ci.yml`. `tests/fixtures` keeps the older
copies that this repository's frozen server code reads until #306 removes it.
