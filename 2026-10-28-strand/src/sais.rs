//! SA-IS (Nong, Zhang & Chan 2009): linear-time suffix-array construction by
//! induced sorting. The input must end with a unique smallest sentinel (0).

const EMPTY: usize = usize::MAX;

/// Suffix array of `s` over alphabet [0,k). `s` must end with a unique 0.
pub fn suffix_array(s: &[u32], k: usize) -> Vec<usize> {
    assert!(!s.is_empty() && *s.last().unwrap() == 0, "text must end with the sentinel 0");
    debug_assert!(s[..s.len() - 1].iter().all(|&c| c != 0), "sentinel must be unique");
    let mut sa = vec![EMPTY; s.len()];
    sa_is(s, &mut sa, k);
    sa
}

fn buckets(s: &[u32], k: usize, ends: bool) -> Vec<usize> {
    let mut b = vec![0usize; k];
    for &c in s {
        b[c as usize] += 1;
    }
    let mut sum = 0;
    for x in b.iter_mut() {
        sum += *x;
        *x = if ends { sum } else { sum - *x };
    }
    b
}

fn induce(s: &[u32], sa: &mut [usize], t: &[bool], k: usize) {
    let n = s.len();
    let mut b = buckets(s, k, false);
    for i in 0..n {
        let j = sa[i];
        if j != EMPTY && j > 0 && !t[j - 1] {
            let c = s[j - 1] as usize;
            sa[b[c]] = j - 1;
            b[c] += 1;
        }
    }
    let mut b = buckets(s, k, true);
    for i in (0..n).rev() {
        let j = sa[i];
        if j != EMPTY && j > 0 && t[j - 1] {
            let c = s[j - 1] as usize;
            b[c] -= 1;
            sa[b[c]] = j - 1;
        }
    }
}

fn sa_is(s: &[u32], sa: &mut [usize], k: usize) {
    let n = s.len();
    if n == 1 {
        sa[0] = 0;
        return;
    }
    // t[i] = true for S-type suffixes
    let mut t = vec![false; n];
    t[n - 1] = true;
    for i in (0..n - 1).rev() {
        t[i] = s[i] < s[i + 1] || (s[i] == s[i + 1] && t[i + 1]);
    }
    let is_lms = |i: usize| i > 0 && t[i] && !t[i - 1];

    // Stage 1: sort LMS substrings by induced sorting.
    sa.iter_mut().for_each(|x| *x = EMPTY);
    let mut b = buckets(s, k, true);
    for i in 1..n {
        if is_lms(i) {
            let c = s[i] as usize;
            b[c] -= 1;
            sa[b[c]] = i;
        }
    }
    induce(s, sa, &t, k);

    // Name the LMS substrings.
    let lms_sorted: Vec<usize> = sa.iter().copied().filter(|&p| p != EMPTY && is_lms(p)).collect();
    let n1 = lms_sorted.len();
    let mut name_of = vec![EMPTY; n];
    let mut name = 0usize;
    let mut prev = EMPTY;
    for &pos in &lms_sorted {
        let mut diff = prev == EMPTY;
        if !diff {
            let mut d = 0;
            loop {
                if s[pos + d] != s[prev + d] || t[pos + d] != t[prev + d] {
                    diff = true;
                    break;
                }
                if d > 0 && (is_lms(pos + d) || is_lms(prev + d)) {
                    break;
                }
                d += 1;
            }
        }
        if diff {
            name += 1;
            prev = pos;
        }
        name_of[pos] = name - 1;
    }
    let lms_pos: Vec<usize> = (1..n).filter(|&i| is_lms(i)).collect();
    let s1: Vec<u32> = lms_pos.iter().map(|&p| name_of[p] as u32).collect();

    // Stage 2: sort the reduced problem.
    let mut sa1 = vec![EMPTY; n1];
    if name < n1 {
        sa_is(&s1, &mut sa1, name);
    } else {
        for (i, &c) in s1.iter().enumerate() {
            sa1[c as usize] = i;
        }
    }

    // Stage 3: induce the full SA from the sorted LMS suffixes.
    sa.iter_mut().for_each(|x| *x = EMPTY);
    let mut b = buckets(s, k, true);
    for i in (0..n1).rev() {
        let j = lms_pos[sa1[i]];
        let c = s[j] as usize;
        b[c] -= 1;
        sa[b[c]] = j;
    }
    induce(s, sa, &t, k);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;

    fn naive(s: &[u32]) -> Vec<usize> {
        let mut v: Vec<usize> = (0..s.len()).collect();
        v.sort_by(|&a, &b| s[a..].cmp(&s[b..]));
        v
    }

    #[test]
    fn banana() {
        // "banana$" with a=1 b=2 n=3
        let s = [2, 1, 3, 1, 3, 1, 0];
        assert_eq!(suffix_array(&s, 4), vec![6, 5, 3, 1, 0, 4, 2]);
    }

    #[test]
    fn tiny_and_degenerate() {
        assert_eq!(suffix_array(&[0], 1), vec![0]);
        assert_eq!(suffix_array(&[1, 0], 2), vec![1, 0]);
        let all_same = [1u32, 1, 1, 1, 1, 1, 0];
        assert_eq!(suffix_array(&all_same, 2), naive(&all_same));
    }

    #[test]
    fn random_matches_naive() {
        let mut r = Rng::new(7);
        for trial in 0..400 {
            let n = 1 + r.below(200);
            let k = 2 + r.below(4);
            let mut s: Vec<u32> = (0..n).map(|_| 1 + r.below(k - 1) as u32).collect();
            if trial % 5 == 0 {
                // highly repetitive
                let unit: Vec<u32> = s.iter().take(1 + r.below(5)).copied().collect();
                s = (0..n).map(|i| unit[i % unit.len()]).collect();
            }
            s.push(0);
            assert_eq!(suffix_array(&s, k), naive(&s), "trial {} s={:?}", trial, s);
        }
    }

    #[test]
    fn large_repetitive_is_fast_and_correct() {
        let mut r = Rng::new(3);
        let unit: Vec<u32> = (0..300).map(|_| 1 + r.below(4) as u32).collect();
        let mut s: Vec<u32> = Vec::new();
        for _ in 0..30 {
            s.extend(&unit);
        }
        s.push(0);
        let sa = suffix_array(&s, 5);
        for w in sa.windows(2) {
            assert!(s[w[0]..] < s[w[1]..]);
        }
    }
}
