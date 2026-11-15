//! Writes the desktop add-on's companion poses into `addon/art` from the
//! master PNGs in `static/`.
//!
//! Each pose is a 256 px square, 256-colour palette PNG with transparency.
//! Export writes only the poses that are missing, because the existing ones
//! were tuned by hand; `--replace` writes them all. `--check` writes nothing
//! and fails when a pose is missing or has a different pixel size.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use color_quant::NeuQuant;
use image::RgbaImage;

use super::{load, png_size, root, shrink, target};

/// The add-on's pose folder, relative to the repository root.
const FOLDER: &str = "addon/art";

/// Pose edge in pixels: the Today panel shows 96 px at up to 2x, and
/// moments 112 px.
const SIZE: u32 = 256;

/// Palette size, the most an indexed PNG holds.
const COLOURS: usize = 256;

/// NeuQuant sampling factor: 1 looks at every pixel, the slowest and best.
const SAMPLING: i32 = 1;

/// One pose: its file name without extension and its master PNG.
struct Pose {
    name: &'static str,
    source: &'static str,
}

/// A pose by name and master.
const fn pose(name: &'static str, source: &'static str) -> Pose {
    Pose { name, source }
}

/// Every pose the add-on shows, as Android names its drawables.
const POSES: &[Pose] = &[
    pose("aki_face", "static/aki/face.png"),
    pose("aki_sad", "static/aki/sad.png"),
    pose("aki_hopeful", "static/aki/hopeful.png"),
    pose("aki_frozen", "static/aki/frozen.png"),
    pose("aki_neglected", "static/aki/neglected.png"),
    pose(
        "anki_tan_frozen",
        "static/anki-tan/generated/frozen-full.png",
    ),
    pose(
        "anki_tan_chibi_frozen",
        "static/anki-tan/generated/frozen-chibi.png",
    ),
    pose("aki_welcome", "static/aki/welcome.png"),
    pose("aki_review", "static/aki/review.png"),
    pose("aki_celebrate", "static/aki/celebrate.png"),
    pose("aki_winner", "static/aki/winner.png"),
    pose("aki_streak", "static/aki/streak.png"),
    pose("aki_streak_hot", "static/aki/streak_hot.png"),
    pose("aki_streak_blazing", "static/aki/streak_blazing.png"),
    pose("aki_streak_legend", "static/aki/streak_legend.png"),
    pose("aki_streak_milestone", "static/aki/streak_milestone.png"),
    pose("aki_freeze", "static/aki/freeze.png"),
    pose("aki_freeze_used", "static/aki/freeze_used.png"),
    pose("aki_sleeping", "static/aki/sleeping.png"),
    pose("aki_at_risk", "static/aki/at_risk.png"),
    pose("ankilope_face", "static/ankilope/face.png"),
    pose("ankilope_sad", "static/ankilope/sad.png"),
    pose("ankilope_hopeful", "static/ankilope/hopeful.png"),
    pose("ankilope_frozen", "static/ankilope/frozen.png"),
    pose("ankilope_sleeping", "static/ankilope/sleeping.png"),
    pose("ankilope_neglected", "static/ankilope/neglected.png"),
    pose("ankilope_welcome", "static/ankilope/welcome.png"),
    pose("ankilope_study", "static/ankilope/study.png"),
    pose("ankilope_celebrate", "static/ankilope/celebrate.png"),
];

/// What the command does.
#[derive(PartialEq)]
enum Mode {
    Export,
    Check,
}

/// What export does with a pose that is already there.
#[derive(PartialEq)]
enum Existing {
    Keep,
    Replace,
}

/// Runs the exporter: `[--check | --replace]`.
pub fn run(args: &[String]) -> ExitCode {
    let mut mode = Mode::Export;
    let mut existing = Existing::Keep;
    for arg in args {
        match arg.as_str() {
            "--check" => mode = Mode::Check,
            "--replace" => existing = Existing::Replace,
            _ => return usage(),
        }
    }
    if mode == Mode::Check && existing == Existing::Replace {
        return usage();
    }

    let folder = root().join(FOLDER);
    let result = match mode {
        Mode::Export => export(&folder, &existing),
        Mode::Check => check(&folder),
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
    eprintln!("usage: xtask export-addon-art [--check | --replace]");
    ExitCode::FAILURE
}

/// The pose's file in `folder`.
fn file(folder: &Path, name: &str) -> PathBuf {
    folder.join(format!("{name}.png"))
}

/// Writes the poses into `folder`.
fn export(folder: &Path, existing: &Existing) -> Result<ExitCode, String> {
    fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
    for pose in POSES {
        let path = file(folder, pose.name);
        if *existing == Existing::Keep && path.exists() {
            continue;
        }

        // Downscale, reduce to a palette and write.
        let master = load(&root().join(pose.source))?;
        let (width, height) = target(master.width(), master.height(), SIZE);
        let bytes = encode(&shrink(master, width, height))?;
        fs::write(&path, &bytes).map_err(|e| format!("{}: {e}", path.display()))?;
        println!(
            "{FOLDER}/{}.png: {width}x{height}, {} bytes",
            pose.name,
            bytes.len()
        );
    }
    Ok(ExitCode::SUCCESS)
}

/// Compares every pose's pixel size with what export would write.
fn check(folder: &Path) -> Result<ExitCode, String> {
    let failed = missing(folder)?;
    for line in &failed {
        println!("{line}");
    }
    if !failed.is_empty() {
        return Ok(ExitCode::FAILURE);
    }
    println!("all {} add-on poses match", POSES.len());
    Ok(ExitCode::SUCCESS)
}

/// One line for each pose in `folder` that is missing or has the wrong size.
fn missing(folder: &Path) -> Result<Vec<String>, String> {
    let mut failed = Vec::new();
    for pose in POSES {
        let (width, height) = png_size(&root().join(pose.source))?;
        let expected = target(width, height, SIZE);
        let path = file(folder, pose.name);
        if !path.exists() {
            failed.push(format!("missing: {FOLDER}/{}.png", pose.name));
            continue;
        }
        let actual = png_size(&path)?;
        if actual != expected {
            let ((aw, ah), (ew, eh)) = (actual, expected);
            failed.push(format!(
                "{FOLDER}/{}.png: {aw}x{ah}, expected {ew}x{eh}",
                pose.name
            ));
        }
    }
    Ok(failed)
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
    fn every_addon_pose_is_exported() {
        let failed = missing(&root().join(FOLDER)).unwrap();
        assert!(
            failed.is_empty(),
            "run `cargo run -p ankiquest-xtask -- export-addon-art`: {failed:?}"
        );
    }

    #[test]
    fn poses_are_named_once() {
        let mut names: Vec<_> = POSES.iter().map(|pose| pose.name).collect();
        names.sort_unstable();
        names.dedup();
        assert_eq!(POSES.len(), names.len());
    }
}
