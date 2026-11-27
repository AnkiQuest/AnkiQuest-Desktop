//! The build provenance attestation of a rules release
//! (`ankiquest_rules.sigstore.json`, see AnkiQuest-Server's
//! docs/shared-rules.md): an asset counts only when the bundle verifies
//! against Sigstore's public trust root, its certificate was issued by
//! [`ISSUER`] to [`SIGNER`], and the asset's SHA-256 is one of its subjects.
//! `SHA256SUMS` alone can be replaced together with the assets it lists.
//!
//! The check is the GitHub CLI's `gh attestation verify` with the bundle
//! given as a file, which needs no login and no API call. The packager
//! already runs curl for its downloads; a Sigstore verifier of its own would
//! bring an async HTTP and TUF stack into this small tool.

use std::path::{Path, PathBuf};
use std::process::Command;

/// The repository whose workflow signs the releases.
const REPOSITORY: &str = "AnkiQuest/AnkiQuest-Server";

/// The release workflow of AnkiQuest-Server, on `master`.
pub(super) const SIGNER: &str = "https://github.com/AnkiQuest/AnkiQuest-Server/.github/workflows/rules-release.yml@refs/heads/master";

/// Who issues the tokens GitHub Actions signs with.
const ISSUER: &str = "https://token.actions.githubusercontent.com";

/// The release's attestation of every asset, a Sigstore bundle.
pub(super) const BUNDLE: &str = "ankiquest_rules.sigstore.json";

/// The GitHub CLI.
const GH: &str = "gh";

/// The arguments of `gh` that verify `file` against `bundle`.
fn arguments(file: &Path, bundle: &Path) -> Vec<std::ffi::OsString> {
    let mut arguments: Vec<std::ffi::OsString> =
        ["attestation", "verify"].iter().map(Into::into).collect();
    arguments.push(file.into());
    arguments.push("--bundle".into());
    arguments.push(bundle.into());
    for (flag, value) in [
        ("--repo", REPOSITORY),
        ("--cert-identity", SIGNER),
        ("--cert-oidc-issuer", ISSUER),
    ] {
        arguments.push(flag.into());
        arguments.push(value.into());
    }
    arguments
}

/// Verifies files against one release's bundle, fetched once.
pub(super) struct Verifier {
    bundle: PathBuf,
    url: String,
    fetched: bool,
}

impl Verifier {
    /// A verifier for the bundle at `url`, kept at `bundle` once fetched.
    pub(super) fn new(url: String, bundle: PathBuf) -> Self {
        Self {
            bundle,
            url,
            fetched: false,
        }
    }

    /// Fails unless the bundle attests `file` (asset `name`) for [`SIGNER`].
    pub(super) fn verify(&mut self, name: &str, file: &Path) -> Result<(), String> {
        // The bundle is fetched again for every build that downloads assets:
        // a release's bundle never changes, but it is small.
        if !self.fetched {
            let bytes = crate::release::get(&self.url)?;
            std::fs::write(&self.bundle, bytes)
                .map_err(|e| format!("{}: {e}", self.bundle.display()))?;
            self.fetched = true;
        }

        let output = Command::new(GH)
            .args(arguments(file, &self.bundle))
            .output()
            .map_err(|e| {
                format!(
                    "{GH}: {e}; the GitHub CLI checks the rules release's attestation (or set ANKIQUEST_RULES_DIR)"
                )
            })?;
        if !output.status.success() {
            return Err(format!(
                "{name} is not attested by {SIGNER}: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gh_checks_the_exact_workflow_and_issuer() {
        let arguments = arguments(Path::new("a.so"), Path::new("b.json"));
        let arguments: Vec<_> = arguments.iter().map(|a| a.to_str().unwrap()).collect();
        assert_eq!(
            vec![
                "attestation",
                "verify",
                "a.so",
                "--bundle",
                "b.json",
                "--repo",
                "AnkiQuest/AnkiQuest-Server",
                "--cert-identity",
                SIGNER,
                "--cert-oidc-issuer",
                "https://token.actions.githubusercontent.com",
            ],
            arguments
        );
    }
}
