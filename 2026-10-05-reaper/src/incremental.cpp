#include "collectors.hpp"
#include <algorithm>

namespace reaper {

IncrementalHeap::IncrementalHeap(size_t words, size_t sl) : MarkSweepHeap(words), slice(sl ? sl : 64) {}

std::string IncrementalHeap::describe() const {
  return "tri-colour incremental mark (Dijkstra barrier) + lazy sweep, slice=" + std::to_string(slice);
}

void IncrementalHeap::onStore(Ref, Ref val) {
  if (st == MARK && val != NIL && !(mem[val] & MARK_BIT)) {   // shade the stored target gray
    stats.barrier_hits++;
    mem[val] |= MARK_BIT;
    gray.push_back(val);
  }
}

void IncrementalHeap::onAllocated(Ref r) {
  if (st == MARK || (st == SWEEP && r >= sweepPos)) mem[r] |= MARK_BIT;   // allocate black
}

void IncrementalHeap::startCycle() {
  double t = nowMs();
  st = MARK;
  gray.clear();
  cycleLive = cycleReclaimed = 0;
  for (Ref r : roots) markObject(r, gray);
  recordPause(t, nowMs() - t, 's');
}

void IncrementalHeap::markStep(size_t budget) {
  double t = nowMs();
  stats.inc_steps++;
  while (budget-- && !gray.empty()) {
    Ref r = gray.back();
    gray.pop_back();
    cycleLive += size(r);
    for (uint32_t i = 0, n = nptrs(r); i < n; i++) markObject(field(r, i), gray);
  }
  if (gray.empty()) terminateMark();
  recordPause(t, nowMs() - t, 's');
}

void IncrementalHeap::terminateMark() {
  // Root slots are written without a barrier, so rescan them atomically, then drain.
  for (Ref r : roots) markObject(r, gray);
  drainMarks(gray, &cycleLive);
  touchLive(cycleLive);
  st = SWEEP;
  sweepPos = BASE;
  head = NIL;  // free blocks are rediscovered (and coalesced) as the sweep advances
}

void IncrementalHeap::sweepStep(size_t budget) {
  double t = nowMs();
  stats.inc_steps++;
  size_t end = mem.size(), done = 0;
  Ref lastFree = NIL;
  while (sweepPos < end && done < budget) {
    size_t pos = sweepPos;
    uint32_t sz = size((Ref)pos);
    bool isFree = tag((Ref)pos) == TAG_FREE;
    bool dead = !isFree && !(mem[pos] & MARK_BIT);
    done += sz;
    sweepPos += sz;
    if (!isFree && !dead) { mem[pos] &= ~MARK_BIT; lastFree = NIL; continue; }
    if (dead) cycleReclaimed += sz;
    if (lastFree != NIL && lastFree + size(lastFree) == pos) {
      mem[lastFree] = makeMeta(size(lastFree) + sz, 0, TAG_FREE);
      poison(pos, pos + sz);
    } else {
      makeFree(pos, sz, head);   // LIFO push: lets the mutator allocate from swept space immediately
      head = lastFree = (Ref)pos;
    }
  }
  if (sweepPos >= end) {
    st = IDLE;
    stats.major_gcs++;
    stats.reclaimed_words += cycleReclaimed;
  }
  recordPause(t, nowMs() - t, 's');
}

void IncrementalHeap::finishCycle() {
  double t = nowMs();
  if (st == MARK) { while (st == MARK) { for (Ref r : roots) markObject(r, gray); drainMarks(gray, &cycleLive); terminateMark(); } }
  while (st == SWEEP) sweepStep((size_t)-1);
  recordPause(t, nowMs() - t, 'M');
}

void IncrementalHeap::fullCycle() {
  startCycle();
  finishCycle();
}

void IncrementalHeap::pace(uint32_t words) {
  size_t freeW = capacityWords() - usedWords();
  if (st == IDLE) {
    if (freeW * 100 < capacityWords() * 40) startCycle();   // begin when under 40% free
    return;
  }
  debt += (size_t)words * 4;                                 // 4 units of GC work per word allocated
  if (debt < slice) return;
  size_t b = debt;
  debt = 0;
  if (st == MARK) markStep(b / 4 + 1);
  else if (st == SWEEP) sweepStep(b * 4);
}

Ref IncrementalHeap::tryAlloc(uint32_t w) {
  pace(w);
  Ref r = MarkSweepHeap::tryAlloc(w);
  while (r == NIL && st == SWEEP) { sweepStep(slice * 4); r = MarkSweepHeap::tryAlloc(w); }
  return r;
}

bool IncrementalHeap::collectForAlloc(uint32_t, int attempt) {
  if (attempt == 0) {
    bool wasActive = st != IDLE;
    finishCycle();
    lastWasFull = !wasActive;
    if (!wasActive) fullCycle();
    return true;
  }
  if (attempt == 1 && !lastWasFull) { fullCycle(); lastWasFull = true; return true; }
  return false;
}

}  // namespace reaper
