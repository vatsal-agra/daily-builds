#include "heap.hpp"
#include <algorithm>
#include <chrono>
#include <cstdio>

namespace reaper {

double Heap::nowMs() {
  using namespace std::chrono;
  return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

double Stats::pct(double p) const {
  if (pauses.empty()) return 0;
  std::vector<double> d;
  d.reserve(pauses.size());
  for (auto& x : pauses) d.push_back(x.dur_ms);
  std::sort(d.begin(), d.end());
  size_t i = (size_t)(p / 100.0 * (d.size() - 1) + 0.5);
  return d[std::min(i, d.size() - 1)];
}

Heap::Heap(size_t words) : roots(NROOTS, NIL), mem(words + BASE, 0) { t0 = nowMs(); }

void Heap::recordPause(double start_ms, double dur_ms, char kind) {
  stats.pauses.push_back({start_ms - t0, dur_ms, kind});
  stats.total_pause_ms += dur_ms;
  stats.max_pause_ms = std::max(stats.max_pause_ms, dur_ms);
}

void Heap::poison(size_t from, size_t to) {
  if (!poisoning) return;
  for (size_t i = from; i < to; i++) mem[i] = POISON;
}

void Heap::touchLive(size_t words) { stats.peak_live_words = std::max<uint64_t>(stats.peak_live_words, words); }

// ------------------------------------------------------------------ mutator API
void Heap::newObj(size_t dst, uint32_t np, uint32_t nd, uint32_t tag) {
  if (dst >= NROOTS) throw std::out_of_range("root slot");
  if (np > 0xFFFF) throw std::invalid_argument("too many pointer slots");
  if (tag >= TAG_FREE) throw std::invalid_argument("tag out of range");
  uint64_t w64 = (uint64_t)HDR + np + nd;
  if (w64 >= 0x7FFFFFFFull || w64 >= mem.size()) throw OutOfMemory("object larger than heap");
  uint32_t words = (uint32_t)w64;
  Ref r = tryAlloc(words);
  for (int attempt = 0; r == NIL; attempt++) {
    if (!collectForAlloc(words, attempt))
      throw OutOfMemory("heap exhausted allocating " + std::to_string(words) + " words in " + name());
    r = tryAlloc(words);
  }
  mem[r] = makeMeta(words, np, tag);
  mem[r + 1] = 0;
  std::fill(mem.begin() + r + HDR, mem.begin() + r + words, (Word)0);
  stats.allocs++;
  stats.alloc_words += words;
  onAllocated(r);
  roots[dst] = r;
}

void Heap::store(size_t o, uint32_t i, size_t s) {
  Ref obj = roots.at(o);
  if (obj == NIL) throw std::invalid_argument("store through null slot");
  if (i >= nptrs(obj)) throw std::out_of_range("pointer field index");
  Ref val = roots.at(s);
  onStore(obj, val);
  mem[obj + HDR + i] = val;
}
void Heap::storeNil(size_t o, uint32_t i) {
  Ref obj = roots.at(o);
  if (obj == NIL) throw std::invalid_argument("store through null slot");
  if (i >= nptrs(obj)) throw std::out_of_range("pointer field index");
  mem[obj + HDR + i] = NIL;
}
void Heap::load(size_t dst, size_t o, uint32_t i) {
  Ref obj = roots.at(o);
  if (obj == NIL) throw std::invalid_argument("load through null slot");
  if (i >= nptrs(obj)) throw std::out_of_range("pointer field index");
  roots.at(dst) = field(obj, i);
}
void Heap::setData(size_t slot, uint32_t j, Word v) {
  Ref obj = roots.at(slot);
  if (obj == NIL) throw std::invalid_argument("setData through null slot");
  if (j >= size(obj) - HDR - nptrs(obj)) throw std::out_of_range("data index");
  dataRaw(obj, j) = v;
}
Word Heap::getData(size_t slot, uint32_t j) const {
  Ref obj = roots.at(slot);
  if (obj == NIL) throw std::invalid_argument("getData through null slot");
  if (j >= size(obj) - HDR - nptrs(obj)) throw std::out_of_range("data index");
  return mem[obj + HDR + nptrs(obj) + j];
}
void Heap::gc(bool full) { collectExplicit(full); }

// ------------------------------------------------------------------ marking helpers
void Heap::markObject(Ref r, std::vector<Ref>& stack) {
  if (r == NIL || (mem[r] & MARK_BIT)) return;
  mem[r] |= MARK_BIT;
  stack.push_back(r);
}
void Heap::drainMarks(std::vector<Ref>& stack, uint64_t* live) {
  while (!stack.empty()) {
    Ref r = stack.back();
    stack.pop_back();
    if (live) *live += size(r);
    uint32_t n = nptrs(r);
    for (uint32_t i = 0; i < n; i++) markObject(field(r, i), stack);
  }
}
void Heap::markFromRoots(std::vector<Ref>& stack, uint64_t* live) {
  for (Ref r : roots) markObject(r, stack);
  drainMarks(stack, live);
}

size_t Heap::compactRegions(const std::vector<std::pair<size_t, size_t>>& regions, size_t limit) {
  size_t dest = BASE;
  for (auto& rg : regions)                                     // pass 1: forwarding addresses
    for (size_t pos = rg.first; pos < rg.second; pos += size((Ref)pos))
      if (mem[pos] & MARK_BIT) { mem[pos + 1] = dest; dest += size((Ref)pos); }
  if (dest > limit) {
    for (auto& rg : regions)
      for (size_t pos = rg.first; pos < rg.second; pos += size((Ref)pos)) mem[pos] &= ~MARK_BIT;
    return SIZE_MAX;
  }
  for (Ref& r : roots) if (r != NIL) r = (Ref)mem[r + 1];     // pass 2: rewrite pointers
  for (auto& rg : regions)
    for (size_t pos = rg.first; pos < rg.second; pos += size((Ref)pos))
      if (mem[pos] & MARK_BIT)
        for (uint32_t i = 0, n = nptrs((Ref)pos); i < n; i++) {
          Word& f = mem[pos + HDR + i];
          if (f != NIL) f = mem[f + 1];
        }
  for (auto& rg : regions)                                     // pass 3: slide
    for (size_t pos = rg.first; pos < rg.second;) {
      size_t sz = size((Ref)pos);
      if (mem[pos] & MARK_BIT) {
        size_t to = mem[pos + 1];
        if (to != pos) { std::memmove(&mem[to], &mem[pos], sz * sizeof(Word)); stats.moved_objects++; stats.copied_words += sz; }
        mem[to] &= ~(MARK_BIT | REM_BIT);
        mem[to + 1] = 0;
      }
      pos += sz;
    }
  return dest;
}

// ------------------------------------------------------------------ introspection
void Heap::map(std::vector<uint8_t>& out) const {
  out.assign(mem.size(), 0);
  walk([&](Ref r, bool isFree) {
    if (isFree) return;
    for (size_t k = 0; k < size(r); k++) out[r + k] = isYoung(r) ? 2 : 1;
  });
}

static inline Word mix(Word h, Word v) {
  h ^= v + 0x9E3779B97F4A7C15ull + (h << 6) + (h >> 2);
  h *= 0xFF51AFD7ED558CCDull;
  h ^= h >> 32;
  return h;
}

uint64_t Heap::graphHash(size_t* liveObjects, size_t* liveWords) const {
  std::vector<uint32_t> idx(mem.size(), 0);  // visit index + 1
  std::vector<Ref> order;
  uint64_t h = 1469598103934665603ull;
  auto visit = [&](Ref r) -> uint32_t {
    if (r == NIL) return 0;
    if (!idx[r]) { order.push_back(r); idx[r] = (uint32_t)order.size(); }
    return idx[r];
  };
  for (Ref r : roots) h = mix(h, visit(r));
  size_t words = 0;
  for (size_t k = 0; k < order.size(); k++) {
    Ref r = order[k];
    uint32_t np = nptrs(r), sz = size(r);
    words += sz;
    h = mix(h, ((Word)np << 32) | sz);
    h = mix(h, tag(r));
    for (uint32_t i = 0; i < np; i++) h = mix(h, visit(field(r, i)));
    for (uint32_t j = HDR + np; j < sz; j++) h = mix(h, mem[r + j]);
  }
  if (liveObjects) *liveObjects = order.size();
  if (liveWords) *liveWords = words;
  return h;
}

std::string Heap::verify() const {
  char buf[256];
  std::vector<uint8_t> start(mem.size(), 0);  // 1 = object start, 2 = free block start
  std::string err;
  walk([&](Ref r, bool isFree) {
    if (!err.empty()) return;
    if (r < BASE || r + HDR > mem.size()) { snprintf(buf, sizeof buf, "block @%u out of arena", r); err = buf; return; }
    uint32_t sz = size(r);
    if (sz < HDR || (size_t)r + sz > mem.size()) { snprintf(buf, sizeof buf, "block @%u has bad size %u", r, sz); err = buf; return; }
    if (mem[r] & FWD_BIT) { snprintf(buf, sizeof buf, "block @%u still forwarded", r); err = buf; return; }
    if (isFree != (tag(r) == TAG_FREE)) { snprintf(buf, sizeof buf, "block @%u free flag/tag mismatch", r); err = buf; return; }
    if (!isFree && HDR + nptrs(r) > sz) { snprintf(buf, sizeof buf, "object @%u: nptrs %u overflows size %u", r, nptrs(r), sz); err = buf; return; }
    if (isFree && poisoning && freeBlocksPoisoned()) {
      for (uint32_t k = HDR; k < sz; k++)
        if (mem[r + k] != POISON) { snprintf(buf, sizeof buf, "free block @%u word %u not poisoned (write-after-free?)", r, k); err = buf; return; }
    }
    start[r] = isFree ? 2 : 1;
  });
  if (!err.empty()) return err;
  auto okRef = [&](Ref x) { return x == NIL || (x < start.size() && start[x] == 1); };
  for (size_t i = 0; i < roots.size(); i++)
    if (!okRef(roots[i])) { snprintf(buf, sizeof buf, "root slot %zu holds dangling ref %u", i, roots[i]); return buf; }
  {  // every object reachable from the roots must be intact and its pointers valid
    std::vector<uint8_t> seen(mem.size(), 0);
    std::vector<Ref> work;
    for (Ref r : roots) if (r != NIL && !seen[r]) { seen[r] = 1; work.push_back(r); }
    while (!work.empty()) {
      Ref r = work.back();
      work.pop_back();
      for (uint32_t i = 0; i < nptrs(r); i++) {
        Ref f = field(r, i);
        if (!okRef(f)) { snprintf(buf, sizeof buf, "object @%u field %u holds dangling ref %u", r, i, f); return buf; }
        if (f != NIL && !seen[f]) { seen[f] = 1; work.push_back(f); }
      }
    }
  }
  return verifyExtra();
}

}  // namespace reaper
