//! Copies AnkiQuest-Server's shared fixtures and API examples into
//! `tests/`, where the add-on tests read them. The tests run against the
//! server's `master`; nothing here pins a commit. `server-data` clones
//! `master` (shallow and sparse) unless `--from <checkout>` names a
//! server checkout, such as a branch a server change is on.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

/// The server repository whose `master` the tests run against.
const SERVER: &str = "https://github.com/AnkiQuest/AnkiQuest-Server.git";

/// The server branch the tests run against.
const BRANCH: &str = "master";

/// Server folders and the add-on test folders they are copied to.
const PAIRS: [(&str, &str); 2] = [
    ("tests/fixtures", "tests/fixtures"),
    ("docs/api/examples", "tests/api-examples"),
];

/// Only JSON data is copied.
const JSON: &str = ".json";

/// Copies the data from `from`, or from a fresh clone of `master`.
pub(super) fn fetch(repo: &Path, from: Option<&Path>) -> Result<(), String> {
    if let Some(server) = from {
        return copy(server, repo);
    }

    // A shallow, sparse clone into a folder of its own, removed after.
    let clone = clone_dir();
    let result = clone_master(&clone).and_then(|()| copy(&clone, repo));
    fs::remove_dir_all(&clone).map_err(|e| format!("{}: {e}", clone.display()))?;
    result
}

/// A temporary folder for the clone, unique to this process.
fn clone_dir() -> PathBuf {
    std::env::temp_dir().join(format!("ankiquest-server-{}", std::process::id()))
}

/// Clones the server's `master` with only the data folders checked out.
fn clone_master(clone: &Path) -> Result<(), String> {
    let target = clone.to_str().ok_or("temporary folder is not UTF-8")?;
    git(&[
        "clone",
        "--quiet",
        "--depth",
        "1",
        "--filter=blob:none",
        "--sparse",
        "--branch",
        BRANCH,
        SERVER,
        target,
    ])?;
    let mut sparse = vec!["-C", target, "sparse-checkout", "set"];
    sparse.extend(PAIRS.iter().map(|(source, _)| *source));
    git(&sparse)?;

    // The log names the commit the tests ran against.
    let head = Command::new("git")
        .args(["-C", target, "rev-parse", "HEAD"])
        .output()
        .map_err(|e| format!("git: {e}"))?;
    println!(
        "AnkiQuest-Server {BRANCH} at {}",
        String::from_utf8_lossy(&head.stdout).trim()
    );
    Ok(())
}

/// Runs git and fails on a non-zero exit.
fn git(args: &[&str]) -> Result<(), String> {
    let status = Command::new("git")
        .args(args)
        .status()
        .map_err(|e| format!("git: {e}"))?;
    if !status.success() {
        return Err(format!("git {} failed: {status}", args.join(" ")));
    }
    Ok(())
}

/// Replaces the JSON files of each test folder with the server's.
fn copy(server: &Path, repo: &Path) -> Result<(), String> {
    // Read everything first, so a broken checkout changes nothing.
    let mut data = Vec::new();
    for (source, target) in PAIRS {
        data.push((repo.join(target), read(&server.join(source))?));
    }

    for (target, files) in data {
        clear(&target)?;
        for (name, bytes) in files {
            let file = target.join(&name);
            fs::write(&file, bytes).map_err(|e| format!("{}: {e}", file.display()))?;
        }
    }
    Ok(())
}

/// The JSON files directly in `folder`, by name; none is an error.
fn read(folder: &Path) -> Result<Vec<(String, Vec<u8>)>, String> {
    let entries = fs::read_dir(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    let mut files = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|e| format!("{}: {e}", folder.display()))?;
        let name = entry.file_name().to_string_lossy().into_owned();
        if !name.ends_with(JSON) {
            continue;
        }

        // Regular files only: a symlink could point outside the checkout.
        let kind = entry.file_type().map_err(|e| format!("{name}: {e}"))?;
        if !kind.is_file() {
            return Err(format!("{}: not a regular file", entry.path().display()));
        }
        let bytes = fs::read(entry.path()).map_err(|e| format!("{name}: {e}"))?;
        files.push((name, bytes));
    }
    if files.is_empty() {
        return Err(format!("{}: no JSON files", folder.display()));
    }
    files.sort();
    Ok(files)
}

/// Creates `folder` and removes the JSON files a previous copy left.
fn clear(folder: &Path) -> Result<(), String> {
    fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    let entries = fs::read_dir(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    for entry in entries {
        let path = entry
            .map_err(|e| format!("{}: {e}", folder.display()))?
            .path();
        if path.to_string_lossy().ends_with(JSON) {
            fs::remove_file(&path).map_err(|e| format!("{}: {e}", path.display()))?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    /// A server checkout with one fixture and one example.
    fn server() -> TempDir {
        let server = TempDir::new().unwrap();
        for (source, _) in PAIRS {
            fs::create_dir_all(server.path().join(source)).unwrap();
        }
        fs::write(server.path().join("tests/fixtures/moods.json"), "{}").unwrap();
        fs::write(server.path().join("tests/fixtures/README.md"), "notes").unwrap();
        fs::write(server.path().join("docs/api/examples/me.json"), "[]").unwrap();
        server
    }

    #[test]
    fn copies_replace_the_previous_data() {
        let server = server();
        let repo = TempDir::new().unwrap();
        let fixtures = repo.path().join("tests/fixtures");
        fs::create_dir_all(&fixtures).unwrap();
        fs::write(fixtures.join("gone.json"), "{}").unwrap();
        fs::write(fixtures.join("keep.txt"), "kept").unwrap();

        fetch(repo.path(), Some(server.path())).unwrap();

        assert_eq!(
            fs::read_to_string(fixtures.join("moods.json")).unwrap(),
            "{}"
        );
        assert!(!fixtures.join("gone.json").exists());
        assert!(!fixtures.join("README.md").exists());
        assert!(fixtures.join("keep.txt").exists());
        let example = repo.path().join("tests/api-examples/me.json");
        assert_eq!(fs::read_to_string(example).unwrap(), "[]");
    }

    #[test]
    fn a_checkout_without_data_changes_nothing() {
        let server = server();
        fs::remove_file(server.path().join("docs/api/examples/me.json")).unwrap();
        let repo = TempDir::new().unwrap();
        let fixtures = repo.path().join("tests/fixtures");
        fs::create_dir_all(&fixtures).unwrap();
        fs::write(fixtures.join("old.json"), "{}").unwrap();

        let error = fetch(repo.path(), Some(server.path())).unwrap_err();

        assert!(error.contains("no JSON files"), "{error}");
        assert!(fixtures.join("old.json").exists());
    }

    #[cfg(unix)]
    #[test]
    fn a_symlinked_file_is_refused() {
        let server = server();
        let link = server.path().join("tests/fixtures/link.json");
        std::os::unix::fs::symlink("/etc/hostname", link).unwrap();
        let repo = TempDir::new().unwrap();

        let error = fetch(repo.path(), Some(server.path())).unwrap_err();

        assert!(error.contains("not a regular file"), "{error}");
    }
}
