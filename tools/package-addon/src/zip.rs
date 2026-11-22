//! Writes ZIP archives byte for byte as Python's `zipfile` did for the
//! old packaging script: deflated with zlib's default level, no extra
//! fields, every entry dated 1980-01-01 and marked as a Unix 0644 file.
//!
//! The data is compressed with zlib itself, not a Rust port, because
//! ports choose different matches and so give different bytes.

use std::collections::BTreeMap;
use std::os::raw::c_ulong;

use libz_sys::{Z_OK, compress2, compressBound};

/// Local file header signature.
const LOCAL: u32 = 0x0403_4b50;

/// Central directory header signature.
const CENTRAL: u32 = 0x0201_4b50;

/// End of central directory signature.
const END: u32 = 0x0605_4b50;

/// Version 2.0: needed for deflate, and the version Python writes.
const VERSION: u8 = 20;

/// "Made by" host system: Unix.
const UNIX: u8 = 3;

/// Compression method: deflate.
const DEFLATE: u16 = 8;

/// General purpose flag: the name is UTF-8.
const UTF8_NAME: u16 = 0x800;

/// MS-DOS date of 1980-01-01, the earliest a ZIP can store.
const DOS_DATE: u16 = (1 << 5) | 1;

/// MS-DOS time of 00:00:00.
const DOS_TIME: u16 = 0;

/// Unix permissions 0644 in the high half of the external attributes.
const MODE: u32 = 0o644 << 16;

/// zlib's default compression level (6), as Python's `zipfile` uses.
const LEVEL: i32 = -1;

/// The two-byte zlib header and four-byte Adler-32 trailer around the
/// raw deflate data that ZIP stores.
const ZLIB_HEADER: usize = 2;
const ZLIB_TRAILER: usize = 4;

/// One entry as the central directory describes it.
struct Entry<'a> {
    name: &'a str,
    flags: u16,
    crc: u32,
    compressed: u32,
    size: u32,
    offset: u32,
}

/// The archive of `files`, in name order.
pub(super) fn archive(files: &BTreeMap<String, Vec<u8>>) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    let mut entries = Vec::new();

    // Each file: its local header, then its compressed data.
    for (name, bytes) in files {
        let data = deflate(bytes)?;
        let entry = Entry {
            name,
            flags: if name.is_ascii() { 0 } else { UTF8_NAME },
            crc: crc32fast::hash(bytes),
            compressed: size(data.len())?,
            size: size(bytes.len())?,
            offset: size(out.len())?,
        };
        local(&mut out, &entry);
        out.extend_from_slice(&data);
        entries.push(entry);
    }

    // The central directory lists every entry, then the end record finds it.
    let start = out.len();
    for entry in &entries {
        central(&mut out, entry);
    }
    let count = u16::try_from(entries.len()).map_err(|_| "too many files for a ZIP")?;
    let directory = size(out.len() - start)?;
    put32(&mut out, END);
    put16(&mut out, 0);
    put16(&mut out, 0);
    put16(&mut out, count);
    put16(&mut out, count);
    put32(&mut out, directory);
    put32(&mut out, size(start)?);
    put16(&mut out, 0);
    Ok(out)
}

/// Writes an entry's local file header.
fn local(out: &mut Vec<u8>, entry: &Entry) {
    put32(out, LOCAL);
    out.extend_from_slice(&[VERSION, 0]);
    put16(out, entry.flags);
    put16(out, DEFLATE);
    put16(out, DOS_TIME);
    put16(out, DOS_DATE);
    put32(out, entry.crc);
    put32(out, entry.compressed);
    put32(out, entry.size);
    put16(out, name_len(entry));
    put16(out, 0);
    out.extend_from_slice(entry.name.as_bytes());
}

/// Writes an entry's central directory header.
fn central(out: &mut Vec<u8>, entry: &Entry) {
    put32(out, CENTRAL);
    out.extend_from_slice(&[VERSION, UNIX, VERSION, 0]);
    put16(out, entry.flags);
    put16(out, DEFLATE);
    put16(out, DOS_TIME);
    put16(out, DOS_DATE);
    put32(out, entry.crc);
    put32(out, entry.compressed);
    put32(out, entry.size);
    put16(out, name_len(entry));
    put16(out, 0);
    put16(out, 0);
    put16(out, 0);
    put16(out, 0);
    put32(out, MODE);
    put32(out, entry.offset);
    out.extend_from_slice(entry.name.as_bytes());
}

/// Raw deflate data of `bytes`, as zlib writes it at the default level.
fn deflate(bytes: &[u8]) -> Result<Vec<u8>, String> {
    let source_len = c_ulong::try_from(bytes.len()).map_err(|e| e.to_string())?;
    // SAFETY: compressBound only computes a size.
    let bound = unsafe { compressBound(source_len) };
    let mut out = vec![0u8; usize::try_from(bound).map_err(|e| e.to_string())?];
    let mut out_len = bound;

    // SAFETY: `out` holds `out_len` writable bytes and `bytes` holds
    // `source_len` readable ones; zlib writes at most `out_len` and
    // stores the length it wrote there.
    let status = unsafe {
        compress2(
            out.as_mut_ptr(),
            &mut out_len,
            bytes.as_ptr(),
            source_len,
            LEVEL,
        )
    };
    if status != Z_OK {
        return Err(format!("zlib compress2 failed: {status}"));
    }

    // The deflate stream is the same with or without the zlib wrapper.
    out.truncate(usize::try_from(out_len).map_err(|e| e.to_string())?);
    Ok(out[ZLIB_HEADER..out.len() - ZLIB_TRAILER].to_vec())
}

/// A length or offset as ZIP's 32-bit field; larger archives need ZIP64.
fn size(value: usize) -> Result<u32, String> {
    u32::try_from(value).map_err(|_| "archive too large for a ZIP without ZIP64".to_owned())
}

/// The name's length; names come from the file system and stay short.
fn name_len(entry: &Entry) -> u16 {
    u16::try_from(entry.name.len()).unwrap_or(u16::MAX)
}

fn put16(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn put32(out: &mut Vec<u8>, value: u32) {
    out.extend_from_slice(&value.to_le_bytes());
}

/// Compression method: stored, as AnkiQuest-Art's release archives are.
const STORED: u16 = 0;

/// Length of the end of central directory record without its comment.
const END_LEN: usize = 22;

/// The longest comment an end of central directory record can carry.
const MAX_COMMENT: usize = u16::MAX as usize;

/// Length of a central directory header before its name.
const CENTRAL_LEN: usize = 46;

/// Length of a local file header before its name.
const LOCAL_LEN: usize = 30;

/// Every entry of a stored (uncompressed) archive, as (name, contents),
/// each checked against its CRC-32. Folders are left out.
pub(super) fn entries(bytes: &[u8]) -> Result<Vec<(String, Vec<u8>)>, String> {
    let end = find_end(bytes)?;
    let count = usize::from(u16_at(bytes, end + 10)?);
    let mut at = u32_at(bytes, end + 16)? as usize;
    let mut out = Vec::with_capacity(count);
    for _ in 0..count {
        if u32_at(bytes, at)? != CENTRAL {
            return Err("broken central directory".to_owned());
        }
        let method = u16_at(bytes, at + 10)?;
        let crc = u32_at(bytes, at + 16)?;
        let compressed = u32_at(bytes, at + 20)? as usize;
        let size = u32_at(bytes, at + 24)? as usize;
        let name_len = usize::from(u16_at(bytes, at + 28)?);
        let extra_len = usize::from(u16_at(bytes, at + 30)?);
        let comment_len = usize::from(u16_at(bytes, at + 32)?);
        let offset = u32_at(bytes, at + 42)? as usize;
        let name = slice(bytes, at + CENTRAL_LEN, name_len)?;
        let name = String::from_utf8(name.to_vec()).map_err(|_| "a name is not UTF-8")?;
        at += CENTRAL_LEN + name_len + extra_len + comment_len;

        // Release archives store their pictures as they are.
        if method != STORED || compressed != size {
            return Err(format!("{name} is compressed; expected stored entries"));
        }
        if name.ends_with('/') {
            continue;
        }
        if u32_at(bytes, offset)? != LOCAL {
            return Err(format!("{name}: broken local header"));
        }
        let local_name = usize::from(u16_at(bytes, offset + 26)?);
        let local_extra = usize::from(u16_at(bytes, offset + 28)?);
        let data = slice(bytes, offset + LOCAL_LEN + local_name + local_extra, size)?;
        if crc32fast::hash(data) != crc {
            return Err(format!("{name}: CRC-32 mismatch"));
        }
        out.push((name, data.to_vec()));
    }
    Ok(out)
}

/// Where the end of central directory record starts.
fn find_end(bytes: &[u8]) -> Result<usize, String> {
    let last = bytes
        .len()
        .checked_sub(END_LEN)
        .ok_or("not a ZIP archive")?;
    let first = last.saturating_sub(MAX_COMMENT);
    (first..=last)
        .rev()
        .find(|&at| u32_at(bytes, at) == Ok(END))
        .ok_or_else(|| "not a ZIP archive".to_owned())
}

/// `len` bytes of `bytes` from `at`.
fn slice(bytes: &[u8], at: usize, len: usize) -> Result<&[u8], String> {
    at.checked_add(len)
        .and_then(|end| bytes.get(at..end))
        .ok_or_else(|| "truncated ZIP archive".to_owned())
}

/// The little-endian u16 at `at`.
fn u16_at(bytes: &[u8], at: usize) -> Result<u16, String> {
    let b = slice(bytes, at, 2)?;
    Ok(u16::from_le_bytes([b[0], b[1]]))
}

/// The little-endian u32 at `at`.
fn u32_at(bytes: &[u8], at: usize) -> Result<u32, String> {
    let b = slice(bytes, at, 4)?;
    Ok(u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}
