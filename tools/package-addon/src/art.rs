//! The add-on's companion pictures, from the AnkiQuest-Art release that
//! `ankiquest-art.json` pins.
//!
//! `addon-art.zip` holds `art/<name>.png`, `<companion>_face.png` and
//! Anki-tan's licence, `art/LICENSE-Anki-tan.md`. The add-on uses the licence
//! and pictures under `art/` and the release's `poses.json`. Each asset is
//! downloaded into a cache named by its SHA-256 and checked against the pin
//! before every use, so a build works offline after the first.
//! `ANKIQUEST_ART_DIR` names a folder holding the
//! release assets to use instead of downloading them, for a release not
//! published yet; they are checked against the pin the same way.

use std::fs;
use std::io::ErrorKind;
use std::path::Path;

use serde_json::Value;

use crate::release::{self, Source};

use crate::zip;

/// The pin file, at the repository root.
pub(super) const PIN: &str = "ankiquest-art.json";

/// Where AnkiQuest-Art publishes its release assets.
const RELEASES: &str = "https://github.com/AnkiQuest/AnkiQuest-Art/releases/download";

/// The release asset with the add-on's pictures.
const PICTURES: &str = "addon-art.zip";

/// AnkiQuest-Art's releases and their pin, shared with the other assets
/// (see `release`).
const SOURCE: Source = Source {
    pin: "ankiquest-art.json",
    repository: "AnkiQuest-Art",
    releases: "https://github.com/AnkiQuest-Art/releases/download",
    local_dir: "ANKIQUEST_ART_DIR",
    cache_dir: "ANKIQUEST_ART_CACHE",
    cache_name: "ankiquest-art",
};

/// The release asset naming the poses and their fallbacks, copied beside the
/// code for the add-on to read.
const POSES_JSON: &str = "poses.json";

/// The folder of the poses, inside the add-on and the asset.
const POSES: &str = "art";

/// The asset also has each face beside the code as `<companion>_face.png`,
/// a copy of `art/<companion>_face.png` the add-on does not use.
const FACE_SUFFIX: &str = "_face.png";

/// The pictures' file extension.
const PNG: &str = ".png";

/// Anki-tan's licence, which her pictures (CC BY-SA 4.0) travel with.
const LICENCE: &str = "art/LICENSE-Anki-tan.md";

/// Unpacks the pinned pictures and poses into `addon`.
pub(super) fn fetch(repo: &Path, addon: &Path) -> Result<(), String> {
    let pictures = release::fetch(&SOURCE, repo, PICTURES)?;
    let poses = release::fetch(&SOURCE, repo, POSES_JSON)?;
    install(&pictures, &poses, addon)
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
        // The top-level faces duplicate those in `art/`.
        if !name.contains('/') {
            continue;
        }
        let path = addon.join(&name);
        if let Some(folder) = path.parent() {
            fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
        }
        fs::write(&path, data).map_err(|e| format!("{}: {e}", path.display()))?;
    }
    Ok(())
}
/// Writes the release's `poses.json` beside the code, where the add-on's
/// `moods.py` reads the poses and their fallbacks from. The parse guards a
/// wrongly pinned asset: `asset()` checks the SHA-256, not that it is JSON.
/// Only a file that is JSON is written.
fn install(pictures: &[u8], poses: &[u8], addon: &Path) -> Result<(), String> {
    if let Err(e) = serde_json::from_slice::<Value>(poses) {
        return Err(format!("{POSES_JSON}: {e}"));
    }
    let directory = fs::symlink_metadata(addon).map_err(|e| format!("{}: {e}", addon.display()))?;
    if !directory.is_dir() {
        return Err(format!("{}: expected an add-on directory", addon.display()));
    }
    let path = addon.join(POSES_JSON);
    match fs::symlink_metadata(&path) {
        Ok(metadata) if !metadata.is_file() => {
            return Err(format!("{}: expected a regular file", path.display()));
        }
        Err(e) if e.kind() != ErrorKind::NotFound => {
            return Err(format!("{}: {e}", path.display()));
        }
        _ => {}
    }
    unpack(pictures, addon)?;
    fs::write(&path, poses).map_err(|e| format!("{}: {e}", path.display()))
}

/// Removes pictures an earlier run unpacked into `addon`, including top-level faces.
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

    use tempfile::TempDir;

    use super::*;

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
    fn pictures_replace_the_previous_ones() {
        let zip = release(&[
            ("aki_face.png", b"face"),
            ("art/aki_sad.png", b"sad"),
            (LICENCE, b"CC BY-SA 4.0"),
        ]);
        let addon = TempDir::new().unwrap();
        fs::create_dir(addon.path().join("art")).unwrap();
        fs::write(addon.path().join("art/aki_old.png"), b"old").unwrap();
        fs::write(addon.path().join("ankilope_face.png"), b"old").unwrap();
        fs::write(addon.path().join("share.py"), b"code").unwrap();

        unpack(&zip, addon.path()).unwrap();

        // The top-level face is left out: the add-on reads `art/`.
        let expected: BTreeMap<String, Vec<u8>> = [
            ("art/aki_sad.png", &b"sad"[..]),
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
    fn poses_json_is_copied_beside_the_code() {
        let addon = TempDir::new().unwrap();
        let pictures = release(&[(LICENCE, b"CC BY-SA 4.0")]);
        let poses = b"{\"core\": [\"face\", \"asleep\"]}";
        install(&pictures, poses, addon.path()).unwrap();
        assert_eq!(
            poses.to_vec(),
            fs::read(addon.path().join(POSES_JSON)).unwrap()
        );
    }

    #[test]
    fn a_poses_json_that_is_not_json_is_refused() {
        let addon = TempDir::new().unwrap();
        let pictures = release(&[(LICENCE, b"CC BY-SA 4.0")]);
        let face = addon.path().join("aki_face.png");
        fs::write(&face, b"face").unwrap();
        let error = install(&pictures, b"face", addon.path()).unwrap_err();
        assert!(error.contains(POSES_JSON), "{error}");
        assert!(!addon.path().join(POSES_JSON).exists());
        assert_eq!(fs::read(face).unwrap(), b"face");
    }

    #[cfg(unix)]
    #[test]
    fn a_linked_poses_file_preserves_the_original_art() {
        let addon = TempDir::new().unwrap();
        let original = TempDir::new().unwrap();
        let path = original.path().join(POSES_JSON);
        fs::write(&path, b"original").unwrap();
        std::os::unix::fs::symlink(&path, addon.path().join(POSES_JSON)).unwrap();
        let face = addon.path().join("aki_face.png");
        fs::write(&face, b"face").unwrap();
        let pictures = release(&[(LICENCE, b"CC BY-SA 4.0")]);

        let error = install(&pictures, b"{}", addon.path()).unwrap_err();
        assert!(error.contains(POSES_JSON), "{error}");
        assert_eq!(fs::read(path).unwrap(), b"original");
        assert_eq!(fs::read(face).unwrap(), b"face");
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
