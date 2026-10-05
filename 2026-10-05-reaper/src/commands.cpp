#include "collectors.hpp"
#include "report.hpp"
#include "workloads.hpp"
#include "script.hpp"
#include <iostream>
#include <sstream>
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
static size_t heapFor(const std::string& w, const Args& a) {
  for (auto& i : workloadInfos()) if (i.name == w) return a.has("heap") ? (size_t)a.num("heap", 0) : i.defaultHeap;
  return (size_t)a.num("heap", 1u << 16);
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
  for (auto& w : workloadInfos()) std::printf("  %-13s %s (default %zu steps, %zu-word heap)\n", w.name.c_str(), w.desc.c_str(), w.defaultSteps, w.defaultHeap);
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
  a.allow({"heap", "steps", "seed", "param", "verify-every"});
  if (a.pos.size() < 2) throw std::invalid_argument("usage: reaper run <gc> <workload> [--heap N --steps N --seed N]");
  std::string w = a.pos[1];
  size_t heap = heapFor(w, a);
  auto h = makeHeap(a.pos[0], heap, a.num("param", 0));
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
  a.allow({"gc", "workload", "seeds", "steps", "heap", "check-every", "param"});
  auto kinds = pick(a.str("gc", "all"), heapKinds(), "collector");
  auto works = pick(a.str("workload", "graph-fuzz"), workloadNames(), "workload");
  size_t seeds = a.num("seeds", 5), steps = a.num("steps", 20000), heap = a.num("heap", 1u << 14);
  size_t every = a.num("check-every", 250);
  if (seeds == 0 || steps == 0) throw std::invalid_argument("--seeds and --steps must be at least 1");
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

int cmdBench(const Args& a) {
  a.allow({"gc", "workload", "steps", "seed", "scale", "csv", "param", "heap"});
  auto kinds = pick(a.str("gc", "all"), heapKinds(), "collector");
  auto works = pick(a.str("workload", "all"), workloadNames(), "workload");
  double scale = std::stod(a.str("scale", "1"));
  if (!(scale > 0)) throw std::invalid_argument("--scale must be positive");
  std::ofstream csv;
  if (a.has("csv")) {
    csv.open(a.str("csv", ""));
    if (!csv) throw std::runtime_error("cannot write " + a.str("csv", ""));
    csv << "workload,collector,heap_words,steps,wall_ms,alloc_words,mwords_per_s,minor_gcs,major_gcs,inc_steps,total_pause_ms,max_pause_ms,p99_pause_ms,moved_objects,peak_retained_words,fragmentation,error\n";
  }
  int failures = 0;
  for (auto& w : works) {
    size_t heap = heapFor(w, a), steps = stepsFor(w, a, scale);
    std::printf("\n== %s — %zu steps, %zu-word heap ==\n", w.c_str(), steps, heap);
    std::printf("%-13s %9s %9s %7s %7s %10s %10s %10s %9s %6s\n", "collector", "wall ms", "Mw/s", "minor", "major", "pause tot", "pause max", "pause p99", "moved", "frag");
    for (auto& k : kinds) {
      auto h = makeHeap(k, heap, a.num("param", 0));
      auto m = makeMutator(w, a.num("seed", 1), heap);
      RunResult r = runWorkload(*h, *m, steps);
      const Stats& st = h->stats;
      if (!r.error.empty()) {
        failures++;
        std::printf("%-13s FAILED: %s\n", k.c_str(), r.error.c_str());
      } else {
        std::string v = h->verify();
        if (!v.empty()) { failures++; std::printf("%-13s VERIFY FAILED: %s\n", k.c_str(), v.c_str()); continue; }
        double mws = r.wall_ms > 0 ? st.alloc_words / 1e3 / r.wall_ms : 0;
        std::printf("%-13s %9.1f %9.1f %7llu %7llu %9.2fms %9.3fms %9.3fms %9llu %5.0f%%\n", k.c_str(), r.wall_ms, mws,
                    (unsigned long long)st.minor_gcs, (unsigned long long)st.major_gcs, st.total_pause_ms, st.max_pause_ms, st.pct(99),
                    (unsigned long long)st.moved_objects, h->fragmentation() * 100);
      }
      if (csv) {
        char line[512];
        snprintf(line, sizeof line, "%s,%s,%zu,%zu,%.3f,%llu,%.3f,%llu,%llu,%llu,%.4f,%.4f,%.4f,%llu,%llu,%.4f,", w.c_str(), k.c_str(), heap, steps, r.wall_ms,
                 (unsigned long long)st.alloc_words, r.wall_ms > 0 ? st.alloc_words / 1e3 / r.wall_ms : 0.0, (unsigned long long)st.minor_gcs,
                 (unsigned long long)st.major_gcs, (unsigned long long)st.inc_steps, st.total_pause_ms, st.max_pause_ms, st.pct(99),
                 (unsigned long long)st.moved_objects, (unsigned long long)st.peak_live_words, h->fragmentation());
        std::string e = r.error;
        for (char& c : e) if (c == ',' || c == '\n') c = ';';
        csv << line << e << "\n";
      }
    }
  }
  if (csv) std::printf("\nwrote %s\n", a.str("csv", "").c_str());
  return failures ? 1 : 0;
}

int cmdScript(const Args& a) {
  a.allow({"gc", "heap", "param", "no-verify"});
  if (a.pos.size() != 1) throw std::invalid_argument("usage: reaper script <file.rpr> [--gc X] [--heap WORDS]");
  std::ifstream f(a.pos[0]);
  if (!f) throw std::runtime_error("cannot open " + a.pos[0]);
  std::stringstream ss;
  ss << f.rdbuf();
  std::string gc = a.str("gc", "generational");
  auto h = makeHeap(gc, a.num("heap", 1u << 16), a.num("param", 0));
  ScriptResult r = runScript(*h, ss.str(), a.pos[0], std::cout);
  if (!r.ok) { std::fprintf(stderr, "%s\n", r.error.c_str()); return 1; }
  std::string v = a.has("no-verify") ? "" : h->verify();
  std::printf("ok: %zu statements on %s, heap verify %s\n", r.statements, gc.c_str(), v.empty() ? "clean" : v.c_str());
  return v.empty() ? 0 : 1;
}


}  // namespace reaper
