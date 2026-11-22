//! Builds the add-on archive for PR checks, GitHub releases and AnkiWeb:
//! `cargo run --manifest-path tools/package-addon/Cargo.toml --
//! --output <file> [--ankiweb] [--updates github|none] [--ref <ref>]
//! [--metadata <file>]`.
//!
//! The archive is reproducible: the same commit and channel always give
//! the same bytes. The GitHub and AnkiWeb builds differ only in the
//! manifest's package ID and conflicts and in `build.json`, which names
//! where the add-on looks for updates.
//!
//! Before packaging, it writes the add-on's companion pictures into
//! `addon/` with AnkiQuest-Art's `art-export`, from the `art` submodule.
//! Linux builds are canonical: another platform may encode a few pixels
//! of a picture differently.

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Value, json};

mod json;
mod zip;

use json::Object;

/// The published AnkiWeb listing's package ID.
const ANKIWEB_ID: &str = "414948448";

/// The add-on's folder, relative to the repository root.
const ADDON: &str = "addon";

/// Release tags are `addon-<number>`.
const TAG_PREFIX: &str = "addon-";

/// A pushed tag's ref starts with this.
const TAGS_REF: &str = "refs/tags/";

/// Path parts that are never packaged: caches, tests and files the
/// installed add-on writes or the build replaces.
const EXCLUDED: &[&str] = &[
    "__pycache__",
    "tests",
    "meta.json",
    "version.json",
    "manifest.json",
    "build.json",
];

/// File extensions that are packaged.
const FORMATS: &[&str] = &[
    "py", "json", "png", "md", "js", "html", "css", "svg", "wasm",
];

/// The add-on's entry point, which Anki imports.
const ENTRY: &str = "__init__.py";

/// The build settings the add-on reads, written as `build.json`.
const BUILD: &str = "build.json";

/// The AnkiQuest-Art submodule, relative to the repository root.
const ART: &str = "art";

/// AnkiQuest-Art's exporter, relative to the submodule.
const EXPORTER: &str = "tools/art-export/Cargo.toml";

/// The folder of the add-on's poses, which the exporter writes.
const POSES: &str = "art";

/// The exporter writes each face beside the code as `<companion>_face.png`.
const FACE_SUFFIX: &str = "_face.png";

/// Anki-tan's licence in the submodule, and where the archive carries it.
const ANKI_TAN_LICENCE: (&str, &str) = ("anki-tan/LICENSE", "art/LICENSE-Anki-tan.md");

/// Where the archive is published.
#[derive(Clone, Copy)]
enum Channel {
    /// GitHub releases, PR artifacts and local builds.
    GitHub(Updates),
    /// The AnkiWeb listing, which updates add-ons itself.
    AnkiWeb,
}

/// Where the installed add-on looks for newer builds.
#[derive(Clone, Copy)]
enum Updates {
    /// `addon-<n>` releases and `addon-nightly` on GitHub.
    GitHub,
    /// Nowhere: the add-on never checks, downloads or installs updates.
    None,
}

/// Where the version comes from.
enum Source {
    /// A pushed release tag: that release, no nightly count.
    Tag(String),
    /// Any other ref: the latest release tag plus the commits since.
    Describe,
}

/// The version written into `version.json` and the manifest.
#[derive(Debug, PartialEq)]
struct Version {
    release: u64,
    nightly: u64,
    commit: String,
}

/// Parsed command-line flags.
struct Args {
    output: PathBuf,
    channel: Channel,
    source: Source,
    metadata: Option<PathBuf>,
}

/// Runs `--output <file> [--ankiweb] [--updates github|none] [--ref <ref>]
/// [--metadata <file>]`.
fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    match package(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("package-addon: {error}");
            ExitCode::FAILURE
        }
    }
}

/// Builds the archive and, if asked, the metadata file.
fn package(args: &[String]) -> Result<(), String> {
    let args = parse(args)?;
    let repo = root();
    let version = version(&repo, &args.source)?;
    export_art(&repo)?;
    build(&repo.join(ADDON), &args.output, &version, args.channel)?;

    // The nightly release publishes this for the add-on's update check.
    if let Some(metadata) = &args.metadata {
        let mut object = version.object();
        object.set("built_at", Value::String(now()));
        write(metadata, format!("{}\n", object.pretty()).as_bytes())?;
    }

    println!(
        "{{\"release\": {}, \"nightly\": {}, \"commit\": \"{}\"}}",
        version.release, version.nightly, version.commit
    );
    Ok(())
}

/// The repository root: this crate is `tools/package-addon`.
fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// Reads the flags; `--output` is required. Updates are off unless
/// `--updates github` asks for them, and never on with `--ankiweb`.
fn parse(args: &[String]) -> Result<Args, String> {
    let mut output = None;
    let mut ankiweb = false;
    let mut updates = None;
    let mut source = Source::Describe;
    let mut metadata = None;
    let mut iter = args.iter();
    while let Some(flag) = iter.next() {
        if flag == "--ankiweb" {
            ankiweb = true;
            continue;
        }
        let value = iter.next().ok_or(format!("{flag} needs a value"))?;
        match flag.as_str() {
            "--output" => output = Some(PathBuf::from(value)),
            "--updates" => updates = Some(Updates::of(value)?),
            "--ref" => source = Source::of(value),
            "--metadata" => metadata = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown argument {flag}")),
        }
    }
    let output = output.ok_or("--output is required")?;

    // AnkiWeb replaces the add-on itself; a second updater would fight it.
    let channel = match (ankiweb, updates) {
        (true, Some(Updates::GitHub)) => {
            return Err("--ankiweb builds leave updates to AnkiWeb".to_owned());
        }
        (true, _) => Channel::AnkiWeb,
        (false, updates) => Channel::GitHub(updates.unwrap_or(Updates::None)),
    };
    Ok(Args {
        output,
        channel,
        source,
        metadata,
    })
}

impl Channel {
    /// Where this build looks for updates.
    fn updates(self) -> Updates {
        match self {
            Self::GitHub(updates) => updates,
            Self::AnkiWeb => Updates::None,
        }
    }
}

impl Updates {
    /// The `--updates` value.
    fn of(value: &str) -> Result<Self, String> {
        match value {
            "github" => Ok(Self::GitHub),
            "none" => Ok(Self::None),
            _ => Err(format!("--updates is github or none, not {value}")),
        }
    }

    /// The name in `build.json`, as the add-on's `UpdateSource` reads it.
    fn name(self) -> &'static str {
        match self {
            Self::GitHub => "github",
            Self::None => "none",
        }
    }
}

impl Source {
    /// A tag ref names its release; anything else, an empty ref included,
    /// is described from history.
    fn of(reference: &str) -> Self {
        match reference.strip_prefix(TAGS_REF) {
            Some(tag) => Self::Tag(tag.to_owned()),
            None => Self::Describe,
        }
    }
}

impl Version {
    /// `addon-13`, or `addon-13 nightly 2 (abcdef0)` after the release.
    fn label(&self) -> String {
        let label = format!("{TAG_PREFIX}{}", self.release);
        if self.nightly == 0 {
            return label;
        }
        let short: String = self.commit.chars().take(7).collect();
        format!("{label} nightly {} ({short})", self.nightly)
    }

    /// The fields in `version.json` order.
    fn object(&self) -> Object {
        let mut object = Object::default();
        object.set("release", json!(self.release));
        object.set("nightly", json!(self.nightly));
        object.set("commit", json!(self.commit));
        object
    }
}

/// The version of HEAD in `repo`.
fn version(repo: &Path, source: &Source) -> Result<Version, String> {
    let commit = git(repo, &["rev-parse", "HEAD"])?;
    let pattern = format!("{TAG_PREFIX}[0-9]*");

    // A tag build is that release; a branch build counts commits since one.
    let (tag, nightly) = match source {
        Source::Tag(tag) => (tag.clone(), 0),
        Source::Describe => {
            let args = [
                "describe",
                "--tags",
                "--match",
                &pattern,
                "--abbrev=0",
                "HEAD",
            ];
            let tag = git(repo, &args)?;
            let range = format!("{tag}..HEAD");
            let count = git(repo, &["rev-list", "--count", "--first-parent", &range])?;
            let count = count
                .parse()
                .map_err(|e| format!("commit count {count}: {e}"))?;
            (tag, count)
        }
    };
    Ok(Version {
        release: release(&tag)?,
        nightly,
        commit,
    })
}

/// The number in an `addon-<number>` tag.
fn release(tag: &str) -> Result<u64, String> {
    let error = || "Expected an addon-<number> release tag".to_owned();
    let digits = tag.strip_prefix(TAG_PREFIX).ok_or_else(error)?;
    let valid = digits.chars().all(|c| c.is_ascii_digit()) && !digits.starts_with('0');
    if !valid || digits.is_empty() {
        return Err(error());
    }
    digits.parse().map_err(|_| error())
}

/// Runs git in `repo` and returns its trimmed output.
fn git(repo: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .map_err(|e| format!("git: {e}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("git {}: {}", args.join(" "), stderr.trim()));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

/// Writes the add-on's pictures from the AnkiQuest-Art submodule into
/// `addon/`, replacing what an earlier run left there, so the archive
/// never carries a picture the exporter no longer writes.
fn export_art(repo: &Path) -> Result<(), String> {
    let art = repo.join(ART);
    if !art.join("manifest.json").is_file() {
        return Err("art/ is empty: run git submodule update --init".to_owned());
    }
    let addon = repo.join(ADDON);
    clear_art(&addon)?;

    // CARGO is set when this runs under cargo; the exporter builds with it.
    let cargo = env::var_os("CARGO").unwrap_or_else(|| "cargo".into());
    let status = Command::new(cargo)
        .args(["run", "--locked", "--release", "--quiet", "--manifest-path"])
        .arg(art.join(EXPORTER))
        .args(["--", "addon"])
        .arg(&addon)
        .stdout(Stdio::null())
        .status()
        .map_err(|e| format!("art-export: {e}"))?;
    if !status.success() {
        return Err(format!("art-export: {status}"));
    }

    // Anki-tan's pictures are CC BY-SA 4.0 and travel with her licence.
    let (licence, copy) = ANKI_TAN_LICENCE;
    let bytes = fs::read(art.join(licence)).map_err(|e| format!("{licence}: {e}"))?;
    write(&addon.join(copy), &bytes)
}

/// Removes the pictures an earlier export wrote into `addon`.
fn clear_art(addon: &Path) -> Result<(), String> {
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

/// Writes the archive of `source` for `channel` to `output`.
fn build(source: &Path, output: &Path, version: &Version, channel: Channel) -> Result<(), String> {
    let mut files = collect(source)?;
    if !files.contains_key(ENTRY) {
        return Err("Missing add-on entry point".to_owned());
    }
    files.insert(
        "manifest.json".to_owned(),
        manifest(source, version, channel)?,
    );
    files.insert(
        "version.json".to_owned(),
        version.object().pretty().into_bytes(),
    );

    // The add-on reads this once to decide whether it may update itself.
    let mut settings = Object::default();
    settings.set("updates", json!(channel.updates().name()));
    files.insert(BUILD.to_owned(), settings.pretty().into_bytes());
    write(output, &zip::archive(&files)?)
}

/// The source manifest with the published name, version and channel.
fn manifest(source: &Path, version: &Version, channel: Channel) -> Result<Vec<u8>, String> {
    let path = source.join("manifest.json");
    let text = fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut manifest: Object =
        serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
    manifest.set("name", json!("AnkiQuest"));
    manifest.set("human_version", json!(version.label()));

    // Each channel conflicts with the other, never itself on a later update.
    let github = manifest
        .get("package")
        .cloned()
        .ok_or("manifest.json has no package")?;
    let (package, conflict) = match channel {
        Channel::GitHub(_) => (github, json!(ANKIWEB_ID)),
        Channel::AnkiWeb => (json!(ANKIWEB_ID), github),
    };
    manifest.set("package", package);
    manifest.set("conflicts", json!([conflict]));
    Ok(manifest.pretty().into_bytes())
}

/// Every packaged file under `source`, by its archive name.
fn collect(source: &Path) -> Result<BTreeMap<String, Vec<u8>>, String> {
    let mut files = BTreeMap::new();
    let mut pending = vec![source.to_path_buf()];
    while let Some(folder) = pending.pop() {
        let entries = fs::read_dir(&folder).map_err(|e| format!("{}: {e}", folder.display()))?;
        for entry in entries {
            let path = entry.map_err(|e| e.to_string())?.path();
            let kind = fs::symlink_metadata(&path)
                .map_err(|e| e.to_string())?
                .file_type();

            // A link could pull files from outside the add-on into the archive.
            if kind.is_symlink() {
                return Err("An add-on archive cannot include symbolic links".to_owned());
            }
            if kind.is_dir() {
                pending.push(path);
                continue;
            }
            let relative = path.strip_prefix(source).map_err(|e| e.to_string())?;
            if !kind.is_file() || !packaged(relative) {
                continue;
            }
            let name = archive_name(relative)?;
            let bytes = fs::read(&path).map_err(|e| format!("{}: {e}", path.display()))?;
            files.insert(name, bytes);
        }
    }
    Ok(files)
}

/// Whether a file, relative to the add-on, belongs in the archive.
fn packaged(relative: &Path) -> bool {
    let hidden = relative.iter().any(|part| {
        let part = part.to_string_lossy();
        EXCLUDED.contains(&part.as_ref()) || part.starts_with('.')
    });
    if hidden {
        return false;
    }
    relative
        .extension()
        .is_some_and(|ext| FORMATS.contains(&ext.to_string_lossy().as_ref()))
}

/// The archive name: the relative path with `/` separators.
fn archive_name(relative: &Path) -> Result<String, String> {
    let parts: Option<Vec<&str>> = relative.iter().map(|part| part.to_str()).collect();
    let parts = parts.ok_or(format!("{} is not UTF-8", relative.display()))?;
    Ok(parts.join("/"))
}

/// Writes `bytes` to `path`.
fn write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    fs::write(path, bytes).map_err(|e| format!("{}: {e}", path.display()))
}

/// The current UTC time as Python's `datetime.isoformat()` writes it.
fn now() -> String {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    iso(elapsed.as_secs(), elapsed.subsec_micros())
}

/// `2026-11-14T09:30:00.123456+00:00`; the fraction is left out when zero.
fn iso(seconds: u64, micros: u32) -> String {
    const DAY: u64 = 86_400;
    let (year, month, day) = civil(seconds / DAY);
    let time = seconds % DAY;
    let (hour, minute, second) = (time / 3600, time / 60 % 60, time % 60);
    let fraction = match micros {
        0 => String::new(),
        _ => format!(".{micros:06}"),
    };
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}{fraction}+00:00")
}

/// The proleptic Gregorian date of a day count since 1970-01-01
/// (Howard Hinnant's `civil_from_days`).
fn civil(days: u64) -> (u64, u64, u64) {
    let z = days + 719_468;
    let era = z / 146_097;
    let doe = z % 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + u64::from(month <= 2);
    (year, month, day)
}

#[cfg(test)]
mod tests;
