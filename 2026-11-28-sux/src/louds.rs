//! LOUDS (Level-Order Unary Degree Sequence) succinct trie over byte strings.
//!
//! The tree shape costs 2 bits per node; edge labels cost one byte per node; "is a key ends
//! here" costs one bit per node. Keys get dense ids 0..n (terminal nodes in level order),
//! so the trie doubles as a minimal perfect hash with reverse lookup.
use crate::bitvec::{BitVec, RankSelect};
use crate::util::*;

const MAGIC: &[u8; 4] = b"SUXT";

#[derive(Debug)]
pub struct Louds {
    shape: RankSelect,    // "10" + for each node in level order: deg × 1, then 0
    labels: Vec<u8>,      // labels[node - 2] = edge label into node (node ids start at 1 = root)
    terminal: RankSelect, // bit (node - 1): a key ends at this node
    nodes: usize,
}

impl Louds {
    /// Build from any collection of byte strings (sorted and de-duplicated internally).
    pub fn build<K: AsRef<[u8]>>(keys: &[K]) -> Louds {
        let mut ks: Vec<&[u8]> = keys.iter().map(|k| k.as_ref()).collect();
        ks.sort_unstable();
        ks.dedup();
        let mut shape = BitVec::new();
        shape.push(true);
        shape.push(false);
        let mut labels = Vec::new();
        let mut term = BitVec::new();
        let mut queue = std::collections::VecDeque::new();
        queue.push_back((0usize, ks.len(), 0usize));
        let mut nodes = 0usize;
        while let Some((mut lo, hi, d)) = queue.pop_front() {
            nodes += 1;
            if lo < hi && ks[lo].len() == d {
                term.push(true);
                lo += 1; // the key equal to this prefix sorts first
            } else {
                term.push(false);
            }
            let mut i = lo;
            while i < hi {
                let b = ks[i][d];
                let mut j = i + 1;
                while j < hi && ks[j][d] == b {
                    j += 1;
                }
                shape.push(true);
                labels.push(b);
                queue.push_back((i, j, d + 1));
                i = j;
            }
            shape.push(false);
        }
        Louds { shape: RankSelect::new(shape), labels, terminal: RankSelect::new(term), nodes }
    }

    pub fn num_nodes(&self) -> usize {
        self.nodes
    }
    pub fn len(&self) -> usize {
        self.terminal.count_ones()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// (first child node id, number of children) of node `x`.
    fn children(&self, x: usize) -> (usize, usize) {
        let start = self.shape.select0(x - 1).unwrap() + 1;
        let end = self.shape.select0(x).unwrap();
        (self.shape.rank1(start) + 1, end - start)
    }
    fn label(&self, node: usize) -> u8 {
        self.labels[node - 2]
    }

    fn child(&self, x: usize, b: u8) -> Option<usize> {
        let (first, deg) = self.children(x);
        let ls = &self.labels[first - 2..first - 2 + deg];
        ls.binary_search(&b).ok().map(|i| first + i)
    }

    fn node_of(&self, key: &[u8]) -> Option<usize> {
        let mut x = 1;
        for &b in key {
            x = self.child(x, b)?;
        }
        Some(x)
    }

    /// Dense id (0..len) of `key`, or None if absent.
    pub fn id_of(&self, key: &[u8]) -> Option<usize> {
        let x = self.node_of(key)?;
        self.terminal.get(x - 1).then(|| self.terminal.rank1(x - 1))
    }
    pub fn contains(&self, key: &[u8]) -> bool {
        self.id_of(key).is_some()
    }

    /// Inverse of `id_of`.
    pub fn key_of(&self, id: usize) -> Option<Vec<u8>> {
        let mut x = self.terminal.select1(id)? + 1;
        let mut key = Vec::new();
        while x != 1 {
            key.push(self.label(x));
            let p = self.shape.select1(x - 1)?; // the 1-bit that introduces node x
            x = self.shape.rank0(p); // parent = zeros before it
        }
        key.reverse();
        Some(key)
    }

    /// Up to `limit` keys starting with `prefix`, in lexicographic order.
    pub fn complete(&self, prefix: &[u8], limit: usize) -> Vec<Vec<u8>> {
        let mut out = Vec::new();
        let Some(start) = self.node_of(prefix) else { return out };
        let mut path = prefix.to_vec();
        self.dfs(start, &mut path, limit, &mut out);
        out
    }
    fn dfs(&self, x: usize, path: &mut Vec<u8>, limit: usize, out: &mut Vec<Vec<u8>>) {
        if out.len() >= limit {
            return;
        }
        if self.terminal.get(x - 1) {
            out.push(path.clone());
        }
        let (first, deg) = self.children(x);
        for i in 0..deg {
            if out.len() >= limit {
                return;
            }
            path.push(self.label(first + i));
            self.dfs(first + i, path, limit, out);
            path.pop();
        }
    }

    /// Number of keys with this prefix.
    pub fn count_prefix(&self, prefix: &[u8]) -> usize {
        let Some(start) = self.node_of(prefix) else { return 0 };
        let mut stack = vec![start];
        let mut n = 0;
        while let Some(x) = stack.pop() {
            n += usize::from(self.terminal.get(x - 1));
            let (first, deg) = self.children(x);
            stack.extend(first..first + deg);
        }
        n
    }

    pub fn total_bits(&self) -> usize {
        self.shape.total_bits() + self.labels.len() * 8 + self.terminal.total_bits()
    }

    pub fn save_bytes(&self) -> Vec<u8> {
        let mut w = Writer::new();
        self.write(&mut w);
        seal(MAGIC, &w.buf)
    }
    pub fn load_bytes(data: &[u8]) -> Result<Self> {
        let mut r = Reader::new(unseal(MAGIC, data)?);
        let t = Self::read(&mut r)?;
        if r.remaining() != 0 {
            return Err(Error::Corrupt("trailing bytes".into()));
        }
        Ok(t)
    }
}

impl Ser for Louds {
    fn write(&self, w: &mut Writer) {
        self.shape.write(w);
        w.bytes(&self.labels);
        self.terminal.write(w);
    }
    fn read(r: &mut Reader) -> Result<Self> {
        let shape = RankSelect::read(r)?;
        let labels = r.bytes()?;
        let terminal = RankSelect::read(r)?;
        let nodes = terminal.len();
        let bad = |m: &str| Err(Error::Corrupt(format!("louds: {m}")));
        if nodes == 0 || shape.len() != 2 * nodes + 1 || shape.count_ones() != nodes || labels.len() != nodes - 1 {
            return bad("size mismatch");
        }
        if !shape.get(0) || shape.get(1) {
            return bad("missing super-root");
        }
        // Every node k must already have been introduced (a 1-bit) before its own block ends,
        // otherwise navigation would run off the sequence.
        for k in 1..=nodes {
            let z = shape.select0(k).ok_or_else(|| Error::Corrupt("louds: too few blocks".into()))?;
            if shape.rank1(z) < k {
                return bad("node used before it is introduced");
            }
        }
        // Sibling labels must be strictly increasing (binary search depends on it).
        for x in 1..=nodes {
            let start = shape.select0(x - 1).unwrap() + 1;
            let end = shape.select0(x).unwrap();
            let first = shape.rank1(start) + 1;
            let deg = end - start;
            if deg > 0 && (first < 2 || first - 2 + deg > labels.len() || labels[first - 2..first - 2 + deg].windows(2).any(|w| w[0] >= w[1])) {
                return bad("sibling labels not strictly increasing");
            }
        }
        Ok(Louds { shape, labels, terminal, nodes })
    }
}
