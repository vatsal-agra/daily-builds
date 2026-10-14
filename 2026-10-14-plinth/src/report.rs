//! Self-contained HTML block map of an image: who owns every block, per-file extents, issues.
use crate::fsck::{analyze_image, Analysis, Owner};
use crate::layout::*;

fn esc(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '<' => o.push_str("\\u003c"),
            '>' => o.push_str("\\u003e"),
            '&' => o.push_str("\\u0026"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o
}

fn extents(blocks: &[u32]) -> Vec<(u32, u32)> {
    let mut v: Vec<u32> = blocks.iter().copied().filter(|&b| b != 0).collect();
    v.sort_unstable();
    let mut out: Vec<(u32, u32)> = vec![];
    for b in v {
        match out.last_mut() {
            Some((s, l)) if *s + *l == b => *l += 1,
            _ => out.push((b, 1)),
        }
    }
    out
}

pub fn analysis_json(a: &Analysis) -> String {
    let sb = match &a.sb {
        Some(s) => s,
        None => return format!("{{\"error\":\"{}\"}}", esc(&a.issues.first().map(|i| i.to_string()).unwrap_or_default())),
    };
    let mut cat = String::new();
    let mut own = Vec::with_capacity(a.owner.len());
    for o in &a.owner {
        let (c, i) = match o {
            Owner::Free => ('0', 0),
            Owner::Super => ('1', 0),
            Owner::Journal => ('2', 0),
            Owner::InodeBitmap => ('3', 0),
            Owner::BlockBitmap => ('4', 0),
            Owner::InodeTable => ('5', 0),
            Owner::Data(i) => ('6', *i),
            Owner::Indirect(i) => ('7', *i),
            Owner::DirData(i) => ('8', *i),
        };
        cat.push(c);
        own.push(i.to_string());
    }
    let mut files = vec![];
    for ino in 1..sb.ninodes as usize {
        let inode = &a.inodes[ino];
        let kind = match inode.kind() {
            Some(k) => k,
            None => continue,
        };
        let path = a.paths.get(&(ino as u32)).cloned().unwrap_or_else(|| format!("(orphan #{ino})"));
        let mut all: Vec<u32> = a.maps[ino].clone();
        for (b, o) in a.owner.iter().enumerate() {
            if *o == Owner::Indirect(ino as u32) {
                all.push(b as u32);
            }
        }
        let used = all.iter().filter(|&&b| b != 0).count();
        let ex: Vec<String> = extents(&all).iter().map(|(s, l)| format!("[{s},{l}]")).collect();
        let size_blocks = (inode.size + BS as u64 - 1) / BS as u64;
        let holes = if kind == Kind::Dir { 0 } else { size_blocks.saturating_sub(a.maps[ino].iter().filter(|&&b| b != 0).count() as u64) };
        files.push(format!(
            "{{\"ino\":{ino},\"path\":\"{}\",\"kind\":\"{}\",\"size\":{},\"nlink\":{},\"perm\":{},\"blocks\":{used},\"holes\":{holes},\"extents\":[{}]}}",
            esc(&path),
            kind.name(),
            inode.size,
            inode.nlink,
            inode.perm,
            ex.join(",")
        ));
    }
    let issues: Vec<String> = a.issues.iter().map(|i| format!("\"{}\"", esc(&i.to_string()))).collect();
    format!(
        "{{\"sb\":{{\"nblocks\":{},\"ninodes\":{},\"journal_start\":{},\"journal_len\":{},\"data_start\":{},\"free_blocks\":{},\"free_inodes\":{},\"clock\":{}}},\"cat\":\"{}\",\"own\":[{}],\"files\":[{}],\"issues\":[{}],\"journal_pending\":{},\"stats\":{{\"files\":{},\"dirs\":{},\"symlinks\":{},\"used\":{},\"holes\":{}}}}}",
        sb.nblocks, sb.ninodes, sb.journal_start, sb.journal_len, sb.data_start, sb.free_blocks, sb.free_inodes, sb.clock,
        cat,
        own.join(","),
        files.join(","),
        issues.join(","),
        a.journal_pending,
        a.stats.files, a.stats.dirs, a.stats.symlinks, a.stats.data_blocks_used, a.stats.sparse_holes
    )
}

pub fn html_map(image: Vec<u8>, title: &str) -> String {
    let a = analyze_image(image);
    let safe_title: String = title.chars().map(|c| if c.is_ascii_alphanumeric() || "._-/ ".contains(c) { c } else { '_' }).collect();
    TEMPLATE.replace("/*DATA*/null", &analysis_json(&a)).replace("{{TITLE}}", &safe_title)
}

const TEMPLATE: &str = include_str!("report.html");
