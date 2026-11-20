//! Writes the desktop add-on's companion poses from the master PNGs in
//! `static/`: every `addon` entry of the art manifest (`art-exports.json`).
//!
//! Each pose is a 256 px square, 256-colour palette PNG with transparency.
//! Export overwrites every pose whose picture changed, deletes every pose
//! whose master is gone (removed or renamed) together with its manifest
//! entry, and records each file's SHA-256. `--check` writes nothing and
//! fails when a pose differs from what export would write, from the hash
//! in the manifest, or has no master.
//!
//! Linux exports are canonical. Another platform, or a new quantiser
//! version, maps a few colours to other palette entries: a few hundred
//! pixels move far while the mean barely moves. Export and check therefore
//! treat a pose as current when it is `close` to a fresh render, so a
//! clean checkout passes everywhere and export leaves the committed files
//! alone.

use std::fs;
use std::path::Path;
use std::process::ExitCode;

use color_quant::NeuQuant;
use image::RgbaImage;

use super::exports::{self, Export, Exporter, MANIFEST};
use super::{load, root, shrink, target};

/// Pose edge in pixels: the Today panel shows 96 px at up to 2x, and
/// moments 112 px.
const SIZE: u32 = 256;

/// Palette size, the most an indexed PNG holds.
const COLOURS: usize = 256;

/// NeuQuant sampling factor: 1 looks at every pixel, the slowest and best.
const SAMPLING: i32 = 1;

/// Largest mean channel difference, out of 255, between a committed pose
/// and a fresh export: drift moves a few palette entries, a different
/// picture moves far more.
const MEAN_TOLERANCE: f64 = 0.5;

/// A pixel has drifted when one of its channels moves more than this.
const DRIFT: u8 = 16;

/// Largest share of drifted pixels. Drift from Windows/MSVC and from
/// color_quant 2 moves at most 0.4% of a pose; no single pixel is bounded,
/// since one swapped palette entry can move a pixel by 150.
const DRIFTED_SHARE: f64 = 0.01;

/// What the command does.
#[derive(PartialEq)]
enum Mode {
    Export,
    Check,
}

/// Runs the exporter: `[--check]`.
pub fn run(args: &[String]) -> ExitCode {
    let mode = match args {
        [] => Mode::Export,
        [flag] if flag == "--check" => Mode::Check,
        _ => return usage(),
    };
    let result = match mode {
        Mode::Export => export(&root()),
        Mode::Check => check(&root()),
    };
    match result {
        Ok(code) => code,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}

/// Prints the usage text and fails.
fn usage() -> ExitCode {
    eprintln!("usage: xtask export-addon-art [--check]");
    ExitCode::FAILURE
}

/// Whether a manifest entry is an add-on pose.
fn is_pose(export: &Export) -> bool {
    export.exporter == Exporter::Addon
}

/// Whether the master of `export` exists.
fn has_master(export: &Export) -> bool {
    root().join(&export.master).is_file()
}

/// The pose `export` describes, made from its master.
fn render(export: &Export) -> Result<Vec<u8>, String> {
    let master = load(&root().join(&export.master))?;
    let (width, height) = target(master.width(), master.height(), SIZE);
    encode(&shrink(master, width, height))
}

/// Writes every pose whose picture changed into `checkout`, deletes every
/// pose whose master is gone, and records each pose's hash in the
/// checkout's manifest.
fn export(checkout: &Path) -> Result<ExitCode, String> {
    let manifest_path = checkout.join(MANIFEST);
    let mut manifest = exports::read_at(&manifest_path)?;

    // A copy whose master was removed or renamed goes with its entry.
    for export in manifest.exports.iter().filter(|e| !has_master(e)) {
        remove(&checkout.join(&export.file))?;
        println!("{}: deleted, {} is gone", export.file, export.master);
    }
    manifest.exports.retain(has_master);

    for export in manifest.exports.iter_mut().filter(|export| is_pose(export)) {
        let fresh = render(export)?;
        let path = checkout.join(&export.file);
        let committed = fs::read(&path).ok();

        // Keep a committed pose that differs only by drift.
        if step(committed.as_deref(), &fresh)? == Step::Keep {
            export.sha256 = exports::sha256(&committed.unwrap_or_default());
            println!("{}: current", export.file);
            continue;
        }
        save(&path, &fresh)?;
        export.sha256 = exports::sha256(&fresh);
        println!("{}: {} bytes", export.file, fresh.len());
    }
    exports::write(&manifest_path, &manifest)?;
    Ok(ExitCode::SUCCESS)
}

/// What export does with one pose.
#[derive(PartialEq, Debug)]
enum Step {
    /// No file yet: write it.
    Add,
    /// The committed file is current: leave it.
    Keep,
    /// The picture changed: overwrite the committed file.
    Replace,
}

/// What export does with a pose, given the committed file and a fresh render.
fn step(committed: Option<&[u8]>, fresh: &[u8]) -> Result<Step, String> {
    let Some(committed) = committed else {
        return Ok(Step::Add);
    };
    if committed == fresh || close(fresh, committed)? {
        return Ok(Step::Keep);
    }
    Ok(Step::Replace)
}

/// Writes `bytes` to `path`, creating its folder.
fn save(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if let Some(folder) = path.parent() {
        fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    }
    fs::write(path, bytes).map_err(|e| format!("{}: {e}", path.display()))
}

/// Deletes `path`; a file already gone is fine.
fn remove(path: &Path) -> Result<(), String> {
    match fs::remove_file(path) {
        Err(e) if e.kind() != std::io::ErrorKind::NotFound => {
            Err(format!("{}: {e}", path.display()))
        }
        _ => Ok(()),
    }
}

/// Compares every pose in `checkout` with a fresh export and with the
/// checkout's manifest.
fn check(checkout: &Path) -> Result<ExitCode, String> {
    let failed = stale(checkout)?;
    for line in &failed {
        println!("{line}");
    }
    if !failed.is_empty() {
        return Ok(ExitCode::FAILURE);
    }
    println!("all add-on poses match");
    Ok(ExitCode::SUCCESS)
}

/// One line for each pose that is missing, edited, out of date or without
/// a master.
fn stale(checkout: &Path) -> Result<Vec<String>, String> {
    let mut failed = Vec::new();
    for export in exports::read_at(&checkout.join(MANIFEST))?
        .exports
        .iter()
        .filter(|export| is_pose(export))
    {
        if !has_master(export) {
            failed.push(format!("{}: {} is gone", export.file, export.master));
            continue;
        }
        let path = checkout.join(&export.file);
        let Ok(committed) = fs::read(&path) else {
            failed.push(format!("missing: {}", export.file));
            continue;
        };
        if exports::sha256(&committed) != export.sha256 {
            failed.push(format!("{}: not the file export wrote", export.file));
            continue;
        }
        let fresh = render(export)?;
        if fresh != committed && !close(&fresh, &committed)? {
            failed.push(format!("{}: differs from {}", export.file, export.master));
        }
    }
    Ok(failed)
}

/// Whether two PNGs show the same picture up to drift: a small mean
/// difference and few drifted pixels.
fn close(a: &[u8], b: &[u8]) -> Result<bool, String> {
    let decode = |bytes: &[u8]| {
        image::load_from_memory(bytes)
            .map(|image| image.into_rgba8())
            .map_err(|e| e.to_string())
    };
    let (a, b) = (decode(a)?, decode(b)?);
    if a.dimensions() != b.dimensions() {
        return Ok(false);
    }
    let differences: Vec<u8> = a
        .as_raw()
        .iter()
        .zip(b.as_raw())
        .map(|(x, y)| x.abs_diff(*y))
        .collect();

    // Mean over every channel, share over pixels.
    let total: f64 = differences.iter().map(|&d| f64::from(d)).sum();
    let mean = total / differences.len().max(1) as f64;
    let (pixels, _) = differences.as_chunks::<4>();
    let drifted = pixels
        .iter()
        .filter(|pixel| pixel.iter().any(|&d| d > DRIFT))
        .count();
    let share = drifted as f64 / pixels.len().max(1) as f64;
    Ok(mean <= MEAN_TOLERANCE && share <= DRIFTED_SHARE)
}

/// Encodes `image` as an indexed PNG with a 256-colour RGBA palette.
fn encode(image: &RgbaImage) -> Result<Vec<u8>, String> {
    let quant = NeuQuant::new(SAMPLING, COLOURS, image.as_raw());
    let (pixels, _) = image.as_raw().as_chunks::<4>();
    let indices: Vec<u8> = pixels
        .iter()
        .map(|pixel| quant.index_of(pixel) as u8)
        .collect();

    // Split the RGBA palette into PNG's colour and transparency chunks.
    let rgba = quant.color_map_rgba();
    let (palette, _) = rgba.as_chunks::<4>();
    let colours: Vec<u8> = palette.iter().flat_map(|&[r, g, b, _]| [r, g, b]).collect();
    let alpha: Vec<u8> = palette.iter().map(|&[_, _, _, a]| a).collect();

    let mut bytes = Vec::new();
    let mut encoder = png::Encoder::new(&mut bytes, image.width(), image.height());
    encoder.set_color(png::ColorType::Indexed);
    encoder.set_depth(png::BitDepth::Eight);
    encoder.set_palette(colours);
    encoder.set_trns(alpha);
    encoder.set_compression(png::Compression::High);
    let mut writer = encoder.write_header().map_err(|e| e.to_string())?;
    writer
        .write_image_data(&indices)
        .map_err(|e| e.to_string())?;
    writer.finish().map_err(|e| e.to_string())?;
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_addon_pose_is_current() {
        let failed = stale(&root()).unwrap();
        assert!(
            failed.is_empty(),
            "run `cargo run -p ankiquest-xtask -- export-addon-art`: {failed:?}"
        );
    }

    #[test]
    fn poses_are_listed_once() {
        let manifest = exports::read().unwrap();
        let mut files: Vec<_> = manifest.exports.iter().map(|e| &e.file).collect();
        files.sort_unstable();
        files.dedup();
        assert_eq!(manifest.exports.len(), files.len());
    }

    #[test]
    fn a_changed_picture_is_not_close() {
        let red = RgbaImage::from_pixel(8, 8, image::Rgba([255, 0, 0, 255]));
        let blue = RgbaImage::from_pixel(8, 8, image::Rgba([0, 0, 255, 255]));
        let (red, blue) = (encode(&red).unwrap(), encode(&blue).unwrap());
        assert!(close(&red, &red).unwrap());
        assert!(!close(&red, &blue).unwrap());
    }

    /// `image` as a plain RGBA PNG.
    fn png(image: &RgbaImage) -> Vec<u8> {
        let mut bytes = std::io::Cursor::new(Vec::new());
        image.write_to(&mut bytes, image::ImageFormat::Png).unwrap();
        bytes.into_inner()
    }

    /// The committed Aki winner pose, decoded.
    fn winner() -> RgbaImage {
        let path = root().join(WINNER);
        image::open(path).unwrap().into_rgba8()
    }

    /// The drift reported on Windows/MSVC for aki_winner.png: one pixel
    /// off by 64, everything else the same.
    #[test]
    fn one_drifted_pixel_is_close() {
        let committed = winner();
        let mut fresh = committed.clone();
        fresh.put_pixel(146, 160, image::Rgba([116, 98, 114, 253]));
        assert!(close(&png(&fresh), &png(&committed)).unwrap());
        assert_eq!(step(Some(&png(&committed)), &png(&fresh)), Ok(Step::Keep));
    }

    /// A 40 px patch painted over the pose is an edit, not drift.
    #[test]
    fn a_painted_patch_is_not_close() {
        let committed = winner();
        let mut edited = committed.clone();
        for (x, y, pixel) in edited.enumerate_pixels_mut() {
            if (100..140).contains(&x) && (100..140).contains(&y) {
                *pixel = image::Rgba([255, 0, 255, 255]);
            }
        }
        assert!(!close(&png(&edited), &png(&committed)).unwrap());
        assert_eq!(
            step(Some(&png(&committed)), &png(&edited)),
            Ok(Step::Replace)
        );
    }

    #[test]
    fn a_missing_pose_is_added() {
        assert_eq!(step(None, &png(&winner())), Ok(Step::Add));
    }

    /// The add-on's winner pose.
    const WINNER: &str = "addon/art/aki_winner.png";

    /// A pose under its old name, whose master was renamed.
    const SLEEPING: &str = "addon/art/aki_sleeping.png";

    /// A master that no longer exists.
    const GONE: &str = "static/aki/sleeping-renamed.png";

    /// A temporary checkout whose manifest lists only the winner pose,
    /// before its first export.
    fn checkout() -> tempfile::TempDir {
        let checkout = tempfile::tempdir().unwrap();
        let path = checkout.path().join(MANIFEST);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        let winner = Export {
            file: WINNER.into(),
            master: "static/aki/winner.png".into(),
            exporter: Exporter::Addon,
            sha256: String::new(),
        };
        let manifest = exports::Manifest {
            exports: vec![winner],
        };
        exports::write(&path, &manifest).unwrap();
        checkout
    }

    /// The names of the files in `folder`, sorted.
    fn names(folder: &Path) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(folder)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    }

    #[test]
    fn export_writes_checks_and_overwrites() {
        // A fresh checkout misses the pose; export writes it.
        let checkout = checkout();
        let checkout = checkout.path();
        assert_eq!(vec![format!("missing: {WINNER}")], stale(checkout).unwrap());
        assert_eq!(ExitCode::SUCCESS, export(checkout).unwrap());
        assert!(stale(checkout).unwrap().is_empty());
        let path = checkout.join(WINNER);
        let written = fs::read(&path).unwrap();

        // An edited pose fails the check.
        let blue = RgbaImage::from_pixel(SIZE, SIZE, image::Rgba([0, 0, 255, 255]));
        fs::write(&path, encode(&blue).unwrap()).unwrap();
        assert_eq!(
            vec![format!("{WINNER}: not the file export wrote")],
            stale(checkout).unwrap()
        );

        // Export overwrites it in place and keeps no other file.
        assert_eq!(ExitCode::SUCCESS, export(checkout).unwrap());
        assert!(stale(checkout).unwrap().is_empty());
        assert_eq!(written, fs::read(&path).unwrap());
        assert_eq!(vec!["addon", "crates"], names(checkout));
        assert_eq!(vec!["aki_winner.png"], names(&checkout.join("addon/art")));
    }

    #[test]
    fn export_deletes_a_pose_whose_master_is_gone() {
        // The winner pose is current; a second pose names a master that
        // was renamed.
        let checkout = checkout();
        let checkout = checkout.path();
        assert_eq!(ExitCode::SUCCESS, export(checkout).unwrap());
        let gone = Export {
            file: SLEEPING.into(),
            master: GONE.into(),
            exporter: Exporter::Addon,
            sha256: String::new(),
        };
        fs::write(checkout.join(&gone.file), b"old copy").unwrap();
        let manifest_path = checkout.join(MANIFEST);
        let mut manifest = exports::read_at(&manifest_path).unwrap();
        manifest.exports.push(gone);
        exports::write(&manifest_path, &manifest).unwrap();

        // Check fails on it; export deletes the file and drops the entry.
        assert_eq!(
            vec![format!("{SLEEPING}: {GONE} is gone")],
            stale(checkout).unwrap()
        );
        assert_eq!(ExitCode::SUCCESS, export(checkout).unwrap());
        assert!(stale(checkout).unwrap().is_empty());
        assert!(!checkout.join(SLEEPING).exists());
        assert!(checkout.join(WINNER).is_file());
        let files: Vec<String> = exports::read_at(&manifest_path)
            .unwrap()
            .exports
            .into_iter()
            .map(|export| export.file)
            .collect();
        assert_eq!(vec![WINNER.to_string()], files);
    }
}
