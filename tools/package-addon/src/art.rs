//! The add-on's companion pictures, from the AnkiQuest-Art release that
//! `ankiquest-art.json` pins.
//!
//! `addon-art.zip` holds `art/<name>.png`, `<companion>_face.png` and
//! Anki-tan's licence, `art/LICENSE-Anki-tan.md`, which are unpacked into
//! `addon/` after the pictures of an earlier run are removed. The asset is downloaded once into a cache named by its
//! SHA-256 and checked against the pin before every use, so a build works
//! offline after the first. `ANKIQUEST_ART_DIR` names a folder holding the
//! release assets to use instead of downloading them, for a release not
//! published yet; they are checked against the pin the same way.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::zip;

/// The pin file, at the repository root.
pub(super) const PIN: &str = "ankiquest-art.json";

/// Where AnkiQuest-Art publishes its release assets.
const RELEASES: &str = "https://github.com/AnkiQuest/AnkiQuest-Art/releases/download";

/// The release asset with the add-on's pictures.
const PICTURES: &str = "addon-art.zip";

/// A folder of release assets to use instead of downloading them.
const LOCAL_DIR: &str = "ANKIQUEST_ART_DIR";

/// The download cache, if not the default.
const CACHE_DIR: &str = "ANKIQUEST_ART_CACHE";

/// The cache's folder name inside the user's cache folder.
const CACHE_NAME: &str = "ankiquest-art";

/// The folder of the poses, inside the add-on and the asset.
const POSES: &str = "art";

/// Each face sits beside the code as `<companion>_face.png`.
const FACE_SUFFIX: &str = "_face.png";

/// The pictures' file extension.
const PNG: &str = ".png";

/// Anki-tan's licence, which her pictures (CC BY-SA 4.0) travel with.
const LICENCE: &str = "art/LICENSE-Anki-tan.md";

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

/// Unpacks the pinned pictures into `addon`.
pub(super) fn fetch(repo: &Path, addon: &Path) -> Result<(), String> {
    let pin = Pin::read(&repo.join(PIN))?;
    let local = env::var_os(LOCAL_DIR).map(PathBuf::from);
    let origin = origin(&pin, local)?;
    let bytes = asset(&pin, &origin, PICTURES)?;
    unpack(&bytes, addon)
}

/// Unpacks the pictures in `bytes`, an `addon-art.zip`, into `addon`,
/// replacing those of an earlier run.
fn unpack(bytes: &[u8], addon: &Path) -> Result<(), String> {
    let entries = zip::entries(bytes).map_err(|e| format!("{PICTURES}: {e}"))?;

    // Every entry is checked before anything in the add-on changes.
    if let Some((name, _)) = entries
        .iter()
        .find(|(name, _)| name != LICENCE && !picture(name))
    {
        return Err(format!("{PICTURES}: unexpected entry {name}"));
    }
    if !entries.iter().any(|(name, _)| name == LICENCE) {
        return Err(format!("{PICTURES}: no {LICENCE}"));
    }
    clear(addon)?;
    for (name, data) in entries {
        let path = addon.join(&name);
        if let Some(folder) = path.parent() {
            fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
        }
        fs::write(&path, data).map_err(|e| format!("{}: {e}", path.display()))?;
    }
    Ok(())
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
    fn sha256(&self, name: &str) -> Result<String, String> {
        self.assets
            .get(name)
            .and_then(Value::as_str)
            .map(str::to_ascii_lowercase)
            .ok_or_else(|| format!("{PIN} pins no {name}"))
    }
}

/// Where the assets come from: a local folder if one is named, else the
/// pinned release, which must have a tag.
fn origin(pin: &Pin, local: Option<PathBuf>) -> Result<Origin, String> {
    if let Some(folder) = local {
        return Ok(Origin::Local(folder));
    }
    match &pin.tag {
        Some(tag) => Ok(Origin::Release(tag.clone())),
        None => Err(format!(
            "{PIN} names no AnkiQuest-Art release yet; set {LOCAL_DIR} to a folder with its assets"
        )),
    }
}

/// The bytes of asset `name`, checked against the pin.
fn asset(pin: &Pin, origin: &Origin, name: &str) -> Result<Vec<u8>, String> {
    let expected = pin.sha256(name)?;
    let folder = match origin {
        Origin::Local(folder) => folder.clone(),
        Origin::Release(tag) => {
            let cache = cache()?;
            download(tag, name, &expected, &cache)?;
            cache
        }
    };
    let path = match origin {
        Origin::Local(_) => folder.join(name),
        Origin::Release(_) => folder.join(&expected),
    };
    let bytes = fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    verify(name, &bytes, &expected)?;
    Ok(bytes)
}

/// Fails unless `bytes` have the SHA-256 `expected`.
fn verify(name: &str, bytes: &[u8], expected: &str) -> Result<(), String> {
    let actual = hex(&Sha256::digest(bytes));
    if actual != expected {
        return Err(format!(
            "{name}: SHA-256 {actual}, but {PIN} pins {expected}"
        ));
    }
    Ok(())
}

/// Lower-case hex of `bytes`.
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Downloads asset `name` of release `tag` into `cache` as `<sha256>`,
/// unless a file with the right hash is already there.
fn download(tag: &str, name: &str, sha256: &str, cache: &Path) -> Result<(), String> {
    let target = cache.join(sha256);
    let cached = fs::read(&target).is_ok_and(|bytes| verify(name, &bytes, sha256).is_ok());
    if cached {
        return Ok(());
    }
    fs::create_dir_all(cache).map_err(|e| format!("{}: {e}", cache.display()))?;

    // A partial download never takes the final name.
    let partial = cache.join(format!("{sha256}.part"));
    let url = format!("{RELEASES}/{tag}/{name}");
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
    verify(name, &bytes, sha256)?;
    fs::rename(&partial, &target).map_err(|e| format!("{}: {e}", target.display()))
}

/// The download cache: `ANKIQUEST_ART_CACHE`, else `ankiquest-art` in the
/// user's cache folder.
fn cache() -> Result<PathBuf, String> {
    if let Some(folder) = env::var_os(CACHE_DIR) {
        return Ok(PathBuf::from(folder));
    }
    let base = env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("LOCALAPPDATA").map(PathBuf::from))
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
        .ok_or(format!("no cache folder; set {CACHE_DIR}"))?;
    Ok(base.join(CACHE_NAME))
}

/// Whether `name` is a picture the asset may hold: `art/<name>.png` or
/// `<companion>_face.png`, nothing outside the add-on folder.
fn picture(name: &str) -> bool {
    let plain = |file: &str| {
        file.ends_with(PNG)
            && file
                .bytes()
                .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'.')
            && !file.starts_with('.')
    };
    match name.split_once('/') {
        Some((folder, file)) => folder == POSES && plain(file),
        None => name.ends_with(FACE_SUFFIX) && plain(name),
    }
}

/// Removes the pictures an earlier run unpacked into `addon`.
fn clear(addon: &Path) -> Result<(), String> {
    let poses = addon.join(POSES);
    if poses.is_dir() {
        fs::remove_dir_all(&poses).map_err(|e| format!("{}: {e}", poses.display()))?;
    }
    let entries = fs::read_dir(addon).map_err(|e| format!("{}: {e}", addon.display()))?;
    for entry in entries {
        let path = entry.map_err(|e| e.to_string())?.path();
        let face = path
            .file_name()
            .is_some_and(|name| name.to_string_lossy().ends_with(FACE_SUFFIX));
        if face {
            fs::remove_file(&path).map_err(|e| format!("{}: {e}", path.display()))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use serde_json::json;
    use tempfile::TempDir;

    use super::*;

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

    /// A release archive of `files`, the way Art's releases store them.
    fn release(files: &[(&str, &[u8])]) -> Vec<u8> {
        // The packager's own writer deflates; a stored archive is built by hand.
        let mut out = Vec::new();
        let mut central = Vec::new();
        for (name, bytes) in files {
            let offset = out.len() as u32;
            let crc = crc32fast::hash(bytes);
            let size = bytes.len() as u32;
            let name_len = name.len() as u16;
            out.extend_from_slice(&0x0403_4b50u32.to_le_bytes());
            out.extend_from_slice(&[20, 0, 0, 0, 0, 0, 0, 0, 0x21, 0]);
            out.extend_from_slice(&crc.to_le_bytes());
            out.extend_from_slice(&size.to_le_bytes());
            out.extend_from_slice(&size.to_le_bytes());
            out.extend_from_slice(&name_len.to_le_bytes());
            out.extend_from_slice(&0u16.to_le_bytes());
            out.extend_from_slice(name.as_bytes());
            out.extend_from_slice(bytes);

            central.extend_from_slice(&0x0201_4b50u32.to_le_bytes());
            central.extend_from_slice(&[20, 3, 20, 0, 0, 0, 0, 0, 0, 0, 0x21, 0]);
            central.extend_from_slice(&crc.to_le_bytes());
            central.extend_from_slice(&size.to_le_bytes());
            central.extend_from_slice(&size.to_le_bytes());
            central.extend_from_slice(&name_len.to_le_bytes());
            central.extend_from_slice(&[0; 8]);
            central.extend_from_slice(&(0o100_644u32 << 16).to_le_bytes());
            central.extend_from_slice(&offset.to_le_bytes());
            central.extend_from_slice(name.as_bytes());
        }
        let start = out.len() as u32;
        let count = files.len() as u16;
        out.extend_from_slice(&central);
        out.extend_from_slice(&0x0605_4b50u32.to_le_bytes());
        out.extend_from_slice(&[0; 4]);
        out.extend_from_slice(&count.to_le_bytes());
        out.extend_from_slice(&count.to_le_bytes());
        out.extend_from_slice(&(central.len() as u32).to_le_bytes());
        out.extend_from_slice(&start.to_le_bytes());
        out.extend_from_slice(&[0; 2]);
        out
    }

    /// Files under `folder`, by relative path with `/` separators.
    fn tree(folder: &Path) -> BTreeMap<String, Vec<u8>> {
        let mut files = BTreeMap::new();
        let mut pending = vec![folder.to_path_buf()];
        while let Some(dir) = pending.pop() {
            for entry in fs::read_dir(dir).unwrap() {
                let path = entry.unwrap().path();
                if path.is_dir() {
                    pending.push(path);
                    continue;
                }
                let name = path.strip_prefix(folder).unwrap().to_string_lossy();
                files.insert(name.replace('\\', "/"), fs::read(&path).unwrap());
            }
        }
        files
    }

    #[test]
    fn a_null_tag_needs_a_local_folder() {
        let error = origin(&pin(None, &[]), None).unwrap_err();
        assert!(error.contains(LOCAL_DIR), "{error}");
        let local = PathBuf::from("assets");
        assert_eq!(
            Origin::Local(local.clone()),
            origin(&pin(None, &[]), Some(local)).unwrap()
        );
        assert_eq!(
            Origin::Release("art-1".to_owned()),
            origin(&pin(Some("art-1"), &[]), None).unwrap()
        );
    }

    #[test]
    fn local_assets_are_checked_against_the_pin() {
        let folder = TempDir::new().unwrap();
        fs::write(folder.path().join(PICTURES), b"new").unwrap();
        let local = Origin::Local(folder.path().to_path_buf());

        let pinned = pin(None, &[(PICTURES, b"new")]);
        assert_eq!(b"new".to_vec(), asset(&pinned, &local, PICTURES).unwrap());

        let stale = pin(None, &[(PICTURES, b"old")]);
        let error = asset(&stale, &local, PICTURES).unwrap_err();
        assert!(error.contains("SHA-256"), "{error}");

        let error = asset(&pin(None, &[]), &local, PICTURES).unwrap_err();
        assert!(error.contains("pins no"), "{error}");
    }

    #[test]
    fn a_cached_asset_is_used_without_downloading() {
        let cache = TempDir::new().unwrap();
        let sha = hex(&Sha256::digest(b"cached"));
        fs::write(cache.path().join(&sha), b"cached").unwrap();
        download("art-0", PICTURES, &sha, cache.path()).unwrap();
    }

    #[test]
    fn pictures_replace_the_previous_ones() {
        let assets = TempDir::new().unwrap();
        let zip = release(&[
            ("aki_face.png", b"face"),
            ("art/aki_sad.png", b"sad"),
            (LICENCE, b"CC BY-SA 4.0"),
        ]);
        fs::write(assets.path().join(PICTURES), &zip).unwrap();
        let addon = TempDir::new().unwrap();
        fs::create_dir(addon.path().join("art")).unwrap();
        fs::write(addon.path().join("art/aki_old.png"), b"old").unwrap();
        fs::write(addon.path().join("ankilope_face.png"), b"old").unwrap();
        fs::write(addon.path().join("share.py"), b"code").unwrap();

        let pinned = pin(None, &[(PICTURES, &zip)]);
        let origin = Origin::Local(assets.path().to_path_buf());
        let bytes = asset(&pinned, &origin, PICTURES).unwrap();
        unpack(&bytes, addon.path()).unwrap();

        let expected: BTreeMap<String, Vec<u8>> = [
            ("aki_face.png", &b"face"[..]),
            ("art/aki_sad.png", b"sad"),
            (LICENCE, b"CC BY-SA 4.0"),
            ("share.py", b"code"),
        ]
        .into_iter()
        .map(|(name, bytes)| (name.to_owned(), bytes.to_vec()))
        .collect();
        assert_eq!(expected, tree(addon.path()));
    }

    #[test]
    fn an_archive_without_the_licence_is_refused() {
        let zip = release(&[("art/aki_sad.png", b"sad")]);
        let addon = TempDir::new().unwrap();
        fs::create_dir(addon.path().join("art")).unwrap();
        fs::write(addon.path().join("art/aki_old.png"), b"old").unwrap();
        let error = unpack(&zip, addon.path()).unwrap_err();
        assert!(error.contains(LICENCE), "{error}");
        assert!(addon.path().join("art/aki_old.png").is_file());
    }

    #[test]
    fn an_archive_with_other_files_is_refused() {
        let zip = release(&[("__init__.py", b"code")]);
        let addon = TempDir::new().unwrap();
        let error = unpack(&zip, addon.path()).unwrap_err();
        assert!(error.contains("unexpected entry"), "{error}");
        assert!(!addon.path().join("__init__.py").exists());
    }

    #[test]
    fn only_pictures_may_be_unpacked() {
        assert!(picture("art/aki_streak_hot.png"));
        assert!(picture("anki_tan_face.png"));
        assert!(!picture("art/../__init__.py"));
        assert!(!picture("../aki_face.png"));
        assert!(!picture("art/sub/aki.png"));
        assert!(!picture("__init__.py"));
        assert!(!picture("aki.png"));
        assert!(!picture("/aki_face.png"));
        assert!(!picture("art/Aki.png"));
        assert!(
            !picture(LICENCE),
            "only the licence itself, by its exact name"
        );
    }

    #[test]
    fn a_broken_archive_is_refused() {
        let mut zip = release(&[("art/aki_sad.png", b"tears")]);
        assert!(zip::entries(&zip).is_ok());
        // Change a byte of the picture: its CRC-32 no longer matches.
        let at = zip.windows(5).position(|w| w == b"tears").unwrap();
        zip[at] = b'S';
        assert!(zip::entries(&zip).unwrap_err().contains("CRC-32"));
        assert!(zip::entries(b"not a zip").is_err());
    }
}
