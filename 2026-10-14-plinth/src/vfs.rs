//! The operation surface shared by the real filesystem and the in-memory reference model.
use crate::error::Result;
use crate::layout::Kind;
use std::collections::BTreeMap;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DumpNode {
    pub kind: Kind,
    pub perm: u16,
    pub nlink: u16,
    /// Files: byte length. Dirs: 0.
    pub size: u64,
    /// File contents or symlink target. Empty for dirs.
    pub data: Vec<u8>,
    /// Smallest path that names the same inode (identifies hard-link groups).
    pub group: String,
}

pub type Dump = BTreeMap<String, DumpNode>;

pub trait Vfs {
    fn mkdir(&mut self, p: &str) -> Result<()>;
    fn create(&mut self, p: &str) -> Result<()>;
    fn write(&mut self, p: &str, off: u64, data: &[u8]) -> Result<()>;
    fn truncate(&mut self, p: &str, size: u64) -> Result<()>;
    fn unlink(&mut self, p: &str) -> Result<()>;
    fn rmdir(&mut self, p: &str) -> Result<()>;
    fn rename(&mut self, from: &str, to: &str) -> Result<()>;
    fn link(&mut self, existing: &str, new: &str) -> Result<()>;
    fn symlink(&mut self, target: &str, new: &str) -> Result<()>;
    fn chmod(&mut self, p: &str, perm: u16) -> Result<()>;
    fn dump(&mut self) -> Result<Dump>;
}

/// Fill in `group` for every node given (path, inode-id) pairs.
pub fn assign_groups(dump: &mut Dump, ids: &[(String, u64)]) {
    let mut first: std::collections::HashMap<u64, String> = std::collections::HashMap::new();
    for (p, id) in ids {
        let e = first.entry(*id).or_insert_with(|| p.clone());
        if p < e {
            *e = p.clone();
        }
    }
    for (p, id) in ids {
        if let Some(n) = dump.get_mut(p) {
            n.group = first[id].clone();
        }
    }
}
