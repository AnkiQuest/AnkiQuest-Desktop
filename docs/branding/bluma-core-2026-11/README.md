# Bluma core poses

Art for [#321](https://github.com/AnkiQuest/AnkiQuest-Desktop/issues/321),
part of [#88](https://github.com/AnkiQuest/AnkiQuest-Desktop/issues/88).
Aldana has not yet approved the appearance. This supplies assets;
the other contributor owns pose selection and unlock activation.

| Aki reference | Ankilope reference | Bluma face | Bluma happy |
|---|---|---|---|
| ![Aki](../../../static/aki/face.png) | ![Ankilope](../../../static/ankilope/face.png) | ![Face](../../../static/bluma/face.png) | ![Happy](../../../static/bluma/celebrate.png) |

| Asleep | Streak | Sad |
|---|---|---|
| ![Asleep](../../../static/bluma/sleeping.png) | ![Streak](../../../static/bluma/streak.png) | ![Sad](../../../static/bluma/sad.png) |

| Hopeful | Frozen | Neglected |
|---|---|---|
| ![Hopeful](../../../static/bluma/hopeful.png) | ![Frozen](../../../static/bluma/frozen.png) | ![Neglected](../../../static/bluma/neglected.png) |

OpenAI `image_gen` generated three candidates per pose on 2026-11-16;
its model identifier was not exposed. [Generation records](generation.json)
retain all 24 prompts. Happy C established the cow's identity; the other
poses used that image as their reference. Selections: face C, asleep A,
happy C, streak B, sad C, hopeful B, frozen B and neglected B. Happy B
had an extra limb; hopeful A had a broad glow. The selected set preserves
the same face, scarf, satchel, markings and proportions.

Each master is 1254 x 1254 RGBA, with no text. The existing
[alpha cleanup](../alpha-cleanup/README.md) clears only alpha 1-4.
[Measurements](measurements.json) record source/output hashes, unchanged
pixels above alpha 4 and a maximum composite change of 4/255. Inspected
each pose on white, dark and grey, at native size and 64/128 px. Original
artwork is preserved; these masters and exports use new `bluma_*` names.

[Reusable prompts](prompts.md) supply a style prompt and one prompt per
core pose for the custom-companion template. `celebrate` is the export
name for happy; `sleeping` is the export name for asleep.

The existing Rust exporters produce canonical 256 px add-on PNGs and
1024 px Android WebPs on Linux. Their run and hashes will be recorded
before this draft becomes ready for review.
