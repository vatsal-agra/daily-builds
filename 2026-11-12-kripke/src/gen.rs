//! Scalable model families, printed as ordinary model text.

use std::fmt::Write;

pub const FAMILIES: &[(&str, &str)] = &[
    ("philosophers", "N dining philosophers, everyone takes the left fork first (deadlocks)"),
    ("philosophers-fixed", "N dining philosophers, the last one takes the right fork first (deadlock-free)"),
    ("tokenring", "N-node token ring mutual exclusion"),
    ("counter", "N-bit wrap-around counter with a reset input"),
    ("comparator", "two N-bit registers constrained equal: BDD size explodes unless variables are interleaved (try --reorder)"),
    ("lfsr", "N-bit maximal-length LFSR (3 <= N <= 16): reachable states must be 2^N - 1"),
];

pub fn generate(name: &str, n: usize) -> Result<String, String> {
    match name {
        "philosophers" => philosophers(n, false),
        "philosophers-fixed" => philosophers(n, true),
        "tokenring" => tokenring(n),
        "counter" => counter(n),
        "comparator" => comparator(n),
        "lfsr" => lfsr(n),
        _ => Err(format!(
            "unknown family '{}'; available: {}",
            name,
            FAMILIES.iter().map(|(n, _)| *n).collect::<Vec<_>>().join(", ")
        )),
    }
}

fn philosophers(n: usize, fixed: bool) -> Result<String, String> {
    if !(2..=12).contains(&n) {
        return Err("philosophers: N must be between 2 and 12".into());
    }
    let mut s = String::new();
    let _ = writeln!(s, "-- {} dining philosophers ({}). Philosopher i uses forks a(i) then b(i).", n, if fixed { "last one reversed: deadlock-free" } else { "all left-handed: can deadlock" });
    let _ = writeln!(s, "-- A scheduler variable picks who moves; FAIRNESS makes it pick everyone infinitely often.");
    let _ = writeln!(s, "MODULE main\nVAR\n  sched : 0..{};", n - 1);
    for i in 0..n {
        let _ = writeln!(s, "  p{} : {{think, left, eat}};", i);
    }
    for i in 0..n {
        let _ = writeln!(s, "  f{} : boolean;", i);
    }
    let first = |i: usize| if fixed && i == n - 1 { (i + 1) % n } else { i };
    let second = |i: usize| if fixed && i == n - 1 { i } else { (i + 1) % n };
    let _ = writeln!(s, "ASSIGN\n  init(sched) := 0;");
    let sched_set: Vec<String> = (0..n).map(|i| i.to_string()).collect();
    let _ = writeln!(s, "  next(sched) := {{{}}};", sched_set.join(", "));
    for i in 0..n {
        let (a, b) = (first(i), second(i));
        let _ = writeln!(s, "  init(p{}) := think;", i);
        let _ = writeln!(
            s,
            "  next(p{i}) := case\n    sched != {i}            : p{i};\n    p{i} = think & !f{a}    : {{think, left}};\n    p{i} = left & !f{b}     : eat;\n    p{i} = eat              : think;\n    TRUE                    : p{i};\n  esac;",
            i = i,
            a = a,
            b = b
        );
    }
    for k in 0..n {
        let _ = writeln!(s, "  init(f{}) := FALSE;", k);
        let _ = writeln!(s, "  next(f{}) := case", k);
        for i in 0..n {
            let (a, b) = (first(i), second(i));
            if a == k {
                let _ = writeln!(s, "    sched = {i} & p{i} = think & next(p{i}) = left : TRUE;", i = i);
            }
            if b == k {
                let _ = writeln!(s, "    sched = {i} & p{i} = left & !f{k} : TRUE;", i = i, k = k);
            }
            if a == k || b == k {
                let _ = writeln!(s, "    sched = {i} & p{i} = eat : FALSE;", i = i);
            }
        }
        let _ = writeln!(s, "    TRUE : f{};\n  esac;", k);
    }
    for i in 0..n {
        let _ = writeln!(s, "FAIRNESS sched = {}", i);
    }
    let pairs: Vec<String> = (0..n).map(|i| format!("!(p{} = eat & p{} = eat)", i, (i + 1) % n)).collect();
    let _ = writeln!(s, "INVARSPEC NAME neighbours_never_both_eat := {}", pairs.join(" & "));
    let _ = writeln!(s, "SPEC NAME philosopher0_can_eat := EF p0 = eat");
    let _ = writeln!(s, "SPEC NAME always_possible_to_eat_again := AG EF p0 = eat    -- needs --stutter to see a deadlock");
    let _ = writeln!(s, "LTLSPEC NAME no_starvation_0 := G (p0 = left -> F p0 = eat)");
    let _ = writeln!(s, "LTLSPEC NAME everyone_eats_infinitely_often := G F p0 = eat");
    Ok(s)
}

fn tokenring(n: usize) -> Result<String, String> {
    if !(2..=16).contains(&n) {
        return Err("tokenring: N must be between 2 and 16".into());
    }
    let mut s = String::new();
    let _ = writeln!(s, "-- token ring mutual exclusion, {} nodes; every node moves in lock step", n);
    let _ = writeln!(s, "MODULE main\nVAR\n  tok : 0..{};", n - 1);
    for i in 0..n {
        let _ = writeln!(s, "  s{} : {{idle, wait, crit}};", i);
    }
    let _ = writeln!(s, "ASSIGN\n  init(tok) := 0;");
    for i in 0..n {
        let _ = writeln!(s, "  init(s{i}) := idle;\n  next(s{i}) := case\n    s{i} = idle           : {{idle, wait}};\n    s{i} = wait & tok = {i} : crit;\n    s{i} = crit           : idle;\n    TRUE                  : s{i};\n  esac;", i = i);
    }
    let _ = writeln!(s, "  next(tok) := case");
    for i in 0..n {
        let _ = writeln!(s, "    tok = {} & s{} = idle : {};", i, i, (i + 1) % n);
    }
    let _ = writeln!(s, "    TRUE : tok;\n  esac;");
    let mut pairs = vec![];
    for i in 0..n {
        for j in i + 1..n {
            pairs.push(format!("!(s{} = crit & s{} = crit)", i, j));
        }
    }
    let _ = writeln!(s, "INVARSPEC NAME mutual_exclusion := {}", pairs.join(" & "));
    for i in 0..n.min(3) {
        let _ = writeln!(s, "SPEC NAME node{i}_served := AG (s{i} = wait -> AF s{i} = crit)", i = i);
    }
    let _ = writeln!(s, "SPEC NAME token_always_moves_on := AG AF tok = 0");
    let _ = writeln!(s, "LTLSPEC NAME ltl_served := G (s0 = wait -> F s0 = crit)");
    Ok(s)
}

fn counter(n: usize) -> Result<String, String> {
    if !(1..=24).contains(&n) {
        return Err("counter: N must be between 1 and 24".into());
    }
    let max = (1u64 << n) - 1;
    let mut s = String::new();
    let _ = writeln!(s, "-- {}-bit counter with a synchronous reset input", n);
    let _ = writeln!(s, "MODULE main\nIVAR reset : boolean;\nVAR n : 0..{};", max);
    let _ = writeln!(s, "ASSIGN\n  init(n) := 0;\n  next(n) := case reset : 0; TRUE : (n + 1) mod {}; esac;", max + 1);
    let _ = writeln!(s, "INVARSPEC NAME in_range := n <= {}", max);
    let _ = writeln!(s, "SPEC NAME wraps := AG EF n = 0");
    let _ = writeln!(s, "SPEC NAME increments := AG (n < {} -> EX n = n + 1)", max);
    let _ = writeln!(s, "LTLSPEC NAME returns_to_zero := G F n = 0");
    let _ = writeln!(s, "INVARSPEC NAME never_reaches_max := n != {}   -- false: shortest counterexample counts up", max);
    Ok(s)
}

fn comparator(n: usize) -> Result<String, String> {
    if !(1..=24).contains(&n) {
        return Err("comparator: N must be between 1 and 24".into());
    }
    let mut s = String::new();
    let _ = writeln!(s, "-- two {}-bit registers that start equal and never change.", n);
    let _ = writeln!(s, "-- The reachable set is the comparator x = y: exponential BDD with x-bits-then-y-bits, linear when interleaved.");
    let _ = writeln!(s, "MODULE main\nVAR");
    for i in 0..n {
        let _ = writeln!(s, "  x{} : boolean;", i);
    }
    for i in 0..n {
        let _ = writeln!(s, "  y{} : boolean;", i);
    }
    let eqs: Vec<String> = (0..n).map(|i| format!("(x{} <-> y{})", i, i)).collect();
    let _ = writeln!(s, "INIT {}", eqs.join(" & "));
    let _ = writeln!(s, "ASSIGN");
    for i in 0..n {
        let _ = writeln!(s, "  next(x{i}) := x{i};\n  next(y{i}) := y{i};", i = i);
    }
    let _ = writeln!(s, "INVARSPEC NAME registers_stay_equal := {}", eqs.join(" & "));
    Ok(s)
}

fn lfsr(n: usize) -> Result<String, String> {
    let taps: &[usize] = match n {
        3 => &[3, 2],
        4 => &[4, 3],
        5 => &[5, 3],
        6 => &[6, 5],
        7 => &[7, 6],
        8 => &[8, 6, 5, 4],
        9 => &[9, 5],
        10 => &[10, 7],
        11 => &[11, 9],
        12 => &[12, 11, 10, 4],
        13 => &[13, 12, 11, 8],
        14 => &[14, 13, 12, 2],
        15 => &[15, 14],
        16 => &[16, 15, 13, 4],
        _ => return Err("lfsr: N must be between 3 and 16".into()),
    };
    let mut s = String::new();
    let _ = writeln!(s, "-- {}-bit Fibonacci LFSR, taps {:?}: a maximal-length one visits 2^{} - 1 = {} states", n, taps, n, (1u64 << n) - 1);
    let _ = writeln!(s, "MODULE main\nVAR");
    for i in 1..=n {
        let _ = writeln!(s, "  s{} : boolean;", i);
    }
    let _ = writeln!(s, "ASSIGN");
    for i in 1..=n {
        let _ = writeln!(s, "  init(s{}) := {};", i, if i == 1 { "TRUE" } else { "FALSE" });
    }
    let fb: Vec<String> = taps.iter().map(|t| format!("s{}", t)).collect();
    let _ = writeln!(s, "  next(s1) := {};", fb.join(" xor "));
    for i in 2..=n {
        let _ = writeln!(s, "  next(s{}) := s{};", i, i - 1);
    }
    let zero: Vec<String> = (1..=n).map(|i| format!("!s{}", i)).collect();
    let _ = writeln!(s, "INVARSPEC NAME never_all_zero := !({})", zero.join(" & "));
    // AG AF on a 2^N-long cycle nests two fixpoints of length 2^N: only worth asking for small N.
    if n <= 9 {
        let seed = format!("s1 & {}", (2..=n).map(|i| format!("!s{}", i)).collect::<Vec<_>>().join(" & "));
        let _ = writeln!(s, "SPEC NAME seed_recurs := AG AF ({})", seed);
        let _ = writeln!(s, "LTLSPEC NAME ltl_seed_recurs := G F ({})", seed);
    }
    Ok(s)
}
