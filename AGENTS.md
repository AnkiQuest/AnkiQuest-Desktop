# Agent instructions

AnkiQuest adds XP, streaks, friends, leaderboards and moments to Anki. It has three repositories:

- [AnkiQuest/AnkiQuest-Server](https://github.com/AnkiQuest/AnkiQuest-Server): the server (Rust), its web pages (TypeScript), the API examples, the shared fixtures and the companion art masters.
- [AnkiQuest/AnkiQuest-Desktop](https://github.com/AnkiQuest/AnkiQuest-Desktop): the Anki desktop add-on (Python).
- [AnkiQuest/AnkiQuest-Android](https://github.com/AnkiQuest/AnkiQuest-Android): the Android app (Kotlin), a fork of AnkiDroid.

These rules apply to every agent (Claude, Codex, others) and to people too. Everything above "This repository" is the same in all three repositories: change it in AnkiQuest-Server first, then copy it to the other two. CI fails while a copy differs.

## People

- hill (GitHub float3).
- Aldana (GitHub AldanaBRZ).
- The owners: hill and Aldana together. They decide and approve, with equal rights and responsibilities in the project.
- Claude: Claude Code agents.
- Astra: Aldana's Codex agent, which posts as AldanaBRZ.

Never call a person "the owner"; name them. "Code owner" describes how you treat the code, not who decides. "The owners" means hill and Aldana together. Name the person who approved something: "hill approved…", "Aldana approved…". An agent passing on an approval links the person's own words.

## Code ownership

You are the code owner and long-term maintainer of this codebase. The design is yours to decide, unless hill or Aldana overrules it.

Act like it: consolidate duplicated code instead of copying it, fix what you find instead of only reporting it, and leave the code better than you found it. List every change, including small ones, in the PR description; reviewers read the diff against it.

Don't hold on to the past. Deprecate and remove old code, tools, docs and layouts instead of keeping shims, aliases or "moved to" stubs, and make breaking changes when they make the design clearer. Pull requests that remove code are especially welcome. Say in the PR what breaks and who has to act. Two limits still apply: released apps keep working, so old endpoints, fields and API examples stay until no supported client uses them; and companion art is never deleted (see below).

## Bugs: test first

1. Write a regression test that reproduces the bug.
2. Run it and watch it fail for the expected reason.
3. Fix the bug.
4. Run it again and watch it pass, together with the rest of the suite.

Say in the PR that the test failed before the fix. Never skip, disable or loosen a test to get CI green.

## Languages

Write new code in Rust, or TypeScript for the web, when the platform allows it. Use other languages only where the host demands them: Kotlin for the Android app, Python for the Anki desktop add-on. Do not add new Python tools or scripts; when you change an existing one substantially, port it to Rust.

## Code

- Name values: extract recurring or meaningful values into constants or enums; values from a spec (HTTP status codes, for example) always get a constant. Keep obvious one-off values inline.
- Return early; avoid deep nesting.
- Always use braces, even for one-line `if`s.
- Short function names, under 30 characters.
- Enums instead of booleans for function parameters.
- Blank lines between logical blocks, and a short comment saying what a block does and why.
- Keep members private by default. Widening visibility to share code instead of duplicating it is welcome; no approval is needed. Say in the PR what was widened and why.
- Layer the code: low-level mechanics (HTTP, database, files, platform APIs) sit behind an abstraction, and each layer talks only to the one directly below it.
- Prefer targeted edits over rewriting whole files.
- Keep all state explicit. Model a lifecycle or mode as one enum or sealed type with named states and named transitions, not as several booleans, nullable fields and timestamps whose combination means something. Every state is visible in one place, impossible combinations can't be represented, and tests cover each transition.

## Git and pull requests

- Start each session with `git fetch` and work from the latest default branch.
- Never push to the default branch; open a pull request.
- Pull requests by hill or Claude need an approving review from Aldana or Astra (the AldanaBRZ account). Pull requests by Aldana or Astra need an approving review from hill or Claude (the float3 account). One approval from the other side is enough; merge only once it is given and every check is green on the final commit. hill may merge trivially correct changes (documentation, AGENTS.md, README, labels, search and replace) without that review.
- Commit messages: subject in the imperative, capitalised, at most 50 characters (72 hard limit), no full stop; a blank line; a body wrapped at 72 characters that explains what and why, not how.
- Name the model that did the work. Every commit, pull request, issue, comment and review an agent writes ends with `Assisted-by: <tool> (<model and version>)`, such as `Assisted-by: Claude Code (Opus 5.5)` or `Assisted-by: Codex (GPT-6)`. Generated images name the model that drew them in the pull request and in their generation record. If the tool does not say which model it used, write that instead of guessing.
- Never link to an agent session (such as `claude.ai/code/session_…`) in commits, pull requests, issues or comments.
- No emoji in commits, pull requests, issues or comments.
- Never commit secrets, tokens or personal data. Secrets live on the servers, outside the repositories.

## Desktop and Android parity

AnkiQuest has two clients: the Android app ([AnkiQuest/AnkiQuest-Android](https://github.com/AnkiQuest/AnkiQuest-Android)) and the Anki desktop add-on (`addon/` in [AnkiQuest/AnkiQuest-Desktop](https://github.com/AnkiQuest/AnkiQuest-Desktop)). A player should get the same AnkiQuest on both.

- A user-facing feature or behaviour change lands on both clients, unless the platform can't do it (home-screen widgets, for example). Do both in one go when you can. Otherwise open an issue in the other repository, labelled `parity`, and link it from the PR.
- Rules both clients compute (streak verdicts, heatmap, card labels, deck names) are defined once, as cases in `tests/fixtures/*.json` in [AnkiQuest/AnkiQuest-Server](https://github.com/AnkiQuest/AnkiQuest-Server/tree/master/tests/fixtures). Both clients test against the same cases. Change the fixture first, then both implementations.
- Use the same names, wording and order for the same thing on both clients.
- When you find a gap between the clients, open a `parity` issue for it.

## Companion art

Companion art means every picture of a character: poses, moment and card pictures, widget and notification drawables.

- Masters live only in `static/<companion>/` in AnkiQuest-Server. Every other copy (share cards, add-on, Android, docs) is generated from them by the exporters and hash-checked in CI; never commit a hand-made copy.
- Never delete companion art, even when nothing uses it any more. Remove the references, keep the files, so they can be reused or merged later.
- Each character needs a core set of poses before it goes live in the apps: face, asleep, happy, streak (on fire), sad, hopeful, frozen and neglected. A character without the full core set stays hidden.
- Every other pose is an extension: streak tiers, milestones, frozen days 2 and 3, hurt, dead, welcome, a defeated leech, and poses for other rare moments. Extensions are optional. A missing extension falls back to its core pose (a streak tier to streak, frozen 3 to frozen, a defeated leech to happy).
- The core set, the extensions and their fallbacks are defined once, in [`tests/fixtures/companion_poses.json`](https://github.com/AnkiQuest/AnkiQuest-Server/blob/master/tests/fixtures/companion_poses.json) in AnkiQuest-Server; both clients use that list.

## Writing

Write comments, commit messages, issues and PR descriptions with as few words as needed. No praise, no filler, no superlatives. Em dashes take no spaces around them.

Mannered prose substitutes metaphor and flourish for direct statement. Instead of "a parameter worth varying," the mannered writer produces "a dial worth turning." Instead of "this point still matters," they write "this point earns its keep." The phrases exist to display the writer, not to convey the idea, and readers can tell. That is why mannered prose irritates: it makes the reader work harder so the writer can perform. It is also imprecise. Metaphors drag in connotations the writer did not choose and cannot control. The fix is to say what you mean. When a literal phrase is available, use it.

## This repository

AnkiQuest-Desktop holds the Anki desktop add-on and its releases.

- **Layout.** `addon/`: the add-on, Python because Anki requires it. `tests/`: add-on tests (Python). `tools/package-addon`: the add-on packager (`cargo run --manifest-path tools/package-addon/Cargo.toml -- --output <file>`), a Rust workspace of its own that stays when the server moves out. `crates/xtask` holds the other repository tools (`cargo run -p ankiquest-xtask -- <command>`). Python is only the add-on and its tests; write every other tool, check and test in Rust.
- **Freeze.** Server code (`src/`, `crates/` except xtask, `web/`, server docs and `docs/api`) is frozen here: open server changes against AnkiQuest-Server. The remaining copy is removed by #306.
- **The server is moving out.** The server, web, API, fixture and deployment code still here (`src/`, `crates/` other than `xtask`, `web/`, `static/`, the TypeScript tests, `docs/api/`, `flake.nix`) is removed by #306. Change it in AnkiQuest-Server, not here. Until then the add-on tests read this copy of `tests/fixtures/*.json`; change a fixture in AnkiQuest-Server first.
- **Shared instructions.** Everything above "This repository" in this file is a copy of AnkiQuest-Server's `AGENTS.md`; the `agents-copy` workflow fails while they differ. Change it there first.
- **Releases** are the `addon-*` tags and GitHub releases of this repository; AnkiWeb lists the add-on as 414948448.
- **Checks to run** before pushing, for what you changed: `python -m unittest discover -s tests` for the add-on; `cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings` and `cargo test --workspace` for `xtask`; the same three with `--manifest-path tools/package-addon/Cargo.toml` for the packager. Leave the full matrix to CI.
