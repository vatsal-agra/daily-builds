// Concrete collectors. Declared in a header so tests can poke at internals.
#pragma once
#include "heap.hpp"
#include <algorithm>

namespace reaper {

// Oracle: bump allocator that never collects. Same mutator semantics, no GC.
class NoGcHeap : public Heap {
 public:
  explicit NoGcHeap(size_t words, size_t maxWords = (size_t)1 << 26) : Heap(words), top(BASE), maxWords(maxWords) {}
  std::string name() const override { return "nogc"; }
  size_t usedWords() const override { return top - BASE; }
  void walk(const std::function<void(Ref, bool)>& f) const override {
    for (size_t p = BASE; p < top; p += size((Ref)p)) f((Ref)p, false);
  }
 protected:
  Ref tryAlloc(uint32_t w) override {
    if (top + w > mem.size()) {              // the oracle simply grows; refs are indices so nothing dangles
      size_t n = std::max(mem.size() * 2, top + w);
      if (n > maxWords + BASE) return NIL;
      mem.resize(n, 0);
    }
    Ref r = (Ref)top; top += w; return r;
  }
  bool collectForAlloc(uint32_t, int) override { return false; }
  void collectExplicit(bool) override {}
  size_t top, maxWords;
};

// Free-list mark-sweep (non-moving).
class MarkSweepHeap : public Heap {
 public:
  explicit MarkSweepHeap(size_t words);
  std::string name() const override { return "marksweep"; }
  size_t usedWords() const override;
  void walk(const std::function<void(Ref, bool)>& f) const override;
  double fragmentation() const override;
  bool freeBlocksPoisoned() const override { return true; }
  std::string verifyExtra() const override;
  std::string describe() const override { return "non-moving, first-fit free list, coalescing sweep"; }
 protected:
  Ref tryAlloc(uint32_t w) override;
  bool collectForAlloc(uint32_t, int attempt) override;
  void collectExplicit(bool) override { collect(); }
  void collect();
  void makeFree(size_t at, size_t words, Ref next);
  Ref head = NIL;
};

// Lisp2 sliding mark-compact (bump allocation).
class MarkCompactHeap : public Heap {
 public:
  explicit MarkCompactHeap(size_t words) : Heap(words), top(BASE) { poison(BASE, mem.size()); }
  std::string name() const override { return "markcompact"; }
  size_t usedWords() const override { return top - BASE; }
  void walk(const std::function<void(Ref, bool)>& f) const override {
    for (size_t p = BASE; p < top; p += size((Ref)p)) f((Ref)p, false);
  }
  std::string describe() const override { return "sliding Lisp2 compaction, bump allocation"; }
 protected:
  Ref tryAlloc(uint32_t w) override { if (top + w > mem.size()) return NIL; Ref r = (Ref)top; top += w; return r; }
  bool collectForAlloc(uint32_t, int attempt) override { if (attempt) return false; collect(); return true; }
  void collectExplicit(bool) override { collect(); }
  void collect();
  size_t top;
};

// Cheney semispace copying. `words` is the TOTAL arena; each semispace is half.
class CopyingHeap : public Heap {
 public:
  explicit CopyingHeap(size_t words);
  std::string name() const override { return "copying"; }
  size_t capacityWords() const override { return half; }
  size_t usedWords() const override { return top - lo; }
  void walk(const std::function<void(Ref, bool)>& f) const override {
    for (size_t p = lo; p < top; p += size((Ref)p)) f((Ref)p, false);
  }
  std::string describe() const override { return "Cheney semispace copy, half the arena usable"; }
 protected:
  Ref tryAlloc(uint32_t w) override { if (top + w > lo + half) return NIL; Ref r = (Ref)top; top += w; return r; }
  bool collectForAlloc(uint32_t, int attempt) override { if (attempt) return false; collect(); return true; }
  void collectExplicit(bool) override { collect(); }
  void collect();
  Ref evacuate(Ref r, size_t& free);
  size_t half, lo, top;
};

// Two-generation collector: bump nursery + compacted old generation.
class GenerationalHeap : public Heap {
 public:
  GenerationalHeap(size_t words, size_t nurseryWords);
  std::string name() const override { return "generational"; }
  size_t usedWords() const override { return (oldTop - BASE) + (nurTop - nurStart); }
  void walk(const std::function<void(Ref, bool)>& f) const override;
  std::string verifyExtra() const override;
  std::string describe() const override;
  size_t nurseryWords() const { return nurEnd - nurStart; }
  size_t rememberedSize() const { return remembered.size(); }
 protected:
  Ref tryAlloc(uint32_t w) override;
  bool collectForAlloc(uint32_t, int attempt) override;
  void collectExplicit(bool full) override { if (full) major(); else minorOrMajor(); }
  void onStore(Ref obj, Ref val) override;
  bool isYoung(Ref r) const override { return r >= nurStart; }
  void minorOrMajor();
  void minor();
  void major();
  Ref evacuate(Ref r);
  size_t nurStart, nurEnd, nurTop, oldTop;
  std::vector<Ref> remembered;
  bool lastMajor = false;
};

// Incremental tri-colour mark + lazy sweep (non-moving), Dijkstra insertion barrier.
class IncrementalHeap : public MarkSweepHeap {
 public:
  IncrementalHeap(size_t words, size_t slice);
  std::string name() const override { return "incremental"; }
  std::string describe() const override;
  enum State { IDLE, MARK, SWEEP };
  State state() const { return st; }
 protected:
  Ref tryAlloc(uint32_t w) override;
  bool collectForAlloc(uint32_t, int attempt) override;
  void collectExplicit(bool) override { finishCycle(); fullCycle(); }
  void onStore(Ref obj, Ref val) override;
  void onAllocated(Ref r) override;
  void startCycle();
  void markStep(size_t budget);
  void terminateMark();
  void sweepStep(size_t budget);
  void finishCycle();
  void fullCycle();
  void pace(uint32_t words);
  State st = IDLE;
  std::vector<Ref> gray;
  size_t sweepPos = BASE, slice, debt = 0;
  bool lastWasFull = false;
  uint64_t cycleLive = 0, cycleReclaimed = 0;
};

}  // namespace reaper
