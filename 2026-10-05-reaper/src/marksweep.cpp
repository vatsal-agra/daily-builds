#include "collectors.hpp"
#include <algorithm>

namespace reaper {

MarkSweepHeap::MarkSweepHeap(size_t words) : Heap(words) {
  poison(BASE, mem.size());
  makeFree(BASE, words, NIL);
  head = BASE;
}

void MarkSweepHeap::makeFree(size_t at, size_t words, Ref next) {
  mem[at] = makeMeta((uint32_t)words, 0, TAG_FREE);
  mem[at + 1] = next;
  poison(at + HDR, at + words);
}

Ref MarkSweepHeap::tryAlloc(uint32_t w) {
  Ref prev = NIL;
  for (Ref cur = head; cur != NIL; prev = cur, cur = (Ref)mem[cur + 1]) {
    uint32_t sz = size(cur);
    if (sz < w || sz - w == 1) continue;  // a 1-word remainder cannot hold a header
    Ref next = (Ref)mem[cur + 1];
    Ref link = next;
    if (sz > w) { makeFree(cur + w, sz - w, next); link = cur + w; }
    if (prev == NIL) head = link; else mem[prev + 1] = link;
    return cur;
  }
  return NIL;
}

bool MarkSweepHeap::collectForAlloc(uint32_t, int attempt) {
  if (attempt) return false;
  collect();
  return true;
}

void MarkSweepHeap::collect() {
  double t = nowMs();
  std::vector<Ref> stack;
  uint64_t live = 0;
  markFromRoots(stack, &live);
  size_t end = mem.size(), tail = NIL, lastFree = NIL;
  head = NIL;
  uint64_t reclaimed = 0;
  for (size_t pos = BASE; pos < end;) {
    uint32_t sz = size((Ref)pos);
    bool isFree = tag((Ref)pos) == TAG_FREE;
    bool dead = !isFree && !(mem[pos] & MARK_BIT);
    if (!isFree && !dead) { mem[pos] &= ~MARK_BIT; lastFree = NIL; pos += sz; continue; }
    if (dead) reclaimed += sz;
    if (lastFree != NIL && lastFree + size(lastFree) == pos) {   // coalesce into previous free block
      mem[lastFree] = makeMeta(size(lastFree) + sz, 0, TAG_FREE);
      poison(pos, pos + sz);
    } else {
      makeFree(pos, sz, NIL);
      if (tail == NIL) head = (Ref)pos; else mem[tail + 1] = pos;
      tail = lastFree = (Ref)pos;
    }
    pos += sz;
  }
  stats.major_gcs++;
  stats.reclaimed_words += reclaimed;
  touchLive(live);
  recordPause(t, nowMs() - t, 'M');
}

size_t MarkSweepHeap::usedWords() const {
  size_t freeW = 0;
  for (Ref c = head; c != NIL; c = (Ref)mem[c + 1]) freeW += size(c);
  return capacityWords() - freeW;
}

void MarkSweepHeap::walk(const std::function<void(Ref, bool)>& f) const {
  for (size_t p = BASE; p < mem.size(); p += size((Ref)p)) f((Ref)p, tag((Ref)p) == TAG_FREE);
}

double MarkSweepHeap::fragmentation() const {
  size_t total = 0, largest = 0;
  for (Ref c = head; c != NIL; c = (Ref)mem[c + 1]) { total += size(c); largest = std::max<size_t>(largest, size(c)); }
  return total ? 1.0 - (double)largest / total : 0.0;
}

std::string MarkSweepHeap::verifyExtra() const {
  // the free list must be exactly the set of free blocks in the arena
  size_t listed = 0, walked = 0, seen = 0;
  for (Ref c = head; c != NIL; c = (Ref)mem[c + 1]) {
    if (c < BASE || c >= mem.size() || tag(c) != TAG_FREE) return "free list holds a non-free block @" + std::to_string(c);
    listed += size(c);
    if (++seen > mem.size()) return "free list is cyclic";
  }
  for (size_t p = BASE; p < mem.size(); p += size((Ref)p)) if (tag((Ref)p) == TAG_FREE) walked += size((Ref)p);
  if (name() == "marksweep" && listed != walked) return "free list misses free blocks (leak)";
  return "";
}

}  // namespace reaper
