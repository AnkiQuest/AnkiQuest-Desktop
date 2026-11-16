# Full-size Anki-tan additions

Part of [#88](https://github.com/AnkiQuest/AnkiQuest-Desktop/issues/88).
Adds asleep, sad and neglected masters. These supply full-size art where
the imported pack uses chibi faces. Streak is still outstanding. The
other agent owns pose selection and unlock activation.

| Original reference | Existing frozen | Asleep | Sad | Neglected |
|---|---|---|---|---|
| ![Original](../../../static/anki-tan/illust/anki_tan_main.png) | ![Frozen](../../../static/anki-tan/generated/frozen-full.png) | ![Asleep](../../../static/anki-tan/generated/asleep-full.png) | ![Sad](../../../static/anki-tan/generated/sad-full.png) | ![Neglected](../../../static/anki-tan/generated/neglected-full.png) |

Aldana approved these three images on 2026-11-16. Three candidates
were generated per pose using OpenAI's `image_gen` tool; its model
identifier was not exposed. Selections: asleep A, sad A, neglected C.
The approved frozen derivative and Shigeyuki's main illustration were
the reference images. [Prompts](generation.json) retain all nine variants.

Each master is 1254 x 1254 RGBA, with no text. The existing
[alpha cleanup](../alpha-cleanup/README.md) clears only pixels with
alpha 1-4. [Measurements](measurements.json) record source/output hashes,
unchanged pixels above alpha 4, and a maximum composite change of 4/255.
The selected art was inspected on white, dark and grey, including 64 px
and 128 px previews. Original art is preserved.

Anki-tan by Shigeyuki (https://www.patreon.com/Shigeyuki).
These derivatives and their exports are licensed CC BY-SA 4.0 under
[her LICENSE](../../../static/anki-tan/LICENSE).

Canonical exports use `export-addon-art` and `export-android-art` on
Linux. [Run 43789530883](https://github.com/AnkiQuest/AnkiQuest-Desktop/actions/runs/43789530883)
generated both clients' files from e8794893e539622078dbbdab4b4ffdd2a20c2e78.
All 31 existing add-on poses remained byte-identical. The three new
add-on files match the hashes in `crates/xtask/art-exports.json`.
The Android companion work is tracked in
[AnkiQuest-Android#337](https://github.com/AnkiQuest/AnkiQuest-Android/issues/337).

The Companion art exports workflow retains both clients' output, the
manifest and its diff for seven days. It never commits files; contributors
inspect the artifact and commit the selected exports before final CI.

The inventory counts exporter-registered masters as well as standard pose
filenames. This keeps all Anki-tan derivatives under their existing licence
directory while recognizing the full-size poses and chibi frozen fallback.
The regression failed before the fix in CI run 43793210490: asleep was
reported Missing instead of Present (48 xtask tests passed, one failed).
Registration alone never counts a master whose file is absent.
