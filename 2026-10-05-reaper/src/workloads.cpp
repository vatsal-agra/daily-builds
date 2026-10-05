#include "workloads.hpp"
#include "collectors.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace reaper {

namespace {

[[noreturn]] void corrupt(const std::string& m) { throw std::runtime_error("HEAP CORRUPTION: " + m); }

// ---------------------------------------------------------------- binary-trees
// (the classic GC benchmark: one long-lived tree, endless short-lived ones)
void buildTree(Heap& h, int depth, size_t dst, size_t tmp) {
  h.newObj(dst, 2, 1);
  h.setData(dst, 0, (Word)depth);
  if (depth > 0) {
    buildTree(h, depth - 1, tmp, tmp + 1);
    h.store(dst, 0, tmp);
    buildTree(h, depth - 1, tmp, tmp + 1);
    h.store(dst, 1, tmp);
  }
}
uint64_t checkTree(Heap& h, size_t slot, int depth, size_t tmp) {
  if (h.isNull(slot)) corrupt("tree node vanished at depth " + std::to_string(depth));
  if (h.getData(slot, 0) != (Word)depth) corrupt("tree node data clobbered at depth " + std::to_string(depth));
  if (depth == 0) return 1;
  h.load(tmp, slot, 0);
  uint64_t n = 1 + checkTree(h, tmp, depth - 1, tmp + 1);
  h.load(tmp, slot, 1);
  return n + checkTree(h, tmp, depth - 1, tmp + 1);
}

class BinaryTrees : public Mutator {
  int longDepth, shortDepth;
  uint64_t acc = 0;
  bool built = false;
 public:
  BinaryTrees(size_t heapWords) {
    longDepth = 4;
    while (longDepth < 20 && (size_t)5 << (longDepth + 2) <= heapWords / 8) longDepth++;
    shortDepth = std::max(3, std::min(10, longDepth - 1));
  }
  void step(Heap& h) override {
    if (!built) { buildTree(h, longDepth, 0, 8); built = true; }
    buildTree(h, shortDepth, 1, 8);
    acc += checkTree(h, 1, shortDepth, 8);
    h.clear(1);
  }
  void finish(Heap& h) override {
    if (!built) return;
    uint64_t n = checkTree(h, 0, longDepth, 8);
    if (n != ((uint64_t)1 << (longDepth + 1)) - 1) corrupt("long-lived tree has wrong node count");
  }
  uint64_t checksum() const override { return acc; }
};

// ---------------------------------------------------------------- list-churn
class ListChurn : public Mutator {
  Rng rng;
  uint64_t seq = 0, acc = 0;
 public:
  ListChurn(uint64_t seed) : rng(seed) {}
  void step(Heap& h) override {
    h.newObj(2, 1, 2);                       // node: next, [seq, ~seq]
    h.setData(2, 0, seq);
    h.setData(2, 1, ~seq);
    seq++;
    if (!h.isNull(0)) h.store(2, 0, 0);
    h.move(0, 2);
    uint32_t r = rng.below(400);
    if (r == 0) h.clear(0);                  // drop the whole list
    else if (r < 8) { h.move(1, 0); }        // keep a second alias alive
    else if (r < 10) h.clear(1);
  }
  void finish(Heap& h) override {
    for (size_t head : {0, 1}) {
      h.move(3, head);
      Word prev = ~0ull;
      size_t n = 0;
      while (!h.isNull(3)) {
        Word s = h.getData(3, 0);
        if (h.getData(3, 1) != ~s) corrupt("list node payload clobbered");
        if (prev != ~0ull && s >= prev) corrupt("list order broken");
        prev = s;
        h.load(3, 3, 0);
        if (++n > seq + 1) corrupt("list cycle");
      }
      acc += n;
    }
  }
  uint64_t checksum() const override { return acc ^ seq; }
};

// ---------------------------------------------------------------- lru-cache
// A 256-bucket table (becomes old) whose buckets are constantly overwritten with fresh entries:
// the pattern generational GC and its write barrier exist for.
class LruCache : public Mutator {
  Rng rng;
  uint64_t seq = 0, acc = 0;
  std::vector<uint64_t> keys = std::vector<uint64_t>(256, 0);
  bool built = false;
  static constexpr uint32_t B = 256;
 public:
  LruCache(uint64_t seed) : rng(seed) {}
  void step(Heap& h) override {
    if (!built) { h.newObj(0, B, 0); built = true; }
    for (int k = 0; k < 3; k++) {            // short-lived garbage
      h.newObj(3, 1, 1 + rng.below(6));
      h.setData(3, 0, seq);
    }
    uint32_t i = rng.below(B);
    uint32_t nd = 2 + rng.below(30);
    h.newObj(1, 1, nd);
    seq++;
    h.setData(1, 0, seq);
    h.setData(1, 1, seq * 7 + 1);
    h.store(1, 0, 3);                        // entry -> garbage-ish side object
    h.store(0, i, 1);
    keys[i] = seq;
    uint32_t j = rng.below(B);               // read back a random bucket
    if (keys[j]) {
      h.load(2, 0, j);
      if (h.isNull(2) || h.getData(2, 0) != keys[j] || h.getData(2, 1) != keys[j] * 7 + 1) corrupt("cache entry clobbered");
      acc += h.getData(2, 0);
    }
  }
  void finish(Heap& h) override {
    for (uint32_t j = 0; j < B; j++) {
      if (!keys[j]) continue;
      h.load(2, 0, j);
      if (h.isNull(2) || h.getData(2, 0) != keys[j] || h.getData(2, 1) != keys[j] * 7 + 1) corrupt("cache entry lost/clobbered at finish");
    }
  }
  uint64_t checksum() const override { return acc; }
};

// ---------------------------------------------------------------- fragmenter
class Fragmenter : public Mutator {
  Rng rng;
  size_t budget;
  std::vector<uint32_t> sizes = std::vector<uint32_t>(512, 0);
  std::vector<uint64_t> keys = std::vector<uint64_t>(512, 0);
  size_t liveWords = 0;
  uint64_t seq = 0, steps = 0, acc = 0;
  bool built = false;
 public:
  Fragmenter(uint64_t seed, size_t heapWords) : rng(seed), budget(heapWords / 5) {}
  void verifyBlock(Heap& h, uint32_t i) {
    h.load(2, 0, i);
    uint32_t nd = h.ndataOf(2);
    if (h.isNull(2) || nd + HDR != sizes[i] || h.getData(2, 0) != keys[i] || h.getData(2, nd - 1) != ~keys[i])
      corrupt("fragmenter block " + std::to_string(i) + " clobbered");
  }
  void step(Heap& h) override {
    if (!built) { h.newObj(0, 512, 0); built = true; }
    steps++;
    uint32_t i = rng.below(512);
    if (sizes[i]) {
      verifyBlock(h, i);
      if (rng.below(100) < 60) {
        h.storeNil(0, i);
        liveWords -= sizes[i];
        sizes[i] = 0;
        return;
      }
    }
    uint32_t sz = 1u << (3 + rng.below(8));   // 8..1024 words
    if (liveWords - sizes[i] + sz > budget) return;
    liveWords -= sizes[i];
    h.newObj(1, 0, sz - HDR);
    keys[i] = ++seq;
    h.setData(1, 0, keys[i]);
    h.setData(1, sz - HDR - 1, ~keys[i]);
    h.store(0, i, 1);
    h.clear(1);
    sizes[i] = sz;
    liveWords += sz;
    acc += sz;
    if (steps % 64 == 0) {                    // a big transient request: needs contiguous space
      uint32_t big = (uint32_t)std::max<size_t>(64, budget / 6);
      h.newObj(1, 0, big);
      h.setData(1, big - 1, 99);
      h.clear(1);
    }
  }
  void finish(Heap& h) override {
    for (uint32_t i = 0; i < 512; i++) if (sizes[i]) verifyBlock(h, i);
  }
  uint64_t checksum() const override { return acc; }
};

// ---------------------------------------------------------------- graph-fuzz
class GraphFuzz : public Mutator {
  Rng rng;
  uint64_t n = 0, acc = 0;
 public:
  GraphFuzz(uint64_t seed) : rng(seed) {}
  void step(Heap& h) override {
    n++;
    uint32_t r = rng.below(1000);
    size_t a = rng.below(NROOTS), b = rng.below(NROOTS);
    if (n % 1024 == 0) { for (size_t s = 0; s < NROOTS; s++) h.clear(s); return; }
    if (n % 128 == 0) {                       // purge: keep the live set bounded
      for (int k = 0; k < 16; k++) h.clear(rng.below(NROOTS));
      for (int k = 0; k < 24; k++) {
        size_t s = rng.below(NROOTS);
        if (!h.isNull(s) && h.nptrsOf(s)) h.storeNil(s, rng.below(h.nptrsOf(s)));
      }
      return;
    }
    if (r < 250) {
      uint32_t np = rng.below(5), nd = rng.below(6);
      if (rng.below(40) == 0) nd += 100 + rng.below(400);           // occasional big object
      h.newObj(a, np, nd, 1 + rng.below(7));
      for (uint32_t j = 0; j < nd && j < 4; j++) h.setData(a, j, rng.next());
      if (nd) h.setData(a, nd - 1, rng.next());
    } else if (r < 470) {
      if (!h.isNull(a) && h.nptrsOf(a)) h.store(a, rng.below(h.nptrsOf(a)), b);
    } else if (r < 540) {
      if (!h.isNull(a) && h.nptrsOf(a)) h.storeNil(a, rng.below(h.nptrsOf(a)));
    } else if (r < 700) {
      if (!h.isNull(a) && h.nptrsOf(a)) h.load(b, a, rng.below(h.nptrsOf(a)));
    } else if (r < 780) {
      h.move(b, a);
    } else if (r < 840) {
      h.clear(a);
    } else if (r < 920) {
      if (!h.isNull(a) && h.ndataOf(a)) h.setData(a, rng.below(h.ndataOf(a)), rng.next());
    } else if (r < 990) {
      if (!h.isNull(a) && h.ndataOf(a)) acc = acc * 31 + h.getData(a, rng.below(h.ndataOf(a)));
    } else if (r < 991) {
      h.gc(rng.below(2) == 0);
    }
  }
  void finish(Heap&) override {}
  uint64_t checksum() const override { return acc; }
};

// ---------------------------------------------------------------- pointer-shuffle
// A binary tree reachable only through its root. Each step relocates whole subtrees from one parent
// to another with load/store/storeNil — the exact "hide a white object behind a black one" pattern
// that a tri-colour collector's write barrier exists to survive — while garbage drives collection.
class PointerShuffle : public Mutator {
  Rng rng;
  uint64_t id = 0, inserted = 0, acc = 0, holdSince = 0;
  size_t holdDepth = 0;
  static constexpr size_t ROOT = 0, A = 1, B = 2, X = 3, TMP = 4, NEW = 5, GARB = 6, HOLD = 7, SCR = 8;
  static constexpr uint64_t CAP = 600;
  void descend(Heap& h, std::vector<uint8_t>& path, size_t dst) {
    h.move(dst, ROOT);
    path.clear();
    while (path.size() < 40 && rng.below(5) != 0) {
      uint8_t d = (uint8_t)rng.below(2);
      h.load(TMP, dst, d);
      if (h.isNull(TMP)) break;
      h.move(dst, TMP);
      path.push_back(d);
    }
  }
  void freshNode(Heap& h, size_t dst) {
    h.newObj(dst, 2, 1);
    h.setData(dst, 0, ++id * 3 + 1);
  }
  uint64_t check(Heap& h, size_t slot, int depth) {
    if (depth > 50) corrupt("shuffle tree too deep (cycle?)");
    if (h.getData(slot, 0) % 3 != 1) corrupt("shuffle node payload clobbered");
    uint64_t n = 1;
    for (uint32_t d = 0; d < 2; d++) {
      h.load(SCR + depth, slot, d);
      if (!h.isNull(SCR + depth)) n += check(h, SCR + depth, depth + 1);
      if (n > CAP + 2) corrupt("shuffle tree too large (cycle?)");
    }
    return n;
  }
 public:
  PointerShuffle(uint64_t seed) : rng(seed) {}
  void step(Heap& h) override {
    if (h.isNull(ROOT) || inserted >= CAP) { h.clear(ROOT); freshNode(h, ROOT); inserted = 0; }
    for (int k = 0; k < 3; k++) { h.newObj(GARB, 1, 1 + rng.below(8)); h.setData(GARB, 0, id); }
    std::vector<uint8_t> pa, pb;
    for (int k = 0; k < 2; k++) {                       // relocate a subtree
      descend(h, pa, A);
      descend(h, pb, B);
      uint32_t sa = rng.below(2), sb = rng.below(2);
      h.load(X, A, sa);
      if (h.isNull(X)) continue;
      if (pa == pb && sa == sb) continue;
      if (pb.size() > pa.size()) continue;              // only move subtrees up/sideways: depth never grows past 41
      std::vector<uint8_t> px = pa;                     // path of the subtree root
      px.push_back((uint8_t)sa);
      if (pb.size() >= px.size() && std::equal(px.begin(), px.end(), pb.begin())) continue;  // would form a cycle
      h.load(TMP, B, sb);
      if (!h.isNull(TMP)) continue;                     // only move into empty slots: nothing is ever dropped
      h.store(B, sb, X);
      h.storeNil(A, sa);
      acc++;
    }
    // Detach a subtree and keep it ONLY in a root slot for a few steps: while it is unreachable from the
    // heap, a marker that never rescans root slots would free it, and the later re-attach would expose that.
    if (h.isNull(HOLD)) {
      if (rng.below(3) == 0) {
        descend(h, pa, A);
        uint32_t sa = rng.below(2);
        h.load(HOLD, A, sa);
        if (!h.isNull(HOLD)) { h.storeNil(A, sa); holdDepth = pa.size(); holdSince = 0; acc++; }
      }
    } else if (++holdSince > 2 + rng.below(8)) {
      descend(h, pb, B);
      uint32_t sb = rng.below(2);
      h.load(TMP, B, sb);
      if (h.isNull(TMP) && pb.size() <= holdDepth) { h.store(B, sb, HOLD); h.clear(HOLD); acc++; }
      else if (holdSince > 40) h.clear(HOLD);           // give up: the subtree becomes garbage
    }
    for (int k = 0; k < 4; k++) {                       // grow
      descend(h, pa, A);
      uint32_t s = rng.below(2);
      h.load(TMP, A, s);
      if (h.isNull(TMP)) { freshNode(h, NEW); h.store(A, s, NEW); inserted++; }
    }
    h.clear(X); h.clear(A); h.clear(B); h.clear(TMP);
  }
  void finish(Heap& h) override {
    if (h.isNull(ROOT)) return;
    check(h, ROOT, 0);
  }
  uint64_t checksum() const override { return acc; }
};

}  // namespace

std::vector<WorkloadInfo> workloadInfos() {
  return {
      {"binary-trees", "one long-lived tree + endless short-lived trees (classic GC benchmark)", 300, 262144},
      {"list-churn", "cons-heavy linked lists that die wholesale", 200000, 32768},
      {"lru-cache", "old table, young entries: stresses the generational write barrier", 60000, 65536},
      {"fragmenter", "mixed-size blocks freed at random + big contiguous requests", 100000, 262144},
      {"pointer-shuffle", "relocates subtrees between parents while GC runs (barrier torture test)", 40000, 32768},
      {"graph-fuzz", "random cyclic graph mutation (the differential-fuzz workload)", 200000, 32768},
  };
}

std::unique_ptr<Mutator> makeMutator(const std::string& name, uint64_t seed, size_t heapWords) {
  if (name == "binary-trees") return std::make_unique<BinaryTrees>(heapWords);
  if (name == "list-churn") return std::make_unique<ListChurn>(seed);
  if (name == "lru-cache") return std::make_unique<LruCache>(seed);
  if (name == "fragmenter") return std::make_unique<Fragmenter>(seed, heapWords);
  if (name == "pointer-shuffle") return std::make_unique<PointerShuffle>(seed);
  if (name == "graph-fuzz") return std::make_unique<GraphFuzz>(seed);
  throw std::invalid_argument("unknown workload '" + name + "'");
}

RunResult runWorkload(Heap& h, Mutator& m, size_t steps, size_t verifyEvery) {
  RunResult res;
  double t = Heap::nowMs();
  try {
    for (size_t i = 0; i < steps; i++) {
      m.step(h);
      if (verifyEvery && (i + 1) % verifyEvery == 0) {
        std::string v = h.verify();
        if (!v.empty()) throw std::runtime_error("verify failed at step " + std::to_string(i + 1) + ": " + v);
      }
    }
    m.finish(h);
    res.checksum = m.checksum();
  } catch (const std::exception& e) {
    res.error = e.what();
  }
  res.wall_ms = Heap::nowMs() - t;
  return res;
}

FuzzReport differentialRun(const std::string& kind, const std::string& workload, uint64_t seed, size_t steps,
                           size_t heapWords, size_t checkEvery, size_t param) {
  FuzzReport rep;
  auto target = makeHeap(kind, heapWords, param);
  NoGcHeap oracle(1u << 18);
  auto mt = makeMutator(workload, seed, heapWords);
  auto mo = makeMutator(workload, seed, heapWords);
  auto fail = [&](const std::string& why, size_t at) {
    rep.ok = false;
    rep.detail = kind + "/" + workload + " seed " + std::to_string(seed) + " step " + std::to_string(at) + ": " + why;
  };
  auto compare = [&](size_t at) -> bool {
    std::string v = target->verify();
    if (!v.empty()) { fail("verifier: " + v, at); return false; }
    size_t ot = 0, ow = 0, tt = 0, tw = 0;
    uint64_t ht = target->graphHash(&tt, &tw), ho = oracle.graphHash(&ot, &ow);
    if (ht != ho || tt != ot || tw != ow) {
      fail("graph differs from oracle (live objects " + std::to_string(tt) + " vs " + std::to_string(ot) + ")", at);
      return false;
    }
    if (mt->checksum() != mo->checksum()) { fail("read checksum differs from oracle", at); return false; }
    rep.checks++;
    return true;
  };
  size_t i = 0;
  try {
    for (; i < steps; i++) {
      try { mo->step(oracle); }
      catch (const OutOfMemory&) { fail("oracle arena exhausted (reduce steps)", i); return rep; }
      mt->step(*target);
      if (checkEvery && (i + 1) % checkEvery == 0 && !compare(i + 1)) return rep;
    }
    mt->finish(*target);
    mo->finish(oracle);
    if (!compare(steps)) return rep;
    // precision: a full collection must retain exactly the live words (catches collectors that leak)
    target->gc(true);
    size_t liveObjs = 0, liveWords = 0;
    target->graphHash(&liveObjs, &liveWords);
    if (target->usedWords() != liveWords) {
      fail("after a full GC " + std::to_string(target->usedWords()) + " words are in use but only " + std::to_string(liveWords) + " are live (leak)", steps);
      return rep;
    }
    if (!compare(steps)) return rep;
  } catch (const std::exception& e) {
    fail(e.what(), i);
    return rep;
  }
  rep.steps = steps;
  return rep;
}

}  // namespace reaper
