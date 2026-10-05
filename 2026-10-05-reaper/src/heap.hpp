// Reaper — core heap definitions.
#pragma once
#include <cstdint>
#include <cstring>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace reaper {

using Word = uint64_t;
using Ref = uint32_t;            // word index into the arena; 0 == null
constexpr Ref NIL = 0;
constexpr size_t HDR = 2;        // header words: [meta][aux]
constexpr size_t BASE = 2;       // first usable arena word (0..1 reserved so NIL is never valid)
constexpr size_t NROOTS = 64;
constexpr Word POISON = 0xDEADDEADDEADDEADull;
constexpr unsigned TAG_FREE = 0xFF;

// meta word layout
//  [0..31] size in words (incl. header)  [32..47] #pointer slots  [48] mark  [49] forwarded
//  [50] remembered   [56..63] tag
constexpr Word MARK_BIT = 1ull << 48, FWD_BIT = 1ull << 49, REM_BIT = 1ull << 50;

struct OutOfMemory : std::runtime_error {
  explicit OutOfMemory(const std::string& m) : std::runtime_error(m) {}
};

struct Pause { double start_ms; double dur_ms; char kind; };  // kind: m=minor M=major s=step c=full cycle

struct Stats {
  uint64_t allocs = 0, alloc_words = 0;
  uint64_t minor_gcs = 0, major_gcs = 0, inc_steps = 0;
  uint64_t reclaimed_words = 0, copied_words = 0, moved_objects = 0;
  uint64_t peak_live_words = 0;
  uint64_t barrier_hits = 0, remembered_adds = 0;
  std::vector<Pause> pauses;
  double total_pause_ms = 0, max_pause_ms = 0;
  double pct(double p) const;  // pause percentile in ms
};

struct Layout { uint32_t size, nptrs, tag; };  // decoded header

class Heap {
 public:
  explicit Heap(size_t words);
  virtual ~Heap() = default;
  virtual std::string name() const = 0;

  // ---- mutator API (all references live in root slots so objects may move) ----
  void newObj(size_t dst, uint32_t nptrs, uint32_t ndata, uint32_t tag = 1);
  void store(size_t objSlot, uint32_t i, size_t srcSlot);   // obj.field[i] = src   (barriered)
  void storeNil(size_t objSlot, uint32_t i);
  void load(size_t dst, size_t objSlot, uint32_t i);        // dst = obj.field[i]
  void setData(size_t slot, uint32_t j, Word v);
  Word getData(size_t slot, uint32_t j) const;
  void move(size_t dst, size_t src) { roots[dst] = roots[src]; }
  void clear(size_t slot) { roots[slot] = NIL; }
  uint32_t nptrsOf(size_t slot) const { return nptrs(roots[slot]); }
  uint32_t ndataOf(size_t slot) const { Ref r = roots[slot]; return size(r) - HDR - nptrs(r); }
  bool isNull(size_t slot) const { return roots[slot] == NIL; }
  void gc(bool full = true);                                // explicit collection request

  // ---- object access ----
  Word& meta(Ref r) { return mem[r]; }
  Word meta(Ref r) const { return mem[r]; }
  uint32_t size(Ref r) const { return (uint32_t)(mem[r] & 0xFFFFFFFFu); }
  uint32_t nptrs(Ref r) const { return (uint32_t)((mem[r] >> 32) & 0xFFFF); }
  uint32_t tag(Ref r) const { return (uint32_t)(mem[r] >> 56); }
  Ref field(Ref r, uint32_t i) const { return (Ref)mem[r + HDR + i]; }
  Word& fieldRaw(Ref r, uint32_t i) { return mem[r + HDR + i]; }
  Word& dataRaw(Ref r, uint32_t j) { return mem[r + HDR + nptrs(r) + j]; }
  static Word makeMeta(uint32_t size, uint32_t nptrs, uint32_t tag) {
    return (Word)size | ((Word)nptrs << 32) | ((Word)tag << 56);
  }

  // ---- introspection ----
  virtual size_t capacityWords() const { return mem.size() - BASE; }
  virtual size_t usedWords() const = 0;                       // words currently occupied (live+garbage, excl. free)
  // visit every block (live, garbage or free) in address order: (ref, isFree)
  virtual void walk(const std::function<void(Ref, bool)>& f) const = 0;
  // state of each arena word for the visualiser: 0=unused/free 1=object 2=young object
  virtual void map(std::vector<uint8_t>& out) const;
  virtual std::string verifyExtra() const { return ""; }    // collector-specific invariants
  virtual bool freeBlocksPoisoned() const { return false; }  // walk() free blocks must be fully poisoned
  virtual double fragmentation() const { return 0.0; }       // 1 - largest_free/total_free
  virtual std::string describe() const { return ""; }

  // graph introspection (address independent)
  uint64_t graphHash(size_t* liveObjects = nullptr, size_t* liveWords = nullptr) const;
  // returns "" if healthy, else a description of the first violation
  std::string verify() const;

  std::vector<Ref> roots;
  std::vector<Word> mem;
  Stats stats;
  bool poisoning = true;

  // pause bookkeeping used by collectors
  void recordPause(double start_ms, double dur_ms, char kind);
  static double nowMs();
  double t0 = 0;

 protected:
  // Raw allocation of `words` total words; returns 0 on failure (no GC).
  virtual Ref tryAlloc(uint32_t words) = 0;   // must return exactly `words` words (never padded)
  // Called when tryAlloc failed. `attempt` counts 0,1,2...; return false to give up (OOM).
  virtual bool collectForAlloc(uint32_t words, int attempt) = 0;
  virtual void collectExplicit(bool full) = 0;
  virtual void onStore(Ref obj, Ref val) {}                   // write barrier hook
  virtual void onAllocated(Ref) {}                            // post-alloc hook (e.g. allocate black)
  virtual bool isYoung(Ref) const { return false; }
  void poison(size_t from, size_t to);
  void touchLive(size_t words);

  // shared marking helper over roots (explicit stack, no recursion)
  void markFromRoots(std::vector<Ref>& stack, uint64_t* liveWords = nullptr);
  void markObject(Ref r, std::vector<Ref>& stack);
  // Lisp2 sliding compaction of the marked objects in `regions` ([lo,hi) block ranges, ascending)
  // down to BASE. Returns new top, or SIZE_MAX (marks cleared, heap untouched) if it exceeds `limit`.
  size_t compactRegions(const std::vector<std::pair<size_t, size_t>>& regions, size_t limit);
  void drainMarks(std::vector<Ref>& stack, uint64_t* liveWords);
  friend struct HeapTestAccess;
};

std::unique_ptr<Heap> makeHeap(const std::string& kind, size_t words, size_t param = 0);
std::vector<std::string> heapKinds();   // real collectors (excl. oracle)

}  // namespace reaper
