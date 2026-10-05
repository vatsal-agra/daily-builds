use mosaic::anim;
use mosaic::app::*;
use mosaic::png;
use mosaic::samples;
use mosaic::tilesets;
use std::time::Instant;

const HELP: &str = "\
mosaic — Wave Function Collapse with backtracking

USAGE
  mosaic overlap --sample NAME|FILE [options]     overlapping model (learn from an example image)
  mosaic tiled   --set circuit|terrain [options]  tiled model (edge-socket tilesets)
  mosaic bench   (overlap|tiled) [options]        backtracking vs restart-only over many seeds
  mosaic list                                     built-in samples and tilesets

COMMON OPTIONS
  --size WxH           overlap: output pixels (default 48x32); tiled: cells (default 24x16)
  --seed N             RNG seed (default 1)
  --wrap-out           periodic (toroidal) output
  --no-backtrack       restart on contradiction instead of backtracking
  --max-backtracks N   backtracks allowed per attempt (default 100; hybrid backtrack-then-restart)
  --restarts N         attempts before giving up (default 40)
  --pin x,y,VALUE      pre-collapse a cell; VALUE = glyph or #rrggbb (overlap), tile name (tiled). Repeatable
  --out FILE.png       output image (default out.png)
  --scale K            integer upscale of the PNG (default 8 overlap / 3 tiled)
  --anim FILE.html     write a collapse-animation flipbook
  --anim-frames N      frames in the flipbook (default 120)
  --quiet              suppress the stats line

OVERLAP OPTIONS
  --sample NAME|FILE   built-in name, a .txt ASCII-art file, or a .ppm image
  --n N                pattern size (default 3)
  --symmetry K         1..8 rotations/reflections added to the pattern set (default 1)
  --wrap-in            treat the sample as toroidal when extracting patterns
  --ground             anchor the sample's bottom-left pattern along the bottom row only
  --ascii              also print the result as text

BENCH OPTIONS
  --trials N           seeds 1..N (default 30)
";

fn die(msg: &str) -> ! {
    eprintln!("error: {}", msg);
    std::process::exit(2);
}

struct Args {
    v: Vec<String>,
}
impl Args {
    fn flag(&mut self, name: &str) -> bool {
        if let Some(i) = self.v.iter().position(|a| a == name) {
            self.v.remove(i);
            true
        } else {
            false
        }
    }
    fn opt(&mut self, name: &str) -> Option<String> {
        let i = self.v.iter().position(|a| a == name)?;
        if i + 1 >= self.v.len() {
            die(&format!("{} needs a value", name));
        }
        let val = self.v.remove(i + 1);
        self.v.remove(i);
        Some(val)
    }
    fn opts(&mut self, name: &str) -> Vec<String> {
        let mut r = vec![];
        while let Some(v) = self.opt(name) {
            r.push(v);
        }
        r
    }
    fn num<T: std::str::FromStr>(&mut self, name: &str, default: T) -> T {
        match self.opt(name) {
            None => default,
            Some(s) => s.parse().unwrap_or_else(|_| die(&format!("{} expects a number, got '{}'", name, s))),
        }
    }
}

fn parse_size(s: &str) -> (usize, usize) {
    let (a, b) = s.split_once(['x', 'X']).unwrap_or_else(|| die(&format!("--size expects WxH, got '{}'", s)));
    match (a.parse(), b.parse()) {
        (Ok(a), Ok(b)) => (a, b),
        _ => die(&format!("--size expects WxH, got '{}'", s)),
    }
}

fn common(a: &mut Args, dw: usize, dh: usize) -> Common {
    let (w, h) = a.opt("--size").map(|s| parse_size(&s)).unwrap_or((dw, dh));
    let mut c = Common::new(w, h);
    c.seed = a.num("--seed", 1u64);
    c.periodic = a.flag("--wrap-out");
    c.backtrack = !a.flag("--no-backtrack");
    c.max_backtracks = a.num("--max-backtracks", c.max_backtracks);
    c.max_restarts = a.num("--restarts", c.max_restarts);
    c.pins = a.opts("--pin");
    c
}

fn overlap_opts(a: &mut Args, c: Common) -> OverlapOpts {
    OverlapOpts {
        common: c,
        sample: a.opt("--sample").unwrap_or_else(|| die("--sample is required (see `mosaic list`)")),
        n: a.num("--n", 3usize),
        symmetry: a.num("--symmetry", 1usize),
        wrap_in: a.flag("--wrap-in"),
        ground: a.flag("--ground"),
    }
}

fn finish_args(a: &Args) {
    if let Some(x) = a.v.first() {
        die(&format!("unrecognised argument '{}'\n\n{}", x, HELP));
    }
}

fn save(rep: &Report, out: &str, scale: usize, quiet: bool, title: &str, anim_path: Option<&str>) {
    if scale == 0 || scale > 64 || rep.w * rep.h * scale * scale > 60_000_000 {
        die("--scale must be 1..64 and keep the PNG under 60 megapixels");
    }
    let (w, h, px) = png::upscale(rep.w, rep.h, &rep.px, scale);
    std::fs::write(out, png::encode(w, h, &px)).unwrap_or_else(|e| die(&format!("cannot write {}: {}", out, e)));
    if let Some(p) = anim_path {
        let info = format!("{} decisions · {} backtracks · {} restarts", rep.stats.decisions, rep.stats.backtracks, rep.stats.restarts);
        let page = anim::html(title, &info, &rep.frames, scale.max(1));
        std::fs::write(p, page).unwrap_or_else(|e| die(&format!("cannot write {}: {}", p, e)));
        if !quiet {
            println!("wrote {} ({} frames)", p, rep.frames.len());
        }
    }
    if !quiet {
        println!(
            "wrote {} ({}x{}) | grid {}x{} | {} patterns | {} decisions, {} backtracks, {} restarts | verify: {}",
            out,
            w,
            h,
            rep.grid.0,
            rep.grid.1,
            rep.patterns,
            rep.stats.decisions,
            rep.stats.backtracks,
            rep.stats.restarts,
            if rep.violations == 0 { "OK".to_string() } else { format!("{} VIOLATIONS (first at {:?})", rep.violations, rep.first_violation) }
        );
    }
}

fn main() {
    let mut a = Args { v: std::env::args().skip(1).collect() };
    if a.v.is_empty() || a.flag("--help") || a.flag("-h") {
        print!("{}", HELP);
        return;
    }
    let cmd = a.v.remove(0);
    match cmd.as_str() {
        "list" => {
            println!("overlap samples:");
            for (n, d) in samples::list() {
                println!("  {:<9} {}", n, d);
            }
            println!("tilesets:");
            for (n, d) in tilesets::names() {
                println!("  {:<9} {}", n, d);
                let ts = tilesets::get(n).unwrap();
                let mut bases: Vec<String> = ts.tiles.iter().map(|t| t.name.rsplit_once("_r").map(|x| x.0.to_string()).unwrap_or(t.name.clone())).collect();
                bases.dedup();
                if bases.len() <= 12 {
                    println!("            tiles: {}", bases.join(", "));
                } else {
                    println!("            tiles: t<nw><ne><se><sw> with digits 0=water 1=sand 2=grass, e.g. t0012");
                }
            }
        }
        "overlap" => {
            let c = common(&mut a, 48, 32);
            let mut o = overlap_opts(&mut a, c);
            let out = a.opt("--out").unwrap_or_else(|| "out.png".into());
            let scale = a.num("--scale", 8usize);
            let anim_path = a.opt("--anim");
            let frames = a.num("--anim-frames", 120usize);
            let quiet = a.flag("--quiet");
            let ascii = a.flag("--ascii");
            finish_args(&a);
            if anim_path.is_some() {
                if !(2..=1000).contains(&frames) {
                    die("--anim-frames must be between 2 and 1000");
                }
                o.common.anim_frames = frames;
            }
            let rep = run_overlap(&o).unwrap_or_else(|e| die(&e));
            save(&rep, &out, scale, quiet, &format!("Mosaic · {}", o.sample), anim_path.as_deref());
            if ascii {
                match samples::load(&o.sample) {
                    Ok(img) if !img.glyphs.is_empty() => print!("{}", rep.ascii.as_deref().unwrap_or("")),
                    _ => eprintln!("note: --ascii only works for ASCII-art samples (image samples have no glyphs)"),
                }
            }
            if rep.violations > 0 {
                std::process::exit(1);
            }
        }
        "tiled" => {
            let c = common(&mut a, 24, 16);
            let set = a.opt("--set").unwrap_or_else(|| die("--set is required (circuit | terrain)"));
            let mut o = TiledOpts { common: c, set };
            let out = a.opt("--out").unwrap_or_else(|| "out.png".into());
            let scale = a.num("--scale", 3usize);
            let anim_path = a.opt("--anim");
            let frames = a.num("--anim-frames", 120usize);
            let quiet = a.flag("--quiet");
            finish_args(&a);
            if anim_path.is_some() {
                if !(2..=1000).contains(&frames) {
                    die("--anim-frames must be between 2 and 1000");
                }
                o.common.anim_frames = frames;
            }
            let rep = run_tiled(&o).unwrap_or_else(|e| die(&e));
            save(&rep, &out, scale, quiet, &format!("Mosaic · {}", o.set), anim_path.as_deref());
            if rep.violations > 0 {
                std::process::exit(1);
            }
        }
        "bench" => bench(a),
        other => die(&format!("unknown command '{}'\n\n{}", other, HELP)),
    }
}

fn bench(mut a: Args) {
    if a.v.is_empty() {
        die("bench needs a model: overlap or tiled");
    }
    let kind = a.v.remove(0);
    let trials = a.num("--trials", 30u64);
    let (dw, dh) = if kind == "tiled" { (24, 16) } else { (48, 32) };
    let c = common(&mut a, dw, dh);
    let ov = if kind == "overlap" { Some(overlap_opts(&mut a, c.clone())) } else { None };
    let set = if kind == "tiled" { Some(a.opt("--set").unwrap_or_else(|| die("--set is required"))) } else { None };
    finish_args(&a);
    if ov.is_none() && set.is_none() {
        die("bench model must be overlap or tiled");
    }
    println!("{:<14} {:>8} {:>10} {:>11} {:>11} {:>10}", "mode", "solved", "avg ms", "decisions", "backtracks", "restarts");
    for backtrack in [true, false] {
        let (mut ok, mut dec, mut bt, mut rs) = (0u64, 0usize, 0usize, 0usize);
        let t0 = Instant::now();
        for seed in 1..=trials {
            let mut cc = c.clone();
            cc.seed = seed;
            cc.backtrack = backtrack;
            let r = if let Some(o) = &ov {
                let mut o = o.clone();
                o.common = cc;
                run_overlap(&o)
            } else {
                run_tiled(&TiledOpts { common: cc, set: set.clone().unwrap() })
            };
            if let Ok(rep) = r {
                if rep.violations == 0 {
                    ok += 1;
                    dec += rep.stats.decisions;
                    bt += rep.stats.backtracks;
                    rs += rep.stats.restarts;
                }
            }
        }
        let ms = t0.elapsed().as_secs_f64() * 1000.0 / trials as f64;
        let d = ok.max(1) as f64;
        println!(
            "{:<14} {:>5}/{:<3} {:>10.1} {:>11.0} {:>11.1} {:>10.2}",
            if backtrack { "backtracking" } else { "restart-only" },
            ok,
            trials,
            ms,
            dec as f64 / d,
            bt as f64 / d,
            rs as f64 / d
        );
    }
}
