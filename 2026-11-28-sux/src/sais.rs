//! SA-IS: linear-time suffix array construction (Nong, Zhang & Chan 2009).
const NONE: usize = usize::MAX;

/// Suffix array of `s`, where every symbol is in `0..=upper`.
pub fn suffix_array(s: &[usize], upper: usize) -> Vec<usize> {
    let n = s.len();
    match n {
        0 => return vec![],
        1 => return vec![0],
        2 => return if s[0] < s[1] { vec![0, 1] } else { vec![1, 0] },
        _ => {}
    }
    let mut sa = vec![NONE; n];
    // ls[i] == true  <=>  suffix i is S-type.
    let mut ls = vec![false; n];
    for i in (0..n - 1).rev() {
        ls[i] = if s[i] == s[i + 1] { ls[i + 1] } else { s[i] < s[i + 1] };
    }
    let mut sum_l = vec![0usize; upper + 2];
    let mut sum_s = vec![0usize; upper + 2];
    for i in 0..n {
        if !ls[i] {
            sum_s[s[i]] += 1;
        } else {
            sum_l[s[i] + 1] += 1;
        }
    }
    for i in 0..=upper {
        sum_s[i] += sum_l[i];
        sum_l[i + 1] += sum_s[i];
    }

    let induce = |lms: &[usize], sa: &mut Vec<usize>| {
        sa.iter_mut().for_each(|x| *x = NONE);
        let mut buf = sum_s.clone();
        for &d in lms {
            if d == n {
                continue;
            }
            sa[buf[s[d]]] = d;
            buf[s[d]] += 1;
        }
        buf.clone_from(&sum_l);
        sa[buf[s[n - 1]]] = n - 1;
        buf[s[n - 1]] += 1;
        for i in 0..n {
            let v = sa[i];
            if v != NONE && v >= 1 && !ls[v - 1] {
                sa[buf[s[v - 1]]] = v - 1;
                buf[s[v - 1]] += 1;
            }
        }
        buf.clone_from(&sum_l);
        for i in (0..n).rev() {
            let v = sa[i];
            if v != NONE && v >= 1 && ls[v - 1] {
                buf[s[v - 1] + 1] -= 1;
                sa[buf[s[v - 1] + 1]] = v - 1;
            }
        }
    };

    let mut lms_map = vec![NONE; n + 1];
    let mut m = 0;
    for i in 1..n {
        if !ls[i - 1] && ls[i] {
            lms_map[i] = m;
            m += 1;
        }
    }
    let mut lms = Vec::with_capacity(m);
    for i in 1..n {
        if !ls[i - 1] && ls[i] {
            lms.push(i);
        }
    }
    induce(&lms, &mut sa);

    if m > 0 {
        let mut sorted_lms = Vec::with_capacity(m);
        for &v in &sa {
            if v != NONE && lms_map[v] != NONE {
                sorted_lms.push(v);
            }
        }
        let mut rec_s = vec![0usize; m];
        let mut rec_upper = 0usize;
        rec_s[lms_map[sorted_lms[0]]] = 0;
        for i in 1..m {
            let (mut l, mut r) = (sorted_lms[i - 1], sorted_lms[i]);
            let end_l = if lms_map[l] + 1 < m { lms[lms_map[l] + 1] } else { n };
            let end_r = if lms_map[r] + 1 < m { lms[lms_map[r] + 1] } else { n };
            let mut same = true;
            if end_l - l != end_r - r {
                same = false;
            } else {
                while l < end_l {
                    if s[l] != s[r] {
                        break;
                    }
                    l += 1;
                    r += 1;
                }
                if l == n || s[l] != s[r] {
                    same = false;
                }
            }
            if !same {
                rec_upper += 1;
            }
            rec_s[lms_map[sorted_lms[i]]] = rec_upper;
        }
        let rec_sa = suffix_array(&rec_s, rec_upper);
        for i in 0..m {
            sorted_lms[i] = lms[rec_sa[i]];
        }
        induce(&sorted_lms, &mut sa);
    }
    sa
}

/// Suffix array of raw bytes (no sentinel; shorter suffix sorts first on ties).
pub fn suffix_array_bytes(t: &[u8]) -> Vec<usize> {
    let s: Vec<usize> = t.iter().map(|&b| b as usize).collect();
    suffix_array(&s, 255)
}
