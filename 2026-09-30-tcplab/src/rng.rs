//! Tiny deterministic PRNG (splitmix64). Same seed → same simulation, forever.

#[derive(Clone, Debug)]
pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed ^ 0x9E37_79B9_7F4A_7C15)
    }
    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    /// Uniform in [0,1).
    pub fn f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }
    /// True with probability p.
    pub fn chance(&mut self, p: f64) -> bool {
        p > 0.0 && self.f64() < p
    }
    /// Uniform integer in [0, n). n must be > 0.
    pub fn below(&mut self, n: u64) -> u64 {
        self.next_u64() % n
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn deterministic() {
        let mut a = Rng::new(7);
        let mut b = Rng::new(7);
        for _ in 0..100 {
            assert_eq!(a.next_u64(), b.next_u64());
        }
        assert_ne!(Rng::new(7).next_u64(), Rng::new(8).next_u64());
    }
    #[test]
    fn f64_range_and_chance() {
        let mut r = Rng::new(1);
        let mut hits = 0;
        for _ in 0..100_000 {
            let x = r.f64();
            assert!((0.0..1.0).contains(&x));
            if r.chance(0.1) {
                hits += 1;
            }
        }
        assert!((8_000..12_000).contains(&hits), "hits={hits}");
        assert!(!r.chance(0.0));
    }
}
