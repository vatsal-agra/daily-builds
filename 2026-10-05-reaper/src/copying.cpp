#include "collectors.hpp"
#include <algorithm>

namespace reaper {

CopyingHeap::CopyingHeap(size_t words) : Heap(words & ~size_t(1)), half(words / 2), lo(BASE), top(BASE) {
  poison(BASE, mem.size());
}

Ref CopyingHeap::evacuate(Ref r, size_t& free) {
  if (r == NIL) return NIL;
  if (mem[r] & FWD_BIT) return (Ref)mem[r + 1];
  uint32_t sz = size(r);
  std::memcpy(&mem[free], &mem[r], sz * sizeof(Word));
  mem[free + 1] = 0;
  mem[r] |= FWD_BIT;
  mem[r + 1] = free;
  Ref nr = (Ref)free;
  free += sz;
  stats.moved_objects++;
  stats.copied_words += sz;
  return nr;
}

void CopyingHeap::collect() {
  double t = nowMs();
  size_t fromLo = lo, fromTop = top;
  size_t toLo = (lo == BASE) ? BASE + half : BASE;
  size_t scan = toLo, free = toLo;
  for (Ref& r : roots) r = evacuate(r, free);
  while (scan < free) {                                   // Cheney scan
    Ref o = (Ref)scan;
    for (uint32_t i = 0, n = nptrs(o); i < n; i++) mem[o + HDR + i] = evacuate((Ref)mem[o + HDR + i], free);
    scan += size(o);
  }
  poison(fromLo, fromLo + half);
  stats.major_gcs++;
  stats.reclaimed_words += (fromTop - fromLo) - (free - toLo);
  touchLive(free - toLo);
  lo = toLo;
  top = free;
  recordPause(t, nowMs() - t, 'M');
}

}  // namespace reaper
