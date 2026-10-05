use mosaic::app::*;
use mosaic::overlap::Overlap;
use mosaic::png;
use mosaic::samples;
use mosaic::tiled::{expand, rotate_px, sockets_match, Tile};
use mosaic::tilesets;
use mosaic::verify;

fn ov(sample: &str, w: usize, h: usize) -> OverlapOpts {
    OverlapOpts { common: Common::new(w, h), sample: sample.into(), n: 3, symmetry: 1, wrap_in: false, ground: false }
}
fn tl(set: &str, w: usize, h: usize) -> TiledOpts {
    TiledOpts { common: Common::new(w, h), set: set.into() }
}

// ---------------------------------------------------------------- png

#[test]
fn crc_and_adler_known_vectors() {
    assert_eq!(png::crc32(b"123456789"), 0xCBF4_3926);
    assert_eq!(png::adler32(b"Wikipedia"), 0x11E6_0398);
}

#[test]
fn deflate_round_trips_runs_text_and_noise() {
    let mut noise = Vec::new();
    let mut r = mosaic::rng::Rng::new(9);
    for _ in 0..70_000 {
        noise.push(r.next_u64() as u8);
    }
    let text: Vec<u8> = "the quick brown fox jumps over the lazy dog. ".repeat(500).into_bytes();
    for data in [vec![], vec![7u8], vec![0u8; 100_000], text, noise] {
        let z = png::zlib_compress(&data);
        assert_eq!(png::zlib_decompress(&z).unwrap(), data);
    }
}

#[test]
fn compression_actually_compresses() {
    let flat = vec![0u8; 100_000];
    assert!(png::zlib_compress(&flat).len() < 1000);
    let px: Vec<u32> = (0..200 * 200).map(|i| if (i / 200 + i % 200) % 40 < 20 { 0x336699 } else { 0xFFCC00 }).collect();
    assert!(png::encode(200, 200, &px).len() < 200 * 200 * 3 / 10);
}

#[test]
fn png_encode_decode_round_trip() {
    let px: Vec<u32> = (0..37 * 23).map(|i| ((i * 2654435761u64 as usize) as u32) & 0xFFFFFF).collect();
    let bytes = png::encode(37, 23, &px);
    let (w, h, back) = png::decode(&bytes).unwrap();
    assert_eq!((w, h), (37, 23));
    assert_eq!(back, px);
}

#[test]
fn png_decoder_handles_real_zlib_dynamic_huffman_and_all_filters() {
    // fixture produced by Python's zlib (level 9 => dynamic Huffman) with filters 0..4 on RGBA rows
    let bytes = std::fs::read("tests/fixtures/mixed_filters_rgba.png").unwrap();
    let (w, h, px) = png::decode(&bytes).unwrap();
    let expect = std::fs::read_to_string("tests/fixtures/mixed_filters_rgba.txt").unwrap();
    let rows: Vec<Vec<u32>> = expect.lines().map(|l| l.split(' ').map(|t| u32::from_str_radix(t, 16).unwrap()).collect()).collect();
    assert_eq!((w, h), (20, 12));
    for y in 0..h {
        for x in 0..w {
            assert_eq!(px[y * w + x], rows[y][x], "pixel {},{}", x, y);
        }
    }
}

#[test]
fn png_decoder_rejects_corruption() {
    let mut bytes = png::encode(4, 4, &[0xFF0000; 16]);
    assert!(png::decode(&bytes[..20]).is_err());
    assert!(png::decode(b"not a png at all").is_err());
    let n = bytes.len();
    bytes[n - 20] ^= 0xFF; // flip a bit inside IDAT -> CRC mismatch
    assert!(png::decode(&bytes).unwrap_err().contains("CRC"));
}

#[test]
fn png_sample_loads_as_overlap_sample() {
    let img = samples::load("tests/fixtures/mixed_filters_rgba.png").unwrap();
    assert_eq!((img.w, img.h), (20, 12));
    let mut o = ov("tests/fixtures/mixed_filters_rgba.png", 12, 12);
    o.n = 2;
    o.wrap_in = true;
    let r = run_overlap(&o).unwrap();
    assert_eq!(r.violations, 0);
}

// ---------------------------------------------------------------- overlap model

#[test]
fn every_builtin_sample_yields_valid_output_for_many_seeds() {
    for (name, _) in samples::list() {
        let wrap = name == "waves";
        for seed in 1..=4 {
            let mut o = ov(name, 40, 28);
            o.common.seed = seed;
            o.wrap_in = wrap;
            let r = run_overlap(&o).unwrap_or_else(|e| panic!("{} seed {}: {}", name, seed, e));
            assert_eq!(r.violations, 0, "{} seed {}", name, seed);
            assert_eq!(r.px.len(), 40 * 28);
        }
    }
}

#[test]
fn output_only_uses_sample_colours() {
    let img = samples::load("dungeon").unwrap();
    let r = run_overlap(&ov("dungeon", 30, 30)).unwrap();
    assert!(r.px.iter().all(|c| img.px.contains(c)));
}

#[test]
fn same_seed_same_output_different_seed_different_output() {
    let a = run_overlap(&ov("flowers", 32, 32)).unwrap().px;
    let b = run_overlap(&ov("flowers", 32, 32)).unwrap().px;
    assert_eq!(a, b);
    let mut o = ov("flowers", 32, 32);
    o.common.seed = 99;
    assert_ne!(a, run_overlap(&o).unwrap().px);
}

#[test]
fn pattern_extraction_counts_and_symmetry_growth() {
    let img = samples::load("maze").unwrap();
    let p1 = Overlap::new(&img, 3, 1, false).unwrap().patterns.len();
    let p8 = Overlap::new(&img, 3, 8, false).unwrap().patterns.len();
    assert!(p8 > p1);
    // a flat image has exactly one pattern whatever the symmetry
    let flat = samples::Image { w: 5, h: 5, px: vec![0x112233; 25], glyphs: Default::default(), chars: Default::default() };
    assert_eq!(Overlap::new(&flat, 3, 8, false).unwrap().patterns.len(), 1);
    // sample counts: a 4x4 non-wrapping image has (4-3+1)^2 = 4 windows, wrapping 16
    let img4 = samples::Image { w: 4, h: 4, px: (0..16).map(|i| i as u32).collect(), glyphs: Default::default(), chars: Default::default() };
    assert_eq!(Overlap::new(&img4, 3, 1, false).unwrap().patterns.len(), 4);
    assert_eq!(Overlap::new(&img4, 3, 1, true).unwrap().patterns.len(), 16);
}

#[test]
fn sample_symmetry_is_respected_by_output() {
    let mut o = ov("wires", 36, 36);
    o.symmetry = 8;
    o.common.seed = 5;
    let r = run_overlap(&o).unwrap();
    assert_eq!(r.violations, 0);
}

#[test]
fn periodic_output_wraps_consistently() {
    let mut o = ov("waves", 30, 30);
    o.wrap_in = true;
    o.common.periodic = true;
    let r = run_overlap(&o).unwrap();
    assert_eq!(r.violations, 0);
    assert_eq!(r.grid, (30, 30));
}

#[test]
fn ground_anchors_bottom_row_only() {
    let img = samples::load("city").unwrap();
    let ground = img.chars[&'g'];
    let mut o = ov("city", 48, 20);
    o.ground = true;
    let r = run_overlap(&o).unwrap();
    assert_eq!(r.violations, 0);
    for x in 0..48 {
        assert_eq!(r.px[19 * 48 + x], ground, "bottom row must be ground");
        assert_ne!(r.px[0 * 48 + x], ground, "top row must not be ground");
    }
}

#[test]
fn pin_colour_forces_cell() {
    let img = samples::load("flowers").unwrap();
    let red = img.chars[&'*'];
    for seed in 1..=3 {
        let mut o = ov("flowers", 30, 30);
        o.common.seed = seed;
        o.common.pins = vec!["10,12,*".into(), "20,5,#4c9a2a".into()];
        let r = run_overlap(&o).unwrap();
        assert_eq!(r.px[12 * 30 + 10], red);
        assert_eq!(r.px[5 * 30 + 20], 0x4c9a2a);
        assert_eq!(r.violations, 0);
    }
}

#[test]
fn wires_pin_with_aliased_glyph_works() {
    // '+', '-' and '|' share one colour in the wires sample; pinning by glyph must still work
    let mut o = ov("wires", 30, 20);
    o.common.pins = vec!["5,5,+".into()];
    assert!(run_overlap(&o).is_ok());
}

// ---------------------------------------------------------------- tiled model

#[test]
fn rotation_helpers() {
    let s = 5;
    let px: Vec<u32> = (0..25).collect();
    let mut r = px.clone();
    for _ in 0..4 {
        r = rotate_px(&r, s);
    }
    assert_eq!(r, px);
    // clockwise: top-left pixel moves to top-right
    assert_eq!(rotate_px(&px, s)[s - 1], px[0]);
    // and the bottom-left pixel moves to the top-left
    assert_eq!(rotate_px(&px, s)[0], px[(s - 1) * s]);
    let base = Tile { name: "x".into(), px: px.clone(), sockets: ["a".into(), "b".into(), "c".into(), "d".into()], weight: 1.0 };
    let v = expand(&base, s, 4);
    assert_eq!(v.len(), 4);
    // rotating clockwise: old N (d) becomes E
    assert_eq!(v[1].sockets, ["b".to_string(), "c".to_string(), "d".to_string(), "a".to_string()]);
    assert_eq!(expand(&base, s, 1).len(), 1);
    assert_eq!(expand(&base, s, 2).len(), 2);
}

#[test]
fn socket_matching_rules() {
    assert!(sockets_match("w", "w"));
    assert!(!sockets_match("w", "n"));
    assert!(sockets_match("p+", "p-"));
    assert!(sockets_match("p-", "p+"));
    assert!(!sockets_match("p+", "p+"));
    assert!(!sockets_match("p+", "q-"));
    assert!(sockets_match("01", "01"));
}

#[test]
fn tileset_sizes() {
    assert_eq!(tilesets::get("circuit").unwrap().tiles.len(), 18); // 1+2+4+4+1+4+2
    assert_eq!(tilesets::get("terrain").unwrap().tiles.len(), 81);
}

#[test]
fn both_tilesets_solve_and_verify_for_many_seeds() {
    for set in ["circuit", "terrain"] {
        for seed in 1..=5 {
            let mut o = tl(set, 26, 18);
            o.common.seed = seed;
            let r = run_tiled(&o).unwrap();
            assert_eq!(r.violations, 0, "{} seed {}", set, seed);
        }
    }
}

#[test]
fn tiled_pins_force_tiles_and_prefix_matches_rotations() {
    let ts = tilesets::get("circuit").unwrap();
    let mut o = tl("circuit", 12, 12);
    o.common.pins = vec!["3,4,cross".into(), "6,6,pad".into()];
    let r = run_tiled(&o).unwrap();
    assert_eq!(ts.tiles[r.cells[4 * 12 + 3]].name, "cross_r0");
    assert!(ts.tiles[r.cells[6 * 12 + 6]].name.starts_with("pad_r"));
    assert_eq!(r.violations, 0);
    let mut o = tl("circuit", 12, 12);
    o.common.pins = vec!["3,4,line_r1".into()];
    let r = run_tiled(&o).unwrap();
    assert_eq!(ts.tiles[r.cells[4 * 12 + 3]].name, "line_r1");
}

#[test]
fn terrain_pin_shapes_the_map() {
    let ts = tilesets::get("terrain").unwrap();
    let mut o = tl("terrain", 16, 12);
    o.common.pins = vec!["8,6,t2222".into()];
    let r = run_tiled(&o).unwrap();
    assert_eq!(ts.tiles[r.cells[6 * 16 + 8]].name, "t2222");
    // neighbours must share grass corners with the pinned all-grass tile
    let east = &ts.tiles[r.cells[6 * 16 + 9]].name;
    assert!(east.as_bytes()[1] == b'2' && east.as_bytes()[4] == b'2', "{}", east);
}

#[test]
fn periodic_tiled_including_degenerate_sizes() {
    for (w, h) in [(1, 1), (2, 1), (1, 3), (8, 8)] {
        let mut o = tl("circuit", w, h);
        o.common.periodic = true;
        let r = run_tiled(&o).unwrap();
        assert_eq!(r.violations, 0, "{}x{}", w, h);
    }
}

#[test]
fn render_dimensions_match_tile_size() {
    let r = run_tiled(&tl("terrain", 5, 3)).unwrap();
    assert_eq!((r.w, r.h), (50, 30));
    assert_eq!(r.px.len(), 1500);
}

// ---------------------------------------------------------------- backtracking

#[test]
fn backtracking_actually_fires_and_still_yields_valid_output() {
    let mut total_bt = 0;
    for seed in 1..=8 {
        let mut o = ov("wires", 40, 40);
        o.n = 4;
        o.wrap_in = true;
        o.common.periodic = true;
        o.common.seed = seed;
        let r = run_overlap(&o).unwrap();
        assert_eq!(r.violations, 0, "seed {}", seed);
        total_bt += r.stats.backtracks;
    }
    assert!(total_bt > 0, "expected at least one backtrack across seeds");
}

#[test]
fn backtracking_beats_restart_only_on_a_constrained_wrap() {
    let run_mode = |bt: bool| {
        let (mut ok, mut restarts) = (0, 0);
        for seed in 1..=8 {
            let mut o = ov("wires", 40, 40);
            o.n = 4;
            o.wrap_in = true;
            o.common.periodic = true;
            o.common.seed = seed;
            o.common.backtrack = bt;
            o.common.max_restarts = 100;
            if let Ok(r) = run_overlap(&o) {
                ok += 1;
                restarts += r.stats.restarts;
                assert_eq!(r.violations, 0);
            }
        }
        (ok, restarts)
    };
    let (ok_b, rs_b) = run_mode(true);
    let (ok_r, rs_r) = run_mode(false);
    assert_eq!(ok_b, 8);
    assert!(ok_r > 0);
    assert!(rs_b < rs_r, "backtracking should need fewer restarts ({} vs {})", rs_b, rs_r);
}

// ---------------------------------------------------------------- validators catch broken output

#[test]
fn overlap_validator_flags_tampering() {
    let img = samples::load("maze").unwrap();
    let mut r = run_overlap(&ov("maze", 30, 20)).unwrap();
    assert_eq!(verify::overlap_windows(&img, 3, 1, false, &r.px, 30, 20, false).0, 0);
    r.px[10 * 30 + 10] = 0xFF00FF; // colour that never occurs in the sample
    let (bad, first) = verify::overlap_windows(&img, 3, 1, false, &r.px, 30, 20, false);
    assert!(bad >= 1 && first.is_some());
}

#[test]
fn tiled_validator_flags_tampering() {
    let ts = tilesets::get("circuit").unwrap();
    let mut r = run_tiled(&tl("circuit", 10, 10)).unwrap();
    assert_eq!(verify::tiled_edges(&ts, &r.cells, 10, 10, false).0, 0);
    let wire = ts.find("cross")[0];
    let empty = ts.find("empty")[0];
    let c = 5 * 10 + 5;
    // an unmistakable violation: a cross (four wire sockets) right next to an empty tile
    r.cells[c] = wire;
    r.cells[c + 1] = empty;
    assert!(verify::tiled_edges(&ts, &r.cells, 10, 10, false).0 >= 1);
}

// ---------------------------------------------------------------- animation

#[test]
fn animation_records_frames_and_ends_on_final_image() {
    let mut o = ov("flowers", 30, 24);
    o.common.anim_frames = 25;
    let r = run_overlap(&o).unwrap();
    assert!(r.frames.len() >= 10 && r.frames.len() <= 25, "{}", r.frames.len());
    assert_eq!(r.frames.last().unwrap().2, r.px);
    assert_ne!(r.frames[0].2, r.px);
    let html = mosaic::anim::html("a<b>&\"", "info", &r.frames, 4);
    assert!(html.contains("a&lt;b&gt;&amp;&quot;"));
    assert!(html.contains("data:image/png;base64,"));
}

#[test]
fn animation_shows_backtracking_run() {
    let mut o = ov("wires", 40, 40);
    o.n = 4;
    o.wrap_in = true;
    o.common.periodic = true;
    o.common.anim_frames = 40;
    let r = run_overlap(&o).unwrap();
    assert!(r.frames.len() >= 20);
}

// ---------------------------------------------------------------- error handling

#[test]
fn errors_are_reported_not_panicked() {
    assert!(run_overlap(&ov("nope", 10, 10)).unwrap_err().contains("unknown sample"));
    assert!(run_overlap(&ov("wires", 0, 10)).unwrap_err().contains("at least 1x1"));
    assert!(run_overlap(&ov("wires", 2, 2)).unwrap_err().contains("smaller than the pattern size"));
    let mut o = ov("wires", 20, 20);
    o.n = 1;
    assert!(run_overlap(&o).is_err());
    let mut o = ov("wires", 20, 20);
    o.symmetry = 9;
    assert!(run_overlap(&o).is_err());
    let mut o = ov("wires", 20, 20);
    o.common.pins = vec!["1,1".into()];
    assert!(run_overlap(&o).unwrap_err().contains("expected x,y,value"));
    o.common.pins = vec!["x,1,O".into()];
    assert!(run_overlap(&o).unwrap_err().contains("x must be a number"));
    o.common.pins = vec!["1,1,Q".into()];
    assert!(run_overlap(&o).unwrap_err().contains("not in the sample"));
    o.common.pins = vec!["500,1,O".into()];
    assert!(run_overlap(&o).unwrap_err().contains("outside"));
    let mut o = ov("wires", 20, 20);
    o.ground = true;
    o.common.periodic = true;
    assert!(run_overlap(&o).unwrap_err().contains("--ground"));
    assert!(run_overlap(&ov("wires", 100_000, 100)).unwrap_err().contains("too large"));

    assert!(run_tiled(&tl("nope", 5, 5)).unwrap_err().contains("unknown tileset"));
    let mut o = tl("terrain", 4, 1);
    o.common.pins = vec!["0,0,t0000".into(), "1,0,t2222".into()];
    assert!(run_tiled(&o).unwrap_err().contains("unsatisfiable"));
    o.common.pins = vec!["0,0,bogus".into()];
    assert!(run_tiled(&o).unwrap_err().contains("no tile named"));
    // genuinely unfillable: the 15x15 maze sample cannot tile 60x40 with 5x5 patterns
    let mut o = ov("maze", 60, 40);
    o.n = 5;
    assert!(run_overlap(&o).unwrap_err().contains("unsatisfiable"));
}

#[test]
fn exhaustion_is_reported() {
    // restart budget of 1 and backtracking disabled on a config known to contradict
    let mut hit = false;
    for seed in 1..=30 {
        let mut o = ov("wires", 40, 40);
        o.n = 4;
        o.wrap_in = true;
        o.common.periodic = true;
        o.common.backtrack = false;
        o.common.max_restarts = 1;
        o.common.seed = seed;
        if let Err(e) = run_overlap(&o) {
            assert!(e.contains("restart budget"));
            hit = true;
            break;
        }
    }
    assert!(hit, "expected at least one exhausted run");
}

// ---------------------------------------------------------------- CLI end to end

fn bin() -> std::process::Command {
    std::process::Command::new(env!("CARGO_BIN_EXE_mosaic"))
}

#[test]
fn cli_overlap_tiled_anim_and_bench() {
    let dir = std::env::temp_dir().join(format!("mosaic-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let png_path = dir.join("o.png");
    let html_path = dir.join("o.html");
    let out = bin()
        .args(["overlap", "--sample", "dungeon", "--size", "30x20", "--out"])
        .arg(&png_path)
        .arg("--anim")
        .arg(&html_path)
        .args(["--anim-frames", "20", "--ascii"])
        .output()
        .unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("verify: OK"));
    assert_eq!(stdout.lines().filter(|l| l.chars().all(|c| "# .+".contains(c)) && l.len() == 30).count(), 20);
    let (w, h, _) = png::decode(&std::fs::read(&png_path).unwrap()).unwrap();
    assert_eq!((w, h), (240, 160));
    assert!(std::fs::read_to_string(&html_path).unwrap().contains("<img id=\"f\""));

    let out = bin().args(["tiled", "--set", "circuit", "--size", "8x8", "--pin", "2,2,cross", "--quiet", "--out"]).arg(&png_path).output().unwrap();
    assert!(out.status.success());
    assert!(out.stdout.is_empty());

    let out = bin().args(["bench", "tiled", "--set", "circuit", "--size", "10x10", "--trials", "3"]).output().unwrap();
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("backtracking") && s.contains("restart-only") && s.contains("3/3"), "{}", s);

    let out = bin().arg("list").output().unwrap();
    let s = String::from_utf8_lossy(&out.stdout);
    assert!(s.contains("dungeon") && s.contains("terrain"));
    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn cli_bad_input_exits_2_with_one_line_error() {
    for args in [
        vec!["overlap"],
        vec!["overlap", "--sample", "nope"],
        vec!["overlap", "--sample", "wires", "--size", "banana"],
        vec!["overlap", "--sample", "wires", "--seed", "x"],
        vec!["overlap", "--sample", "wires", "--wat"],
        vec!["tiled", "--set", "circuit", "--scale", "0"],
        vec!["tiled", "--set", "circuit", "--anim", "/tmp/x.html", "--anim-frames", "1"],
        vec!["frobnicate"],
    ] {
        let out = bin().args(&args).output().unwrap();
        assert_eq!(out.status.code(), Some(2), "{:?}", args);
        assert!(String::from_utf8_lossy(&out.stderr).starts_with("error:"), "{:?}", args);
    }
}

#[test]
fn circuit_pixels_agree_with_sockets_after_rotation() {
    // independent of the solver: an edge's midpoint pixel carries copper iff its socket is "w"
    let ts = tilesets::get("circuit").unwrap();
    let s = ts.size;
    let mid = s / 2;
    let board = 0x0b3d2e;
    for t in &ts.tiles {
        let edge = [t.px[mid * s], t.px[(s - 1) * s + mid], t.px[mid * s + s - 1], t.px[mid]]; // W S E N
        for d in 0..4 {
            assert_eq!(edge[d] != board, t.sockets[d] == "w", "tile {} side {}", t.name, d);
        }
    }
}
