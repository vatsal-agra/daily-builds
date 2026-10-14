//! Reference model: a deliberately naive in-memory filesystem with the same observable semantics
//! (including error precedence) as `Fs`. It shares no code with the real implementation, so
//! agreement between the two is evidence, not tautology.
use crate::error::{FsError, Result};
use crate::layout::{name_ok, Kind, MAX_FILE_SIZE, MAX_NAME, MAX_LINKS};
use crate::vfs::{assign_groups, Dump, DumpNode, Vfs};
use std::collections::{BTreeMap, HashMap, VecDeque};

#[derive(Clone)]
struct MNode {
    kind: Kind,
    perm: u16,
    data: Vec<u8>,
    ents: BTreeMap<String, u64>,
}

#[derive(Clone)]
pub struct Model {
    nodes: HashMap<u64, MNode>,
    parent: HashMap<u64, u64>,
    next: u64,
}

const ROOT: u64 = 1;

impl Model {
    pub fn new() -> Model {
        let mut nodes = HashMap::new();
        nodes.insert(ROOT, MNode { kind: Kind::Dir, perm: 0o755, data: vec![], ents: BTreeMap::new() });
        let mut parent = HashMap::new();
        parent.insert(ROOT, ROOT);
        Model { nodes, parent, next: 2 }
    }

    fn split(p: &str) -> Result<VecDeque<String>> {
        if !p.starts_with('/') {
            return Err(FsError::Invalid("paths must be absolute".into()));
        }
        Ok(p.split('/').filter(|c| !c.is_empty()).map(String::from).collect())
    }

    fn walk(&self, mut q: VecDeque<String>, follow_last: bool) -> Result<u64> {
        let mut cur = ROOT;
        let mut hops = 0;
        while let Some(c) = q.pop_front() {
            if c == "." {
                continue;
            }
            if c.len() > MAX_NAME {
                return Err(FsError::NameTooLong);
            }
            let cn = &self.nodes[&cur];
            if cn.kind != Kind::Dir {
                return Err(FsError::NotDir);
            }
            let id = if c == ".." { self.parent[&cur] } else { *cn.ents.get(&c).ok_or(FsError::NotFound)? };
            let n = &self.nodes[&id];
            if n.kind == Kind::Symlink && (follow_last || !q.is_empty()) {
                hops += 1;
                if hops > 8 {
                    return Err(FsError::Loop);
                }
                let t = String::from_utf8(n.data.clone()).unwrap();
                if t.starts_with('/') {
                    cur = ROOT;
                }
                for part in t.split('/').rev().filter(|x| !x.is_empty()) {
                    q.push_front(part.to_string());
                }
                continue;
            }
            if !q.is_empty() && n.kind != Kind::Dir {
                return Err(FsError::NotDir);
            }
            cur = id;
        }
        Ok(cur)
    }

    fn parent_of(&self, p: &str) -> Result<(u64, String)> {
        let mut q = Model::split(p)?;
        let name = q.pop_back().ok_or_else(|| FsError::Invalid("no final component".into()))?;
        if name == "." || name == ".." {
            return Err(FsError::Invalid("dot".into()));
        }
        if name.len() > MAX_NAME {
            return Err(FsError::NameTooLong);
        }
        if !name_ok(&name) {
            return Err(FsError::Invalid("bad name".into()));
        }
        let d = self.walk(q, true)?;
        if self.nodes[&d].kind != Kind::Dir {
            return Err(FsError::NotDir);
        }
        Ok((d, name))
    }

    fn add(&mut self, dir: u64, name: &str, kind: Kind, perm: u16, data: Vec<u8>) -> Result<u64> {
        if self.nodes[&dir].ents.contains_key(name) {
            return Err(FsError::Exists);
        }
        let id = self.next;
        self.next += 1;
        self.nodes.insert(id, MNode { kind, perm, data, ents: BTreeMap::new() });
        if kind == Kind::Dir {
            self.parent.insert(id, dir);
        }
        self.nodes.get_mut(&dir).unwrap().ents.insert(name.to_string(), id);
        Ok(id)
    }

    fn refcount(&self, id: u64) -> usize {
        self.nodes.values().map(|n| n.ents.values().filter(|&&c| c == id).count()).sum()
    }

    fn collect(&mut self) {
        // drop unreachable nodes
        let mut live = std::collections::HashSet::new();
        let mut st = vec![ROOT];
        while let Some(i) = st.pop() {
            if live.insert(i) {
                st.extend(self.nodes[&i].ents.values().copied());
            }
        }
        self.nodes.retain(|k, _| live.contains(k));
        self.parent.retain(|k, _| live.contains(k));
    }

    /// (path, kind, size) of everything, for workload generation.
    pub fn listing(&self) -> Vec<(String, Kind, u64)> {
        let mut out = vec![];
        let mut st = vec![("/".to_string(), ROOT)];
        while let Some((p, id)) = st.pop() {
            let n = &self.nodes[&id];
            out.push((p.clone(), n.kind, n.data.len() as u64));
            for (name, c) in &n.ents {
                st.push((if p == "/" { format!("/{name}") } else { format!("{p}/{name}") }, *c));
            }
        }
        out.sort();
        out
    }

    fn file_target(&self, p: &str) -> Result<u64> {
        let id = self.walk(Model::split(p)?, true)?;
        if self.nodes[&id].kind == Kind::Dir {
            return Err(FsError::IsDir);
        }
        Ok(id)
    }
}

impl Vfs for Model {
    fn mkdir(&mut self, p: &str) -> Result<()> {
        let (d, n) = self.parent_of(p)?;
        self.add(d, &n, Kind::Dir, 0o755, vec![]).map(|_| ())
    }
    fn create(&mut self, p: &str) -> Result<()> {
        let (d, n) = self.parent_of(p)?;
        self.add(d, &n, Kind::File, 0o644, vec![]).map(|_| ())
    }
    fn symlink(&mut self, target: &str, p: &str) -> Result<()> {
        if target.is_empty() || target.len() > 1024 {
            return Err(FsError::Invalid("target".into()));
        }
        let (d, n) = self.parent_of(p)?;
        self.add(d, &n, Kind::Symlink, 0o777, target.as_bytes().to_vec()).map(|_| ())
    }
    fn write(&mut self, p: &str, off: u64, data: &[u8]) -> Result<()> {
        let id = self.file_target(p)?;
        if data.is_empty() {
            return Ok(());
        }
        let end = off.checked_add(data.len() as u64).ok_or(FsError::TooBig)?;
        if end > MAX_FILE_SIZE {
            return Err(FsError::TooBig);
        }
        let n = self.nodes.get_mut(&id).unwrap();
        if (n.data.len() as u64) < end {
            n.data.resize(end as usize, 0);
        }
        n.data[off as usize..end as usize].copy_from_slice(data);
        Ok(())
    }
    fn truncate(&mut self, p: &str, size: u64) -> Result<()> {
        let id = self.file_target(p)?;
        if size > MAX_FILE_SIZE {
            return Err(FsError::TooBig);
        }
        self.nodes.get_mut(&id).unwrap().data.resize(size as usize, 0);
        Ok(())
    }
    fn unlink(&mut self, p: &str) -> Result<()> {
        let (d, n) = self.parent_of(p)?;
        let id = *self.nodes[&d].ents.get(&n).ok_or(FsError::NotFound)?;
        if self.nodes[&id].kind == Kind::Dir {
            return Err(FsError::IsDir);
        }
        self.nodes.get_mut(&d).unwrap().ents.remove(&n);
        self.collect();
        Ok(())
    }
    fn rmdir(&mut self, p: &str) -> Result<()> {
        let (d, n) = self.parent_of(p)?;
        let id = *self.nodes[&d].ents.get(&n).ok_or(FsError::NotFound)?;
        if self.nodes[&id].kind != Kind::Dir {
            return Err(FsError::NotDir);
        }
        if !self.nodes[&id].ents.is_empty() {
            return Err(FsError::NotEmpty);
        }
        self.nodes.get_mut(&d).unwrap().ents.remove(&n);
        self.collect();
        Ok(())
    }
    fn link(&mut self, existing: &str, new: &str) -> Result<()> {
        let id = self.walk(Model::split(existing)?, false)?;
        if self.nodes[&id].kind == Kind::Dir {
            return Err(FsError::IsDir);
        }
        let (d, n) = self.parent_of(new)?;
        if self.nodes[&d].ents.contains_key(&n) {
            return Err(FsError::Exists);
        }
        if self.refcount(id) + 1 > MAX_LINKS as usize {
            return Err(FsError::TooManyLinks);
        }
        self.nodes.get_mut(&d).unwrap().ents.insert(n, id);
        Ok(())
    }
    fn chmod(&mut self, p: &str, perm: u16) -> Result<()> {
        let id = self.walk(Model::split(p)?, true)?;
        self.nodes.get_mut(&id).unwrap().perm = perm & 0o7777;
        Ok(())
    }
    fn rename(&mut self, from: &str, to: &str) -> Result<()> {
        let (sd, sn) = self.parent_of(from)?;
        let (dd, dn) = self.parent_of(to)?;
        let sid = *self.nodes[&sd].ents.get(&sn).ok_or(FsError::NotFound)?;
        if sd == dd && sn == dn {
            return Ok(());
        }
        let sdir = self.nodes[&sid].kind == Kind::Dir;
        if sdir {
            let mut cur = dd;
            loop {
                if cur == sid {
                    return Err(FsError::Invalid("into itself".into()));
                }
                if cur == ROOT {
                    break;
                }
                cur = self.parent[&cur];
            }
        }
        if let Some(&did) = self.nodes[&dd].ents.get(&dn) {
            if did == sid {
                return Ok(());
            }
            let ddir = self.nodes[&did].kind == Kind::Dir;
            if sdir && !ddir {
                return Err(FsError::NotDir);
            }
            if !sdir && ddir {
                return Err(FsError::IsDir);
            }
            if ddir && !self.nodes[&did].ents.is_empty() {
                return Err(FsError::NotEmpty);
            }
        }
        self.nodes.get_mut(&dd).unwrap().ents.insert(dn, sid);
        self.nodes.get_mut(&sd).unwrap().ents.remove(&sn);
        if sdir {
            self.parent.insert(sid, dd);
        }
        self.collect();
        Ok(())
    }
    fn dump(&mut self) -> Result<Dump> {
        let mut dump = Dump::new();
        let mut ids = vec![];
        let mut st = vec![("/".to_string(), ROOT)];
        while let Some((p, id)) = st.pop() {
            let n = &self.nodes[&id];
            let nlink = if n.kind == Kind::Dir {
                2 + n.ents.values().filter(|c| self.nodes[c].kind == Kind::Dir).count()
            } else {
                self.refcount(id)
            };
            let (size, data) = if n.kind == Kind::Dir { (0, vec![]) } else { (n.data.len() as u64, n.data.clone()) };
            dump.insert(
                p.clone(),
                DumpNode { kind: n.kind, perm: n.perm, nlink: nlink as u16, size, data, group: String::new() },
            );
            ids.push((p.clone(), id));
            for (name, c) in &n.ents {
                st.push((if p == "/" { format!("/{name}") } else { format!("{p}/{name}") }, *c));
            }
        }
        assign_groups(&mut dump, &ids);
        Ok(dump)
    }
}
