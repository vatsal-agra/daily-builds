use kripke::fuzz::{cross_check, gen_model, Rng};

#[test]
fn differential_random_models() {
    let n: u64 = std::env::var("KRIPKE_FUZZ")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(150);
    let mut failures = vec![];
    for seed in 1..=n {
        let src = gen_model(seed);
        let mut rng = Rng(seed * 7919 + 13);
        match cross_check(&src, &mut rng) {
            Ok(bad) if bad.is_empty() => {}
            Ok(bad) => failures.push(format!("seed {}:\n  {}\n{}", seed, bad.join("\n  "), src)),
            Err(e) => failures.push(format!("seed {}: {}", seed, e)),
        }
        if failures.len() >= 3 {
            break;
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n-----\n"));
}
