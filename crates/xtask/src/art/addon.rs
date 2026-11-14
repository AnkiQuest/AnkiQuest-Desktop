//! Writes the desktop add-on's companion poses from the master PNGs in
//! `static/`: every `addon` entry of the art manifest (`art-exports.json`).
//!
//! Each pose is a 256 px square, 256-colour palette PNG with transparency.
//! Export writes them all and records each file's SHA-256 in the manifest.
//! `--check` writes nothing and fails when a pose differs from what export
//! would write, or from the hash in the manifest.

use std::fs;
use std::process::ExitCode;

use color_quant::NeuQuant;
use image::RgbaImage;

use super::exports::{self, Export, Exporter};
use super::{load, root, shrink, target};

/// Pose edge in pixels: the Today panel shows 96 px at up to 2x, and
/// moments 112 px.
const SIZE: u32 = 256;

/// Palette size, the most an indexed PNG holds.
const COLOURS: usize = 256;

/// NeuQuant sampling factor: 1 looks at every pixel, the slowest and best.
const SAMPLING: i32 = 1;

/// Largest mean channel difference, out of 255, between a committed pose
/// and a fresh export: float rounding on another machine can move a few
/// palette entries, a different picture moves far more.
const MEAN_TOLERANCE: f64 = 0.5;

/// Largest single channel difference between a committed pose and a fresh
/// export.
const PIXEL_TOLERANCE: u8 = 48;

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

/// Whether a manifest entry is an add-on pose.
fn is_pose(export: &Export) -> bool {
    export.exporter == Exporter::Addon
}

/// The pose `export` describes, made from its master.
fn render(export: &Export) -> Result<Vec<u8>, String> {
    let master = load(&root().join(&export.master))?;
    let (width, height) = target(master.width(), master.height(), SIZE);
    encode(&shrink(master, width, height))
}

/// Writes every pose and records its hash in the manifest.
fn export() -> Result<ExitCode, String> {
    let mut manifest = exports::read()?;
    for export in manifest.exports.iter_mut().filter(|export| is_pose(export)) {
        let bytes = render(export)?;
        let path = root().join(&export.file);
        if let Some(folder) = path.parent() {
            fs::create_dir_all(folder).map_err(|e| format!("{}: {e}", folder.display()))?;
        }
        fs::write(&path, &bytes).map_err(|e| format!("{}: {e}", path.display()))?;
        export.sha256 = exports::sha256(&bytes);
        println!("{}: {} bytes", export.file, bytes.len());
    }
    exports::write(&manifest)?;
    Ok(ExitCode::SUCCESS)
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
    for export in exports::read()?
        .exports
        .iter()
        .filter(|export| is_pose(export))
    {
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

/// Whether two PNGs show the same pixels up to float rounding.
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
    let total: f64 = differences.iter().map(|&d| f64::from(d)).sum();
    let mean = total / differences.len().max(1) as f64;
    let worst = differences.iter().copied().max().unwrap_or(0);
    Ok(mean <= MEAN_TOLERANCE && worst <= PIXEL_TOLERANCE)
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
    fn a_changed_picture_is_not_close() {
        let red = RgbaImage::from_pixel(8, 8, image::Rgba([255, 0, 0, 255]));
        let blue = RgbaImage::from_pixel(8, 8, image::Rgba([0, 0, 255, 255]));
        let (red, blue) = (encode(&red).unwrap(), encode(&blue).unwrap());
        assert!(close(&red, &red).unwrap());
        assert!(!close(&red, &blue).unwrap());
    }
}
