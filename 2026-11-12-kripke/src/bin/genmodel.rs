fn main() {
    let seed: u64 = std::env::args().nth(1).unwrap().parse().unwrap();
    print!("{}", kripke::fuzz::gen_model(seed));
}
