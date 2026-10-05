#include "collectors.hpp"
#include "report.hpp"
#include "workloads.hpp"
#include <algorithm>
#include <cstdio>
#include <fstream>

namespace reaper {

static std::vector<std::string> pick(const std::string& v, const std::vector<std::string>& all, const char* what) {
  if (v == "all") return all;
  if (std::find(all.begin(), all.end(), v) == all.end()) {
    std::string l;
    for (auto& s : all) l += " " + s;
    throw std::invalid_argument(std::string("unknown ") + what + " '" + v + "' (choose:" + l + ")");
  }
  return {v};
}
static std::vector<std::string> workloadNames() {
  std::vector<std::string> n;
  for (auto& w : workloadInfos()) n.push_back(w.name);
  return n;
}
static size_t stepsFor(const std::string& w, const Args& a, double scale = 1.0) {
  for (auto& i : workloadInfos())
    if (i.name == w) return a.has("steps") ? (size_t)a.num("steps", 0) : std::max<size_t>(1, (size_t)(i.defaultSteps * scale));
  return 0;
}

int cmdList() {
  std::puts("collectors:");
  for (auto& k : heapKinds()) std::printf("  %-13s %s\n", k.c_str(), makeHeap(k, 4096)->describe().c_str());
  std::puts("  nogc          oracle: bump allocator, never collects");
  std::puts("workloads:");
  for (auto& w : workloadInfos()) std::printf("  %-13s %s (default %zu steps)\n", w.name.c_str(), w.desc.c_str(), w.defaultSteps);
  return 0;
}

static void printStats(Heap& h, const RunResult& r) {
  const Stats& s = h.stats;
  std::printf("  %-12s wall %8.1f ms | gcs: %llu minor %llu major %llu steps | pause: total %.1f ms, max %.3f ms, p99 %.3f ms\n",
              h.name().c_str(), r.wall_ms, (unsigned long long)s.minor_gcs, (unsigned long long)s.major_gcs,
              (unsigned long long)s.inc_steps, s.total_pause_ms, s.max_pause_ms, s.pct(99));
  std::printf("  %-12s alloc %llu objs / %llu words | reclaimed %llu | moved %llu objs | peak live %llu words | frag %.2f\n", "",
              (unsigned long long)s.allocs, (unsigned long long)s.alloc_words, (unsigned long long)s.reclaimed_words,
              (unsigned long long)s.moved_objects, (unsigned long long)s.peak_live_words, h.fragmentation());
  if (s.barrier_hits) std::printf("  %-12s write barrier: %llu old->young stores, %llu remembered-set inserts\n", "",
                                  (unsigned long long)s.barrier_hits, (unsigned long long)s.remembered_adds);
}

int cmdRun(const Args& a) {
  if (a.pos.size() < 2) throw std::invalid_argument("usage: reaper run <gc> <workload> [--heap N --steps N --seed N]");
  size_t heap = a.num("heap", 1u << 20);
  auto h = makeHeap(a.pos[0], heap, a.num("param", 0));
  std::string w = a.pos[1];
  auto m = makeMutator(w, a.num("seed", 1), heap);
  size_t steps = stepsFor(w, a);
  std::printf("%s on %s (%zu words, %zu steps) — %s\n", w.c_str(), h->name().c_str(), heap, steps, h->describe().c_str());
  RunResult r = runWorkload(*h, *m, steps, a.num("verify-every", 0));
  if (!r.error.empty()) { std::printf("  FAILED: %s\n", r.error.c_str()); return 1; }
  std::string v = h->verify();
  printStats(*h, r);
  std::printf("  final heap verify: %s | graph hash %016llx\n", v.empty() ? "ok" : v.c_str(), (unsigned long long)h->graphHash());
  return v.empty() ? 0 : 1;
}

int cmdFuzz(const Args& a) {
  auto kinds = pick(a.str("gc", "all"), heapKinds(), "collector");
  auto works = pick(a.str("workload", "graph-fuzz"), workloadNames(), "workload");
  size_t seeds = a.num("seeds", 5), steps = a.num("steps", 20000), heap = a.num("heap", 1u << 14);
  size_t every = a.num("check-every", 250);
  size_t bad = 0, total = 0, checks = 0;
  for (auto& k : kinds)
    for (auto& w : works) {
      size_t okSeeds = 0;
      for (size_t s = 1; s <= seeds; s++) {
        size_t st = steps;
        if (w == "binary-trees") st = std::min<size_t>(st, 200);
        FuzzReport r = differentialRun(k, w, s, st, heap, every, a.num("param", 0));
        total++;
        checks += r.checks;
        if (r.ok) okSeeds++; else { bad++; std::printf("  FAIL %s\n", r.detail.c_str()); }
      }
      std::printf("%-12s %-13s %zu/%zu seeds identical to oracle\n", k.c_str(), w.c_str(), okSeeds, seeds);
    }
  std::printf("%zu runs, %zu oracle comparisons, %zu failures\n", total, checks, bad);
  return bad ? 1 : 0;
}

int cmdBench(const Args&) { return 0; }
int cmdScript(const Args&) { return 0; }
int cmdViz(const Args&) { return 0; }

}  // namespace reaper
