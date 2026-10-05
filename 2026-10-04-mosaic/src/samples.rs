//! Built-in ASCII sample images and a loader for external samples (.txt ASCII art, .ppm).

use std::collections::HashMap;

#[derive(Clone)]
pub struct Image {
    pub w: usize,
    pub h: usize,
    pub px: Vec<u32>,
    /// color -> glyph, used for ASCII export of overlap results
    pub glyphs: HashMap<u32, char>,
    /// glyph -> color for every character used by an ASCII sample (several glyphs may share a colour)
    pub chars: HashMap<char, u32>,
}

struct Builtin {
    name: &'static str,
    about: &'static str,
    legend: &'static [(char, u32)],
    rows: &'static [&'static str],
}

const BUILTINS: &[Builtin] = &[
    Builtin {
        name: "flowers",
        about: "meadow with red/yellow flowers and a pond",
        legend: &[('.', 0x4c9a2a), ('*', 0xe8453c), ('o', 0xf4d03f), ('~', 0x3b82c4), ('t', 0x1f5f1f)],
        rows: &[
            "................",
            "..*......t......",
            ".***....ttt.....",
            "..*......t......",
            "..........o.....",
            "..~~~....ooo....",
            ".~~~~~....o.....",
            ".~~~~~~.........",
            "..~~~~....*.....",
            "...~~....***....",
            "..........*..o..",
            "....t.......ooo.",
            "...ttt.......o..",
            "....t...........",
            "................",
            "................",
        ],
    },
    Builtin {
        name: "dungeon",
        about: "rooms, corridors and doors",
        legend: &[('#', 0x2b2b3a), ('.', 0xb9a98a), ('+', 0x8b4a1f), (' ', 0x14141c)],
        rows: &[
            "################      ",
            "#......#.......#      ",
            "#......#.......#      ",
            "#......+.......#      ",
            "#......#.......#      ",
            "###+####...#####      ",
            "  #.#  ###.###        ",
            "  #.#    #.#   ###### ",
            "  #.#    #.#   #....# ",
            "###.######.#####....# ",
            "#............+.+....# ",
            "#.####.#####.#####+## ",
            "#.#  #.#   #.#   #.#  ",
            "#.#  #.#   #.#   #.#  ",
            "#+#  #+#   #+#   #+#  ",
            "#.#  #.#   #.#   #.#  ",
        ],
    },
    Builtin {
        name: "city",
        about: "skyline with lit windows, sky above and ground below (try --ground)",
        legend: &[('.', 0x7ec8e3), ('B', 0x40424f), ('w', 0xffe066), ('d', 0x2d2f3a), ('g', 0x3a3a3a), ('c', 0xf5f5f5)],
        rows: &[
            "..........c.....................",
            ".....BBB.....................c..",
            ".....BwB........BBBB............",
            "..BBBBwBBB......BwwB....BBB.....",
            "..BwBBBBwB..BBB.BBBB....BwB.....",
            "..BBBwBBBB..BwB.BwwB.BB.BBB.BB..",
            "..BwBBBwBB..BBB.BBwB.BwB.BwB.BwB",
            "..BBBwBBBB..BwB.BwBB.BBB.BBBBwBB",
            "..BwBBBwBB..BBB.BBwB.BwB.BwBBBwB",
            "..BBBdBBBB..BwB.BBBB.BBB.BBBdBBB",
            "gggggggggggggggggggggggggggggggg",
            "gggggggggggggggggggggggggggggggg",
            "gggggggggggggggggggggggggggggggg",
            "gggggggggggggggggggggggggggggggg",
        ],
    },
    Builtin {
        name: "wires",
        about: "circuit-board traces and pads",
        legend: &[('.', 0x0d3b2e), ('-', 0xd4a017), ('|', 0xd4a017), ('+', 0xd4a017), ('O', 0xf2f2f2)],
        rows: &[
            "................",
            "..O---+.........",
            "......|...O-----",
            "......|.........",
            "......+-----+...",
            "............|...",
            "..O---------+...",
            "................",
            "...|.......|....",
            "...|...O---+....",
            "...+--------O...",
            "................",
        ],
    },
    Builtin {
        name: "maze",
        about: "classic wall/corridor maze",
        legend: &[('#', 0x1a1a2e), ('.', 0xe6dcc8)],
        rows: &[
            "###############",
            "#.....#.......#",
            "#.###.#.#####.#",
            "#.#...#.....#.#",
            "#.#.#######.#.#",
            "#.#.......#.#.#",
            "#.#######.#.#.#",
            "#.......#.#...#",
            "#######.#.#####",
            "#.......#.....#",
            "#.#########.#.#",
            "#.#.......#.#.#",
            "#.#.#####.#.#.#",
            "#...#.....#...#",
            "###############",
        ],
    },
    Builtin {
        name: "waves",
        about: "periodic ocean ripples (use --wrap-in)",
        legend: &[('~', 0x1d6fa5), ('^', 0x5ec2e8), ('.', 0x0e4a75)],
        rows: &[
            "~~~~~^^^~~~~~~~~",
            "~~~^^~~~^^~~~~~~",
            "~^^~~~~~~~^^~~~~",
            "^~~~~..~~~~~^^~~",
            "~~~~.....~~~~~~^",
            "~~~~~...~~~~~~~~",
            "~~~~~~~~~~^^~~~~",
            "~^^~~~~~^^~~^^~~",
            "^~~^^~^^~~~~~~^^",
            "~~~~~^~~~~~~~~~~",
        ],
    },
];

pub fn list() -> Vec<(&'static str, &'static str)> {
    BUILTINS.iter().map(|b| (b.name, b.about)).collect()
}

fn color_for_unknown(c: char) -> u32 {
    // deterministic pleasant color from the glyph
    let mut h = (c as u32).wrapping_mul(2654435761);
    h ^= h >> 15;
    let r = 64 + (h & 0x7F);
    let g = 64 + ((h >> 7) & 0x7F);
    let b = 64 + ((h >> 14) & 0x7F);
    (r << 16) | (g << 8) | b
}

fn from_ascii(rows: &[&str], legend: &[(char, u32)]) -> Result<Image, String> {
    if rows.is_empty() {
        return Err("sample is empty".into());
    }
    let w = rows[0].chars().count();
    if w == 0 {
        return Err("sample has an empty first row".into());
    }
    let mut px = Vec::with_capacity(w * rows.len());
    let mut glyphs = HashMap::new();
    let mut chars = HashMap::new();
    for (i, r) in rows.iter().enumerate() {
        if r.chars().count() != w {
            return Err(format!("row {} has width {} but row 0 has width {}", i + 1, r.chars().count(), w));
        }
        for ch in r.chars() {
            let col = legend.iter().find(|(c, _)| *c == ch).map(|(_, v)| *v).unwrap_or_else(|| color_for_unknown(ch));
            glyphs.entry(col).or_insert(ch);
            chars.insert(ch, col);
            px.push(col);
        }
    }
    Ok(Image { w, h: rows.len(), px, glyphs, chars })
}

/// Load a built-in sample by name, or a `.txt` / `.ppm` / `.png` file by path.
pub fn load(spec: &str) -> Result<Image, String> {
    if let Some(b) = BUILTINS.iter().find(|b| b.name == spec) {
        return from_ascii(b.rows, b.legend);
    }
    let path = std::path::Path::new(spec);
    if !path.exists() {
        let names: Vec<&str> = BUILTINS.iter().map(|b| b.name).collect();
        return Err(format!("unknown sample '{}' (built-ins: {}; or give a .txt, .ppm or .png path)", spec, names.join(", ")));
    }
    let bytes = std::fs::read(path).map_err(|e| format!("cannot read {}: {}", spec, e))?;
    if bytes.starts_with(&[0x89, b'P', b'N', b'G']) {
        let (w, h, px) = crate::png::decode(&bytes).map_err(|e| format!("{}: {}", spec, e))?;
        Ok(Image { w, h, px, glyphs: HashMap::new(), chars: HashMap::new() })
    } else if bytes.starts_with(b"P3") || bytes.starts_with(b"P6") {
        parse_ppm(&bytes)
    } else {
        let text = String::from_utf8(bytes).map_err(|_| "sample file is not UTF-8 text or PPM".to_string())?;
        let rows: Vec<&str> = text.lines().filter(|l| !l.is_empty()).collect();
        from_ascii(&rows, &[])
    }
}

fn parse_ppm(b: &[u8]) -> Result<Image, String> {
    let binary = b.starts_with(b"P6");
    let mut pos = 2;
    let mut nums = Vec::new();
    // header: width height maxval, with # comments
    while nums.len() < 3 {
        while pos < b.len() && (b[pos].is_ascii_whitespace() || b[pos] == b'#') {
            if b[pos] == b'#' {
                while pos < b.len() && b[pos] != b'\n' {
                    pos += 1;
                }
            } else {
                pos += 1;
            }
        }
        let s = pos;
        while pos < b.len() && b[pos].is_ascii_digit() {
            pos += 1;
        }
        if s == pos {
            return Err("malformed PPM header".into());
        }
        nums.push(std::str::from_utf8(&b[s..pos]).unwrap().parse::<usize>().map_err(|_| "bad PPM number")?);
    }
    let (w, h, maxv) = (nums[0], nums[1], nums[2]);
    if w == 0 || h == 0 || maxv == 0 || maxv > 255 {
        return Err("unsupported PPM (need 1..255 maxval and nonzero size)".into());
    }
    let scale = |v: usize| (v * 255 / maxv) as u32;
    let mut px = Vec::with_capacity(w * h);
    if binary {
        pos += 1; // single whitespace after maxval
        if b.len() < pos + w * h * 3 {
            return Err("truncated PPM data".into());
        }
        for i in 0..w * h {
            let o = pos + i * 3;
            px.push(scale(b[o] as usize) << 16 | scale(b[o + 1] as usize) << 8 | scale(b[o + 2] as usize));
        }
    } else {
        let text = String::from_utf8_lossy(&b[pos..]);
        let vals: Vec<usize> = text.split_whitespace().filter_map(|t| t.parse().ok()).collect();
        if vals.len() < w * h * 3 {
            return Err("truncated PPM data".into());
        }
        for i in 0..w * h {
            px.push(scale(vals[i * 3]) << 16 | scale(vals[i * 3 + 1]) << 8 | scale(vals[i * 3 + 2]));
        }
    }
    Ok(Image { w, h, px, glyphs: HashMap::new(), chars: HashMap::new() })
}
