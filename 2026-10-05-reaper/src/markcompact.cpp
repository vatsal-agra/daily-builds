#include "collectors.hpp"

namespace reaper {

void MarkCompactHeap::collect() {
  double t = nowMs();
  std::vector<Ref> stack;
  uint64_t live = 0;
  markFromRoots(stack, &live);
  size_t before = top;
  size_t dest = compactRegions({{BASE, top}}, SIZE_MAX);
  poison(dest, top);
  top = dest;
  stats.major_gcs++;
  stats.reclaimed_words += before - dest;
  touchLive(live);
  recordPause(t, nowMs() - t, 'M');
}

}  // namespace reaper
