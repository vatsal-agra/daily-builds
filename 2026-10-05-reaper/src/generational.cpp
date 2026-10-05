#include "collectors.hpp"
#include <algorithm>

namespace reaper {

GenerationalHeap::GenerationalHeap(size_t words, size_t nursery) : Heap(words), oldTop(BASE) {
  if (nursery == 0) nursery = words / 4;
  nursery = std::max<size_t>(16, std::min(nursery, words / 2));
  nurEnd = mem.size();
  nurStart = nurEnd - nursery;
  nurTop = nurStart;
  poison(BASE, mem.size());
}

std::string GenerationalHeap::describe() const {
  return "nursery " + std::to_string(nurEnd - nurStart) + "w + compacted old gen, write barrier + remembered set";
}

void GenerationalHeap::walk(const std::function<void(Ref, bool)>& f) const {
  for (size_t p = BASE; p < oldTop; p += size((Ref)p)) f((Ref)p, false);
  for (size_t p = nurStart; p < nurTop; p += size((Ref)p)) f((Ref)p, false);
}

Ref GenerationalHeap::tryAlloc(uint32_t w) {
  if ((size_t)w * 2 > nurEnd - nurStart) {                // large object: pretenure
    if (oldTop + w > nurStart) return NIL;
    Ref r = (Ref)oldTop;
    oldTop += w;
    return r;
  }
  if (nurTop + w > nurEnd) return NIL;
  Ref r = (Ref)nurTop;
  nurTop += w;
  return r;
}

bool GenerationalHeap::collectForAlloc(uint32_t w, int attempt) {
  if (attempt == 0) {
    if ((size_t)w * 2 > nurEnd - nurStart) major(); else minorOrMajor();
    return true;
  }
  if (attempt == 1 && !lastMajor) { major(); return true; }
  return false;
}

void GenerationalHeap::minorOrMajor() {
  // promotion needs room for the entire nursery's survivors in the worst case
  if (nurStart - oldTop >= nurTop - nurStart) minor(); else major();
}

void GenerationalHeap::onStore(Ref obj, Ref val) {
  if (obj < nurStart && val >= nurStart) {
    stats.barrier_hits++;
    if (!(mem[obj] & REM_BIT)) {
      mem[obj] |= REM_BIT;
      remembered.push_back(obj);
      stats.remembered_adds++;
    }
  }
}

Ref GenerationalHeap::evacuate(Ref r) {
  if (r == NIL || r < nurStart) return r;
  if (mem[r] & FWD_BIT) return (Ref)mem[r + 1];
  uint32_t sz = size(r);
  std::memcpy(&mem[oldTop], &mem[r], sz * sizeof(Word));
  mem[oldTop + 1] = 0;
  mem[r] |= FWD_BIT;
  mem[r + 1] = oldTop;
  Ref nr = (Ref)oldTop;
  oldTop += sz;
  stats.moved_objects++;
  stats.copied_words += sz;
  return nr;
}

void GenerationalHeap::minor() {
  double t = nowMs();
  size_t promoStart = oldTop, scan = oldTop, nurUsed = nurTop - nurStart;
  for (Ref& r : roots) r = evacuate(r);
  for (Ref o : remembered) {
    mem[o] &= ~REM_BIT;
    for (uint32_t i = 0, n = nptrs(o); i < n; i++) mem[o + HDR + i] = evacuate((Ref)mem[o + HDR + i]);
  }
  remembered.clear();
  while (scan < oldTop) {
    Ref o = (Ref)scan;
    for (uint32_t i = 0, n = nptrs(o); i < n; i++) mem[o + HDR + i] = evacuate((Ref)mem[o + HDR + i]);
    scan += size(o);
  }
  poison(nurStart, nurTop);
  stats.minor_gcs++;
  stats.reclaimed_words += nurUsed - (oldTop - promoStart);
  nurTop = nurStart;
  lastMajor = false;
  recordPause(t, nowMs() - t, 'm');
}

void GenerationalHeap::major() {
  double t = nowMs();
  std::vector<Ref> stack;
  uint64_t live = 0;
  markFromRoots(stack, &live);
  size_t before = (oldTop - BASE) + (nurTop - nurStart);
  size_t dest = compactRegions({{BASE, oldTop}, {nurStart, nurTop}}, nurStart);
  if (dest == SIZE_MAX) {
    recordPause(t, nowMs() - t, 'M');
    throw OutOfMemory("generational heap exhausted: live data exceeds old generation");
  }
  poison(dest, oldTop);
  poison(nurStart, nurTop);
  oldTop = dest;
  nurTop = nurStart;
  remembered.clear();
  stats.major_gcs++;
  stats.reclaimed_words += before - (dest - BASE);
  touchLive(live);
  lastMajor = true;
  recordPause(t, nowMs() - t, 'M');
}

std::string GenerationalHeap::verifyExtra() const {
  size_t remCount = 0;
  for (size_t p = BASE; p < oldTop; p += size((Ref)p)) {
    Ref o = (Ref)p;
    bool young = false;
    for (uint32_t i = 0; i < nptrs(o); i++) if (field(o, i) >= nurStart) young = true;
    if (young && !(mem[o] & REM_BIT)) return "old object @" + std::to_string(o) + " points to the nursery but is not remembered (barrier hole)";
    if (mem[o] & REM_BIT) remCount++;
  }
  if (remCount != remembered.size()) return "remembered-set size disagrees with REM flags";
  if (oldTop > nurStart) return "old generation overran the nursery";
  return "";
}

}  // namespace reaper
