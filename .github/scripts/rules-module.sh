#!/usr/bin/env bash
# Makes the shared rules' module that ankiquest-rules.json pins available to
# the packager. While the pin names no release, builds it from the pinned
# AnkiQuest-Server commit (crates/rules-wasm/build.sh, reproducible) and
# points ANKIQUEST_RULES_DIR at it for the following steps; the packager
# checks it against the pinned SHA-256 either way.
set -euo pipefail
if [ "$(jq -r .tag ankiquest-rules.json)" != null ]; then
  exit 0
fi

# Only the workspace manifests and the crates are needed.
server="$RUNNER_TEMP/rules-server"
git init -q "$server"
git -C "$server" sparse-checkout set --no-cone /Cargo.toml /Cargo.lock /build.rs /src/ /crates/
git -C "$server" fetch -q --depth 1 --filter=blob:none https://github.com/AnkiQuest/AnkiQuest-Server "$(jq -r .commit ankiquest-rules.json)"
git -C "$server" checkout -q FETCH_HEAD
(cd "$server/crates/rules" && rustup toolchain install && rustup target add wasm32-unknown-unknown)
"$server/crates/rules-wasm/build.sh" "$RUNNER_TEMP/rules"
echo "ANKIQUEST_RULES_DIR=$RUNNER_TEMP/rules" >> "$GITHUB_ENV"
