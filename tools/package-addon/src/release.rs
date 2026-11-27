//! Assets of GitHub releases: AnkiQuest-Art's pictures, from the release
//! `ankiquest-art.json` pins, and the downloads `rules` makes from
//! AnkiQuest-Server's newest rules release.
//!
//! A pin file names the release's tag and the SHA-256 of each asset. An
//! asset is downloaded once into a cache named by its SHA-256 and checked
//! against its hash before every use, so a build works offline after the
//! first. A folder named by the source's local variable holds the assets to
//! use instead of downloading them, for a release not published yet; they
//! are checked against the pin the same way. The rules check a downloaded
//! asset against their release's attestation too, before it is cached.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;
use sha2::{Digest, Sha256};

/// Length of a SHA-256 digest in hexadecimal.
const SHA256_HEX_LEN: usize = 64;

/// Where a kind of asset comes from and where it is kept.
pub(super) struct Source {
    /// The pin file at the repository root, or what else holds the hashes
    /// assets are checked against (a release's `SHA256SUMS`).
    pub(super) pin: &'static str,
    /// The repository that publishes the releases, for messages.
    pub(super) repository: &'static str,
    /// Where the repository publishes its release assets.
    pub(super) releases: &'static str,
    /// The variable naming a folder of assets to use instead.
    pub(super) local_dir: &'static str,
    /// The variable naming the download cache, if not the default.
    pub(super) cache_dir: &'static str,
    /// The cache's folder name inside the user's cache folder.
    pub(super) cache_name: &'static str,
}

/// Where the assets come from.
#[derive(Debug, PartialEq)]
enum Origin {
    /// The published release with this tag.
    Release(String),
    /// A folder of assets, for a release not published yet.
    Local(PathBuf),
}

/// What the pin file says about the release.
struct Pin {
    tag: Option<String>,
    assets: Value,
}

/// The bytes of asset `name` from the release `source` pins in `repo`,
/// checked against the pin.
pub(super) fn fetch(source: &Source, repo: &Path, name: &str) -> Result<Vec<u8>, String> {
    let pin = Pin::read(&repo.join(source.pin))?;
    let local = env::var_os(source.local_dir).map(PathBuf::from);
    let origin = origin(source, &pin, local)?;
    asset(source, &pin, &origin, name)
}

impl Pin {
    /// The pin file at `path`.
    fn read(path: &Path) -> Result<Self, String> {
        let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let value: Value =
            serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
        Ok(Self {
            tag: value.get("tag").and_then(Value::as_str).map(str::to_owned),
            assets: value.get("assets").cloned().unwrap_or(Value::Null),
        })
    }

    /// The pinned SHA-256 of `name`, in lower-case hex.
    fn sha256(&self, source: &Source, name: &str) -> Result<String, String> {
        let pin = source.pin;
        let hash = self
            .assets
            .get(name)
            .and_then(Value::as_str)
            .ok_or_else(|| format!("{pin} pins no {name}"))?;
        if hash.len() != SHA256_HEX_LEN || !hash.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(format!("{pin} pins an invalid SHA-256 for {name}"));
        }
        Ok(hash.to_ascii_lowercase())
    }
}

/// Where the assets come from: a local folder if one is named, else the
/// pinned release, which must have a tag.
fn origin(source: &Source, pin: &Pin, local: Option<PathBuf>) -> Result<Origin, String> {
    if let Some(folder) = local {
        return Ok(Origin::Local(folder));
    }
    match &pin.tag {
        Some(tag) => Ok(Origin::Release(tag.clone())),
        None => Err(format!(
            "{} names no {} release yet; set {} to a folder with its assets",
            source.pin, source.repository, source.local_dir
        )),
    }
}

/// The bytes of asset `name`, checked against the pin.
fn asset(source: &Source, pin: &Pin, origin: &Origin, name: &str) -> Result<Vec<u8>, String> {
    let expected = pin.sha256(source, name)?;
    let path = match origin {
        Origin::Local(folder) => folder.join(name),
        Origin::Release(tag) => {
            let cache = cache(source)?;
            download(source, tag, name, &expected, &cache, &mut |_| Ok(()))?;
            cache.join(&expected)
        }
    };
    let bytes = fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    verify(source, name, &bytes, &expected)?;
    Ok(bytes)
}

/// The file `attest` checks a downloaded asset in, before it is cached.
pub(super) type Attest<'a> = dyn FnMut(&Path) -> Result<(), String> + 'a;

/// Asset `name` of release `tag`, from the cache or downloaded, checked
/// against `sha256`. A download is cached only once `attest` accepts it; a
/// cached asset was accepted when it was cached, so it serves offline.
pub(super) fn checked(
    source: &Source,
    tag: &str,
    name: &str,
    sha256: &str,
    attest: &mut Attest,
) -> Result<Vec<u8>, String> {
    let cache = cache(source)?;
    download(source, tag, name, sha256, &cache, attest)?;
    let path = cache.join(sha256);
    let bytes = fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    verify(source, name, &bytes, sha256)?;
    Ok(bytes)
}

/// The body of `url`, through curl. `GITHUB_TOKEN`, when set, goes along
/// as a bearer token, for the API's rate limit.
pub(super) fn get(url: &str) -> Result<Vec<u8>, String> {
    let mut command = Command::new("curl");
    command.args(["--fail", "--location", "--silent", "--show-error"]);
    if let Some(token) = env::var_os("GITHUB_TOKEN").filter(|token| !token.is_empty()) {
        let mut header = std::ffi::OsString::from("Authorization: Bearer ");
        header.push(token);
        command.arg("--header").arg(header);
    }
    let output = command
        .arg(url)
        .output()
        .map_err(|e| format!("curl: {e}"))?;
    if !output.status.success() {
        return Err(format!("{url}: download failed ({})", output.status));
    }
    Ok(output.stdout)
}

/// Fails unless `bytes` have the SHA-256 `expected`.
pub(super) fn verify(
    source: &Source,
    name: &str,
    bytes: &[u8],
    expected: &str,
) -> Result<(), String> {
    let actual = hex(&Sha256::digest(bytes));
    if actual != expected {
        return Err(format!(
            "{name}: SHA-256 {actual}, but {} says {expected}",
            source.pin
        ));
    }
    Ok(())
}

/// Lower-case hex of `bytes`.
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Downloads asset `name` of release `tag` into `cache` as `<sha256>`,
/// unless a file with the right hash is already there. The download takes
/// that name only once it has the hash and `attest` accepts it.
fn download(
    source: &Source,
    tag: &str,
    name: &str,
    sha256: &str,
    cache: &Path,
    attest: &mut Attest,
) -> Result<(), String> {
    let target = cache.join(sha256);
    let cached = fs::read(&target).is_ok_and(|bytes| verify(source, name, &bytes, sha256).is_ok());
    if cached {
        return Ok(());
    }
    fs::create_dir_all(cache).map_err(|e| format!("{}: {e}", cache.display()))?;

    // A partial download never takes the final name.
    let partial = cache.join(format!("{sha256}.part"));
    let url = format!("{}/{tag}/{name}", source.releases);
    let status = Command::new("curl")
        .args([
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--output",
        ])
        .arg(&partial)
        .arg(&url)
        .status()
        .map_err(|e| format!("curl: {e}"))?;
    if !status.success() {
        return Err(format!("{url}: download failed ({status})"));
    }
    let bytes = fs::read(&partial).map_err(|e| format!("{}: {e}", partial.display()))?;
    verify(source, name, &bytes, sha256)?;
    if let Err(error) = attest(&partial) {
        let _ = fs::remove_file(&partial);
        return Err(error);
    }
    fs::rename(&partial, &target).map_err(|e| format!("{}: {e}", target.display()))
}

/// The download cache: the source's cache variable, else its folder in the
/// user's cache folder.
fn cache(source: &Source) -> Result<PathBuf, String> {
    if let Some(folder) = env::var_os(source.cache_dir) {
        return Ok(PathBuf::from(folder));
    }
    let base = env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("LOCALAPPDATA").map(PathBuf::from))
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
        .ok_or(format!("no cache folder; set {}", source.cache_dir))?;
    Ok(base.join(source.cache_name))
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use tempfile::TempDir;

    use super::*;

    /// A source for the tests.
    const TEST: Source = Source {
        pin: "test-pin.json",
        repository: "Test",
        releases: "https://example.invalid/releases/download",
        local_dir: "ANKIQUEST_TEST_DIR",
        cache_dir: "ANKIQUEST_TEST_CACHE",
        cache_name: "ankiquest-test",
    };

    /// The asset the tests pin.
    const ASSET: &str = "asset.bin";

    /// A pin of `assets` (name to bytes) under `tag`.
    fn pin(tag: Option<&str>, assets: &[(&str, &[u8])]) -> Pin {
        let hashes: serde_json::Map<String, Value> = assets
            .iter()
            .map(|(name, bytes)| ((*name).to_owned(), json!(hex(&Sha256::digest(bytes)))))
            .collect();
        Pin {
            tag: tag.map(str::to_owned),
            assets: Value::Object(hashes),
        }
    }

    #[test]
    fn a_null_tag_needs_a_local_folder() {
        let error = origin(&TEST, &pin(None, &[]), None).unwrap_err();
        assert!(error.contains(TEST.local_dir), "{error}");
        let local = PathBuf::from("assets");
        assert_eq!(
            Origin::Local(local.clone()),
            origin(&TEST, &pin(None, &[]), Some(local)).unwrap()
        );
        assert_eq!(
            Origin::Release("art-1".to_owned()),
            origin(&TEST, &pin(Some("art-1"), &[]), None).unwrap()
        );
    }

    #[test]
    fn local_assets_are_checked_against_the_pin() {
        let folder = TempDir::new().unwrap();
        fs::write(folder.path().join(ASSET), b"new").unwrap();
        let local = Origin::Local(folder.path().to_path_buf());

        let pinned = pin(None, &[(ASSET, b"new")]);
        assert_eq!(
            b"new".to_vec(),
            asset(&TEST, &pinned, &local, ASSET).unwrap()
        );

        let stale = pin(None, &[(ASSET, b"old")]);
        let error = asset(&TEST, &stale, &local, ASSET).unwrap_err();
        assert!(error.contains("SHA-256"), "{error}");

        let error = asset(&TEST, &pin(None, &[]), &local, ASSET).unwrap_err();
        assert!(error.contains("pins no"), "{error}");
    }

    #[test]
    fn a_cache_key_must_be_a_hex_digest() {
        let mut pinned = pin(None, &[(ASSET, b"new")]);
        for value in ["1234".to_owned(), "g".repeat(SHA256_HEX_LEN)] {
            pinned.assets[ASSET] = json!(value);
            let error = pinned.sha256(&TEST, ASSET).unwrap_err();
            assert!(error.contains("invalid SHA-256"), "{error}");
        }
    }

    #[test]
    fn a_download_is_cached_only_once_attested() {
        let releases = TempDir::new().unwrap();
        fs::create_dir(releases.path().join("rules-1")).unwrap();
        fs::write(releases.path().join("rules-1").join(ASSET), b"new").unwrap();
        let url = format!("file://{}", releases.path().display());
        let source = Source {
            releases: Box::leak(url.into_boxed_str()),
            ..TEST
        };
        let cache = TempDir::new().unwrap();
        let sha = hex(&Sha256::digest(b"new"));

        let error = download(&source, "rules-1", ASSET, &sha, cache.path(), &mut |_| {
            Err("not attested".to_owned())
        })
        .unwrap_err();
        assert_eq!("not attested", error);
        assert_eq!(0, fs::read_dir(cache.path()).unwrap().count());

        download(&source, "rules-1", ASSET, &sha, cache.path(), &mut |file| {
            assert_eq!(b"new".to_vec(), fs::read(file).unwrap());
            Ok(())
        })
        .unwrap();
        assert_eq!(b"new".to_vec(), fs::read(cache.path().join(&sha)).unwrap());
    }

    #[test]
    fn a_cached_asset_is_used_without_downloading() {
        let cache = TempDir::new().unwrap();
        let sha = hex(&Sha256::digest(b"cached"));
        fs::write(cache.path().join(&sha), b"cached").unwrap();
        let mut attested = 0;
        download(&TEST, "art-0", ASSET, &sha, cache.path(), &mut |_| {
            attested += 1;
            Ok(())
        })
        .unwrap();
        assert_eq!(0, attested, "a cached asset was checked when it was cached");
    }
}
