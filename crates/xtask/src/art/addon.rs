//! Writes the desktop add-on's companion poses from the master PNGs in
//! `static/`: every `addon` entry of the art manifest (`art-exports.json`).
//!
//! Each pose is a 256 px square, 256-colour palette PNG with transparency;
//! an icon pose (`ankiquest_art::ICON_POSES`) is 64 px, and export adds one
//! for every companion with its master. A companion without one shows the
//! pose's fallback. Export writes every pose whose picture changed, retires
//! the file it replaces, and records each file's SHA-256 in the manifest.
//! `--check` writes nothing and fails when a pose differs from what export
//! would write, or from the hash in the manifest.
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

use ankiquest_art::{ICON_POSES, companions_with};

use super::exports::{self, Export, Exporter, Retired};
use super::{load, root, shrink, target};

/// Pose edge in pixels: the Today panel shows 96 px at up to 2x, and
/// moments 112 px.
const SIZE: u32 = 256;

/// Icon edge in pixels: an icon beside the streak number, drawn at up to
/// 32 px at 2x.
const ICON: u32 = 64;

/// The add-on's pose folder, relative to the repository root.
const FOLDER: &str = "addon/art";

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

/// Where export moves a pose it replaces: companion art is never deleted
/// (AGENTS.md, Companion art), and nothing packaged reads this folder.
const RETIRED: &str = "assets/retired";

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
        Mode::Export => export(),
        Mode::Check => check(),
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

/// Whether a manifest entry is an add-on pose or icon.
fn is_pose(export: &Export) -> bool {
    matches!(export.exporter, Exporter::Addon | Exporter::AddonIcon)
}

/// The edge, in pixels, `exporter` writes.
fn size(exporter: Exporter) -> u32 {
    match exporter {
        Exporter::Addon => SIZE,
        Exporter::AddonIcon => ICON,
    }
}

/// The pose `export` describes, made from its master.
fn render(export: &Export) -> Result<Vec<u8>, String> {
    let master = load(&root().join(&export.master))?;
    let (width, height) = target(master.width(), master.height(), size(export.exporter));
    encode(&shrink(master, width, height))
}

/// An entry for every icon master, as `<companion>_<pose>.png`.
fn icons() -> Result<Vec<Export>, String> {
    let mut icons = Vec::new();
    for pose in ICON_POSES {
        for companion in companions_with(&root().join("static"), pose)? {
            icons.push(Export {
                file: format!("{FOLDER}/{}_{pose}.png", companion.replace('-', "_")),
                master: format!("static/{companion}/{pose}.png"),
                exporter: Exporter::AddonIcon,
                sha256: String::new(),
            });
        }
    }
    Ok(icons)
}

/// Writes every pose whose picture changed, retiring the file it replaces,
/// and records each pose's hash in the manifest.
fn export() -> Result<ExitCode, String> {
    let mut manifest = exports::read()?;
    let mut retired = Vec::new();

    // List icons whose masters were added since the last export.
    for icon in icons()? {
        if !manifest
            .exports
            .iter()
            .any(|export| export.file == icon.file)
        {
            manifest.exports.push(icon);
        }
    }
    for export in manifest.exports.iter_mut().filter(|export| is_pose(export)) {
        let fresh = render(export)?;
        let path = root().join(&export.file);
        let committed = fs::read(&path).ok();
        match step(committed.as_deref(), &fresh)? {
            // Keep a committed pose that differs only by drift.
            Step::Keep => {
                let committed = committed.unwrap_or_default();
                export.sha256 = exports::sha256(&committed);
                println!("{}: current", export.file);
                continue;
            }
            Step::Add => {}

            // Move the previous picture aside before replacing it.
            Step::Replace => {
                let committed = committed.unwrap_or_default();
                retired.push(retire(export, &committed)?);
            }
        }
        save(&path, &fresh)?;
        export.sha256 = exports::sha256(&fresh);
        println!("{}: {} bytes", export.file, fresh.len());
    }
    manifest.retired.extend(retired);
    exports::write(&manifest)?;
    Ok(ExitCode::SUCCESS)
}

/// What export does with one pose.
#[derive(PartialEq, Debug)]
enum Step {
    /// No file yet: write it.
    Add,
    /// The committed file is current: leave it.
    Keep,
    /// The picture changed: retire the committed file, then write.
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

/// Keeps `bytes`, the pose `export` is about to replace, under `RETIRED`
/// with its hash in the name, and returns its manifest entry.
fn retire(export: &Export, bytes: &[u8]) -> Result<Retired, String> {
    let file = retired_path(&export.file, &exports::sha256(bytes));
    save(&root().join(&file), bytes)?;
    println!("{}: retired to {file}", export.file);
    Ok(Retired {
        file,
        why: format!(
            "Earlier {}, replaced when export-addon-art wrote a new export of {}. Unreferenced.",
            export.file, export.master
        ),
    })
}

/// Where a replaced pose goes: `addon/art/aki_happy.png` with hash
/// `0123abcd…` becomes `assets/retired/addon/art/aki_happy-0123abcd.png`.
fn retired_path(file: &str, sha256: &str) -> String {
    let (stem, extension) = file.rsplit_once('.').unwrap_or((file, "png"));
    format!("{RETIRED}/{stem}-{}.{extension}", &sha256[..8])
}

/// Writes `bytes` to `path`, creating its folder.
fn save(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if let Some(folder) = path.parent() {
        fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    }
    fs::write(path, bytes).map_err(|e| format!("{}: {e}", path.display()))
}

/// Compares every pose with a fresh export and with the manifest.
fn check() -> Result<ExitCode, String> {
    let failed = stale()?;
    for line in &failed {
        println!("{line}");
    }
    if !failed.is_empty() {
        return Ok(ExitCode::FAILURE);
    }
    println!("all add-on poses match");
    Ok(ExitCode::SUCCESS)
}

/// One line for each pose that is missing, edited or out of date.
fn stale() -> Result<Vec<String>, String> {
    let mut failed = Vec::new();
    let manifest = exports::read()?;

    // An icon master added without running export.
    for icon in icons()? {
        if !manifest
            .exports
            .iter()
            .any(|export| export.file == icon.file)
        {
            failed.push(format!("not exported: {}", icon.master));
        }
    }
    for export in manifest.exports.iter().filter(|export| is_pose(export)) {
        let path = root().join(&export.file);
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
        let failed = stale().unwrap();
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
    fn icons_are_named_after_companion_and_pose() {
        for icon in icons().unwrap() {
            assert!(icon.file.starts_with("addon/art/"), "{}", icon.file);
            assert!(icon.file.ends_with("_icon_fire.png"), "{}", icon.file);
            assert!(root().join(&icon.master).is_file(), "{}", icon.master);
        }
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
        let path = root().join("addon/art/aki_winner.png");
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

    #[test]
    fn replaced_poses_keep_their_hash() {
        assert_eq!(
            retired_path("addon/art/aki_winner.png", "0123abcd4567"),
            "assets/retired/addon/art/aki_winner-0123abcd.png"
        );
    }
}
