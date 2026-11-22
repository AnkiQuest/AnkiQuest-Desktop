//! Ports of the old `tests/test_addon_package.py` cases, plus the version
//! and archive format rules the Python script enforced without tests.

use std::io::Read;

use flate2::read::DeflateDecoder;
use tempfile::TempDir;

use super::*;

/// Local file header signature.
const LOCAL: u32 = 0x0403_4b50;

/// Central directory header signature.
const CENTRAL: u32 = 0x0201_4b50;

/// One archive member, read back from the central directory.
struct Member {
    name: String,
    bytes: Vec<u8>,
}

fn u16_at(bytes: &[u8], at: usize) -> usize {
    usize::from(u16::from_le_bytes([bytes[at], bytes[at + 1]]))
}

fn u32_at(bytes: &[u8], at: usize) -> u32 {
    u32::from_le_bytes(bytes[at..at + 4].try_into().unwrap())
}

/// Reads every member and checks its CRC, as Python's `testzip` does.
fn members(archive: &[u8]) -> Vec<Member> {
    let end = archive.len() - 22;
    let count = u16_at(archive, end + 10);
    let mut at = u32_at(archive, end + 16) as usize;
    let mut members = Vec::new();
    for _ in 0..count {
        assert_eq!(CENTRAL, u32_at(archive, at));
        let crc = u32_at(archive, at + 16);
        let size = u32_at(archive, at + 24) as usize;
        let name_len = u16_at(archive, at + 28);
        let offset = u32_at(archive, at + 42) as usize;
        let name = String::from_utf8(archive[at + 46..at + 46 + name_len].to_vec()).unwrap();

        // The local header repeats the name; the data follows it.
        assert_eq!(LOCAL, u32_at(archive, offset));
        let compressed = u32_at(archive, offset + 18) as usize;
        let start = offset + 30 + u16_at(archive, offset + 26) + u16_at(archive, offset + 28);
        let mut bytes = Vec::new();
        DeflateDecoder::new(&archive[start..start + compressed])
            .read_to_end(&mut bytes)
            .unwrap();
        assert_eq!(size, bytes.len(), "{name}");
        assert_eq!(crc, crc32fast::hash(&bytes), "{name}");
        members.push(Member { name, bytes });
        at += 46 + name_len + u16_at(archive, at + 30) + u16_at(archive, at + 32);
    }
    members
}

/// The member called `name`.
fn member<'a>(members: &'a [Member], name: &str) -> &'a [u8] {
    &members.iter().find(|m| m.name == name).unwrap().bytes
}

fn release_13() -> Version {
    Version {
        release: 13,
        nightly: 0,
        commit: "abc1234".to_owned(),
    }
}

/// Builds the real add-on for `channel` and returns its manifest.
fn real_manifest(channel: Channel) -> Value {
    let folder = TempDir::new().unwrap();
    let output = folder.path().join("addon.ankiaddon");
    build(&root().join(ADDON), &output, &release_13(), channel).unwrap();
    let members = members(&fs::read(&output).unwrap());
    serde_json::from_slice(member(&members, "manifest.json")).unwrap()
}

/// A source folder with `files`, each containing `test`.
fn source(folder: &TempDir, files: &[&str]) -> PathBuf {
    let source = folder.path().join("source");
    fs::create_dir(&source).unwrap();
    let manifest = r#"{"package": "ankiquest", "name": "ankiquest", "min_point_version": 231000}"#;
    fs::write(source.join("manifest.json"), manifest).unwrap();
    for name in files {
        let path = source.join(name);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, b"test").unwrap();
    }
    source
}

#[test]
fn github_conflicts_with_ankiweb() {
    let manifest = real_manifest(Channel::GitHub(Updates::GitHub));
    assert_eq!(json!(["414948448"]), manifest["conflicts"]);
    assert_eq!(json!("ankiquest"), manifest["package"]);
}

#[test]
fn ankiweb_conflicts_with_github() {
    let manifest = real_manifest(Channel::AnkiWeb);
    assert_eq!(json!("414948448"), manifest["package"]);
    assert_eq!(json!(["ankiquest"]), manifest["conflicts"]);
}

#[test]
fn local_state_is_excluded() {
    let folder = TempDir::new().unwrap();
    let files = [
        "__init__.py",
        "config.md",
        "art/aki.png",
        "meta.json",
        "art/meta.json",
        "tests/test_private.py",
        "__pycache__/cached.pyc",
        "art/__pycache__/cached.pyc",
        ".hidden.json",
        "debug.log",
        "build.json",
    ];
    let source = source(&folder, &files);
    let output = folder.path().join("addon.ankiaddon");
    let version = Version {
        release: 11,
        nightly: 2,
        commit: "abcdef0123456789".to_owned(),
    };
    build(&source, &output, &version, Channel::GitHub(Updates::GitHub)).unwrap();
    let first = fs::read(&output).unwrap();
    let members = members(&first);

    // Sorted names, only packaged formats, plus the three written files.
    let names: Vec<&str> = members.iter().map(|m| m.name.as_str()).collect();
    let expected = [
        "__init__.py",
        "art/aki.png",
        "build.json",
        "config.md",
        "manifest.json",
        "version.json",
    ];
    assert_eq!(expected.as_slice(), names.as_slice());

    // The installed version is shown and kept next to the add-on.
    let manifest: Value = serde_json::from_slice(member(&members, "manifest.json")).unwrap();
    assert_eq!(
        json!("addon-11 nightly 2 (abcdef0)"),
        manifest["human_version"]
    );
    assert_eq!(json!(231000), manifest["min_point_version"]);
    let installed: Value = serde_json::from_slice(member(&members, "version.json")).unwrap();
    let expected = json!({"release": 11, "nightly": 2, "commit": "abcdef0123456789"});
    assert_eq!(expected, installed);

    // The same input gives the same bytes.
    build(&source, &output, &version, Channel::GitHub(Updates::GitHub)).unwrap();
    assert_eq!(first, fs::read(&output).unwrap());
}

#[test]
fn manifest_keeps_python_layout() {
    let folder = TempDir::new().unwrap();
    let source = source(&folder, &["__init__.py"]);
    let bytes = manifest(&source, &release_13(), Channel::GitHub(Updates::GitHub)).unwrap();
    let expected = "{\n  \"package\": \"ankiquest\",\n  \"name\": \"AnkiQuest\",\n  \
\"min_point_version\": 231000,\n  \"human_version\": \"addon-13\",\n  \"conflicts\": [\n    \
\"414948448\"\n  ]\n}";
    assert_eq!(expected, String::from_utf8(bytes).unwrap());
}

#[test]
fn entry_point_is_required() {
    let folder = TempDir::new().unwrap();
    let source = source(&folder, &["config.md"]);
    let output = folder.path().join("addon.ankiaddon");
    let error = build(
        &source,
        &output,
        &release_13(),
        Channel::GitHub(Updates::GitHub),
    )
    .unwrap_err();
    assert_eq!("Missing add-on entry point", error);
}

#[cfg(unix)]
#[test]
fn symlinks_are_refused() {
    let folder = TempDir::new().unwrap();
    let source = source(&folder, &["__init__.py"]);
    std::os::unix::fs::symlink("/etc/hostname", source.join("linked.py")).unwrap();
    let output = folder.path().join("addon.ankiaddon");
    let error = build(
        &source,
        &output,
        &release_13(),
        Channel::GitHub(Updates::GitHub),
    )
    .unwrap_err();
    assert_eq!("An add-on archive cannot include symbolic links", error);
}

#[test]
fn release_tags_are_numbered() {
    assert_eq!(Ok(14), release("addon-14"));
    for tag in [
        "addon-0",
        "addon-01",
        "addon-",
        "addon-nightly",
        "v14",
        "addon-1x",
    ] {
        assert!(release(tag).is_err(), "{tag}");
    }
}

#[test]
fn tag_refs_have_no_nightly() {
    let version = version(&root(), &Source::of("refs/tags/addon-13")).unwrap();
    assert_eq!(13, version.release);
    assert_eq!(0, version.nightly);
    assert_eq!(40, version.commit.len());
    assert_eq!("addon-13", version.label());
}

#[test]
fn nightly_label_names_commit() {
    let version = Version {
        release: 11,
        nightly: 2,
        commit: "abcdef0123456789".to_owned(),
    };
    assert_eq!("addon-11 nightly 2 (abcdef0)", version.label());
}

#[test]
fn flags_are_parsed() {
    let args: Vec<String> = [
        "--ankiweb",
        "--output",
        "a.zip",
        "--ref",
        "refs/tags/addon-3",
    ]
    .map(String::from)
    .to_vec();
    let args = parse(&args).unwrap();
    assert!(matches!(args.channel, Channel::AnkiWeb));
    assert!(matches!(args.channel.updates(), Updates::None));
    assert!(matches!(args.source, Source::Tag(ref tag) if tag == "addon-3"));
    assert_eq!(PathBuf::from("a.zip"), args.output);
    assert!(parse(&[]).is_err());
    assert!(parse(&["--output".to_owned()]).is_err());
    let unknown = ["--output", "a", "--x", "y"].map(String::from);
    assert!(parse(&unknown).is_err());
}

/// The channel that `flags` (after `--output a`) choose.
fn channel_of(flags: &[&str]) -> Result<Channel, String> {
    let args: Vec<String> = ["--output", "a"]
        .iter()
        .chain(flags)
        .map(|flag| (*flag).to_owned())
        .collect();
    parse(&args).map(|args| args.channel)
}

#[test]
fn updates_are_off_unless_asked_for() {
    assert!(matches!(
        channel_of(&[]),
        Ok(Channel::GitHub(Updates::None))
    ));
    let github = channel_of(&["--updates", "github"]);
    assert!(matches!(github, Ok(Channel::GitHub(Updates::GitHub))));
    let none = channel_of(&["--updates", "none"]);
    assert!(matches!(none, Ok(Channel::GitHub(Updates::None))));
    assert!(channel_of(&["--updates", "nightly"]).is_err());
}

#[test]
fn ankiweb_never_updates_itself() {
    assert!(matches!(channel_of(&["--ankiweb"]), Ok(Channel::AnkiWeb)));
    let none = channel_of(&["--updates", "none", "--ankiweb"]);
    assert!(matches!(none, Ok(Channel::AnkiWeb)));
    assert!(channel_of(&["--ankiweb", "--updates", "github"]).is_err());
    assert!(channel_of(&["--updates", "github", "--ankiweb"]).is_err());
}

#[test]
fn archive_names_its_update_source() {
    let folder = TempDir::new().unwrap();
    let source = source(&folder, &["__init__.py"]);
    let output = folder.path().join("addon.ankiaddon");
    let cases = [
        (Channel::GitHub(Updates::GitHub), "github"),
        (Channel::GitHub(Updates::None), "none"),
        (Channel::AnkiWeb, "none"),
    ];
    for (channel, expected) in cases {
        build(&source, &output, &release_13(), channel).unwrap();
        let members = members(&fs::read(&output).unwrap());
        let written = String::from_utf8(member(&members, "build.json").to_vec()).unwrap();
        assert_eq!(format!("{{\n  \"updates\": \"{expected}\"\n}}"), written);
    }
}

#[test]
fn iso_matches_python() {
    assert_eq!("1970-01-01T00:00:00+00:00", iso(0, 0));
    assert_eq!("2026-11-14T09:30:05.000042+00:00", iso(1_794_648_605, 42));
    assert_eq!(
        "2000-02-29T23:59:59.500000+00:00",
        iso(951_868_799, 500_000)
    );
}
