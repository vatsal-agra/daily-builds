use kripke::driver::{run, Options};
use kripke::report::render_report;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = &args[1];
    let src = std::fs::read_to_string(path).unwrap();
    let opts = Options { reorder: args.iter().any(|a| a == "--reorder"), gc_stress: args.iter().any(|a| a == "--gc-stress"), lax: args.iter().any(|a| a == "--lax") };
    match run(&src, &opts) {
        Ok(r) => {
            print!("{}", render_report(&r, true));
            std::process::exit(if r.all_hold() { 0 } else { 1 });
        }
        Err(e) => {
            eprint!("{}", e.render(&src, path));
            std::process::exit(2);
        }
    }
}
