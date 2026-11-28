use sux::bench::{render, run};

#[test]
fn bench_reports_real_and_sane_numbers() {
    let rows = run(0.05);
    assert!(rows.len() >= 10);
    let find = |s: &str, q: &str| rows.iter().find(|r| r.structure.starts_with(s) && r.query.starts_with(q)).unwrap();
    assert!(find("RankSelect", "rank1").bits_per_item < 1.35);
    assert!(find("Rrr", "rank1").bits_per_item < find("Rrr", "rank1").naive_bits_per_item);
    assert!(find("EliasFano", "get").bits_per_item < 64.0 / 2.0);
    let (plain, comp) = (find("FmIndex plain", "count"), find("FmIndex RRR", "count"));
    assert!(comp.bits_per_item < plain.bits_per_item);
    // The FM-index must beat a linear scan on a count query (it is O(m log sigma), the scan O(n)).
    assert!(plain.ns_per_query < plain.naive_ns.unwrap());
    let text = render(&rows);
    assert!(text.contains("FmIndex") && text.contains("Louds"));
    assert!(rows.iter().all(|r| r.ns_per_query.is_finite() && r.ns_per_query > 0.0));
}
