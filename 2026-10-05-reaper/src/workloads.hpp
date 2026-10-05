#pragma once
#include "heap.hpp"
#include <functional>

namespace reaper {

struct Rng {
  uint64_t s;
  explicit Rng(uint64_t seed) : s(seed * 0x9E3779B97F4A7C15ull + 0x1234567ull) { next(); }
  uint64_t next() {
    uint64_t z = (s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
  }
  uint32_t below(uint32_t n) { return (uint32_t)(next() % n); }
};

// A deterministic mutator. Its decisions may depend only on address-independent state
// (slot nullness, object shapes, data it wrote) so two heaps given the same seed stay in lockstep.
class Mutator {
 public:
  virtual ~Mutator() = default;
  virtual void step(Heap& h) = 0;       // one unit of work
  virtual void finish(Heap& h) = 0;     // self-check: throws std::runtime_error on corrupted data
  virtual uint64_t checksum() const { return 0; }   // fold of everything the mutator *read*
};

struct WorkloadInfo { std::string name, desc; size_t defaultSteps, defaultHeap; };
std::vector<WorkloadInfo> workloadInfos();
// heapWords lets workloads size their live set relative to the heap
std::unique_ptr<Mutator> makeMutator(const std::string& name, uint64_t seed, size_t heapWords);

struct RunResult { double wall_ms = 0; std::string error; uint64_t checksum = 0; };
RunResult runWorkload(Heap& h, Mutator& m, size_t steps, size_t verifyEvery = 0);

struct FuzzReport { bool ok = true; std::string detail; size_t steps = 0, checks = 0; };
// Run `steps` of the mutator on `target` and on a never-collecting oracle in lockstep; compare
// canonical graph hash + read checksum every `checkEvery` steps and run the heap verifier.
FuzzReport differentialRun(const std::string& kind, const std::string& workload, uint64_t seed, size_t steps,
                           size_t heapWords, size_t checkEvery, size_t param = 0);

}  // namespace reaper
