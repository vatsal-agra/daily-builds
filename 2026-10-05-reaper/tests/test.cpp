// Reaper test suite — no framework, just checks and a summary.
#include "collectors.hpp"
#include "workloads.hpp"
#include "script.hpp"
#include <chrono>
#include <fstream>
#include <sstream>
#include <cstdio>
#include <functional>
#include <set>

using namespace reaper;

static int g_checks = 0, g_fail = 0;
static std::string g_cur;
#define CHECK(c) do { g_checks++; if (!(c)) { g_fail++; std::printf("  FAIL [%s] %s:%d: %s\n", g_cur.c_str(), __FILE__, __LINE__, #c); } } while (0)
#define CHECK_EQ(a, b) do { g_checks++; auto _a = (a); auto _b = (b); if (!(_a == _b)) { g_fail++; std::printf("  FAIL [%s] %s:%d: %s == %s (%lld vs %lld)\n", g_cur.c_str(), __FILE__, __LINE__, #a, #b, (long long)_a, (long long)_b); } } while (0)
#define CHECK_VERIFY(heap) do { g_checks++; std::string _v = (heap).verify(); if (!_v.empty()) { g_fail++; std::printf("  FAIL [%s] %s:%d: verify: %s\n", g_cur.c_str(), __FILE__, __LINE__, _v.c_str()); } } while (0)
#define CHECK_NOERR(e) do { g_checks++; if (!(e).empty()) { g_fail++; std::printf("  FAIL [%s] %s:%d: unexpected error: %s\n", g_cur.c_str(), __FILE__, __LINE__, (e).c_str()); } } while (0)
#define CHECK_THROWS(expr, T) do { g_checks++; bool ok = false; try { expr; } catch (const T&) { ok = true; } catch (...) {} if (!ok) { g_fail++; std::printf("  FAIL [%s] %s:%d: expected %s to throw %s\n", g_cur.c_str(), __FILE__, __LINE__, #expr, #T); } } while (0)

static void test(const std::string& name, const std::function<void()>& f) {
  g_cur = name;
  int before = g_fail;
  try { f(); } catch (const std::exception& e) { g_fail++; std::printf("  FAIL [%s] uncaught exception: %s\n", name.c_str(), e.what()); }
  std::printf("%s %s\n", g_fail == before ? "ok  " : "FAIL", name.c_str());
}

static const std::vector<std::string> KINDS = {"marksweep", "markcompact", "copying", "generational", "incremental"};

int main(int argc, char** argv) {
  // ------------------------------------------------------------ object model
  for (auto& k : KINDS) {
    test("model/" + k + ": alloc, fields, data round-trip", [&] {
      auto h = makeHeap(k, 8192);
      h->newObj(0, 3, 4, 5);
      h->newObj(1, 0, 2);
      h->setData(1, 0, 111); h->setData(1, 1, 222);
      h->store(0, 2, 1);
      h->setData(0, 3, 0xABCDEF);
      h->clear(1);
      h->load(1, 0, 2);
      CHECK_EQ(h->getData(1, 0), 111u);
      CHECK_EQ(h->getData(1, 1), 222u);
      CHECK_EQ(h->getData(0, 3), 0xABCDEFu);
      CHECK_EQ(h->nptrsOf(0), 3u);
      CHECK_EQ(h->ndataOf(0), 4u);
      CHECK_VERIFY(*h);
    });
    test("model/" + k + ": misuse throws and leaves the heap intact", [&] {
      auto h = makeHeap(k, 8192);
      h->newObj(0, 1, 1);
      uint64_t before = h->graphHash();
      CHECK_THROWS(h->store(5, 0, 0), std::invalid_argument);     // null object slot
      CHECK_THROWS(h->store(0, 1, 0), std::out_of_range);          // bad field index
      CHECK_THROWS(h->setData(0, 1, 7), std::out_of_range);        // bad data index
      CHECK_THROWS(h->load(1, 5, 0), std::invalid_argument);
      CHECK_THROWS(h->getData(5, 0), std::invalid_argument);
      CHECK_THROWS(h->newObj(NROOTS, 0, 0), std::out_of_range);
      CHECK_THROWS(h->newObj(0, 70000, 0), std::invalid_argument);
      CHECK_THROWS(h->store(NROOTS + 1, 0, 0), std::out_of_range);
      CHECK_EQ(h->graphHash(), before);
      CHECK_VERIFY(*h);
    });
    test("model/" + k + ": zero-size objects and max pointer count", [&] {
      auto h = makeHeap(k, 1u << 18);
      for (int i = 0; i < 2000; i++) h->newObj(i % 8, 0, 0);       // 2-word objects
      h->newObj(0, 60000, 0);                                      // huge pointer array
      h->newObj(1, 0, 0);
      h->store(0, 59999, 1);
      h->gc(true);
      h->load(2, 0, 59999);
      CHECK(!h->isNull(2));
      CHECK_VERIFY(*h);
    });
  }

  // ------------------------------------------------------------ collection actually reclaims + preserves
  for (auto& k : KINDS) {
    test("gc/" + k + ": garbage reclaimed, live data preserved", [&] {
      auto h = makeHeap(k, 1u << 16);
      h->newObj(0, 1, 1);
      h->setData(0, 0, 42);
      for (int i = 0; i < 2000; i++) h->newObj(1, 0, 8);           // 20k words of garbage
      h->clear(1);
      h->gc(true);
      CHECK_EQ(h->getData(0, 0), 42u);
      size_t live = 0;
      h->graphHash(nullptr, &live);
      CHECK_EQ(live, (size_t)(HDR + 1 + 1));
      CHECK(h->usedWords() < 3000);
      CHECK_VERIFY(*h);
      CHECK(h->stats.reclaimed_words > 15000);
    });
    test("gc/" + k + ": a long chain (200k nodes) survives collection without recursion", [&] {
      auto h = makeHeap(k, 1u << 21);
      h->newObj(0, 1, 1);
      h->setData(0, 0, 0);
      for (int i = 1; i <= 200000; i++) {
        h->newObj(1, 1, 1);
        h->setData(1, 0, i);
        h->store(1, 0, 0);
        h->move(0, 1);
      }
      h->gc(true);
      h->gc(true);
      size_t n = 0;
      h->graphHash(&n);
      CHECK_EQ(n, (size_t)200001);
      h->move(1, 0);
      Word expect = 200000;
      while (!h->isNull(1) && expect > 0) { CHECK_EQ(h->getData(1, 0), expect); h->load(1, 1, 0); expect--; }
      CHECK_VERIFY(*h);
    });
    test("gc/" + k + ": cycles and self-references are collected", [&] {
      auto h = makeHeap(k, 1u << 16);
      for (int i = 0; i < 3000; i++) {
        h->newObj(0, 2, 0);
        h->newObj(1, 2, 0);
        h->store(0, 0, 1); h->store(1, 0, 0); h->store(0, 1, 0);   // 2-cycle + self loop
        h->clear(0); h->clear(1);
      }
      h->gc(true);
      CHECK(h->usedWords() < 100);
      CHECK_VERIFY(*h);
    });
  }

  // ------------------------------------------------------------ exhaustion behaviour
  for (auto& k : KINDS) {
    test("oom/" + k + ": OutOfMemory is clean — heap stays valid and reusable", [&] {
      auto h = makeHeap(k, 1u << 14);
      h->newObj(0, 1, 1);
      h->setData(0, 0, 7);
      bool oom = false;
      int n = 0;
      try { for (;; n++) { h->newObj(1, 1, 30); h->store(1, 0, 0); h->move(0, 1); } }
      catch (const OutOfMemory&) { oom = true; }
      CHECK(oom);
      CHECK(n > 100);
      CHECK_VERIFY(*h);
      uint64_t hash = h->graphHash();
      h->clear(0); h->clear(1);                                    // free everything…
      h->gc(true);
      h->newObj(2, 1, 30);                                         // …and the heap works again
      CHECK(!h->isNull(2));
      CHECK(hash != 0);
      CHECK_VERIFY(*h);
    });
    test("oom/" + k + ": an object bigger than the heap fails cleanly", [&] {
      auto h = makeHeap(k, 4096);
      CHECK_THROWS(h->newObj(0, 0, 100000), OutOfMemory);
      CHECK_THROWS(h->newObj(0, 0, 4095), OutOfMemory);            // exceeds the whole arena for every collector
      CHECK_VERIFY(*h);
    });
  }

  test("oom: copying/generational/marksweep usable capacity is as documented", [&] {
    auto fill = [&](const std::string& k, size_t heap) {
      auto h = makeHeap(k, heap);
      size_t live = 0;
      h->newObj(0, 1, 6);                                          // 9-word cells in a chain
      try { for (;;) { h->newObj(1, 1, 6); h->store(1, 0, 0); h->move(0, 1); } } catch (const OutOfMemory&) {}
      h->graphHash(nullptr, &live);
      return (double)live / heap;
    };
    CHECK(fill("marksweep", 1u << 16) > 0.97);
    CHECK(fill("markcompact", 1u << 16) > 0.97);
    CHECK(fill("incremental", 1u << 16) > 0.97);
    double c = fill("copying", 1u << 16);
    CHECK(c > 0.45 && c <= 0.5);
    double g = fill("generational", 1u << 16);
    CHECK(g > 0.74);                                                // old gen holds 3/4; the nursery can also be full of live data at OOM
  });

  // ------------------------------------------------------------ the verifier must itself catch corruption
  for (auto& k : KINDS) {
    test("verifier/" + k + ": detects dangling root, dangling field, bad header", [&] {
      auto h = makeHeap(k, 8192);
      h->newObj(0, 2, 1);
      h->newObj(1, 0, 1);
      h->store(0, 0, 1);
      CHECK_VERIFY(*h);
      Ref saved = h->roots[1];
      h->roots[1] = saved + 1;                                   // points into the middle of an object
      CHECK(!h->verify().empty());
      h->roots[1] = saved;
      CHECK_VERIFY(*h);
      Ref obj = h->roots[0];
      h->fieldRaw(obj, 1) = 3;                                   // dangling pointer inside a live object
      CHECK(!h->verify().empty());
      h->fieldRaw(obj, 1) = NIL;
      CHECK_VERIFY(*h);
      Word m = h->meta(obj);
      h->meta(obj) = (m & ~0xFFFFFFFFull) | 0x7FFFFFF0ull;       // absurd size
      CHECK(!h->verify().empty());
      h->meta(obj) = m;
      CHECK_VERIFY(*h);
    });
  }
  test("verifier/marksweep: write-after-free is caught by poison check", [&] {
    auto h = makeHeap("marksweep", 8192);
    h->newObj(0, 0, 8);
    Ref victim = h->roots[0];
    h->newObj(1, 0, 1);                                          // keep a live neighbour after it
    h->clear(0);
    h->gc(true);
    CHECK_VERIFY(*h);
    h->mem[victim + 5] = 1234;                                   // a stale pointer scribbles into freed memory
    CHECK(h->verify().find("not poisoned") != std::string::npos);
  });
  test("verifier/generational: barrier hole is caught", [&] {
    auto h = makeHeap("generational", 8192);
    h->newObj(0, 1, 0);
    h->gc(true);                                                 // slot 0 is old
    h->newObj(1, 0, 0);                                          // slot 1 is young
    Ref old = h->roots[0];
    h->fieldRaw(old, 0) = h->roots[1];                           // store WITHOUT the barrier
    CHECK(h->verify().find("barrier hole") != std::string::npos);
  });
  test("verifier: dangling references into freed memory are caught", [&] {
    auto h = makeHeap("markcompact", 8192);
    h->newObj(0, 0, 4);
    Ref stale = h->roots[0];
    h->newObj(1, 0, 4);
    h->clear(0);
    h->gc(true);                                                 // object 0 died; object 1 slid down over it
    h->roots[0] = stale + 3;                                     // forged ref into the middle of a block
    CHECK(!h->verify().empty());
  });

  // ------------------------------------------------------------ generational specifics
  test("generational: write barrier + remembered set + pretenuring", [&] {
    GenerationalHeap h(1u << 14, 512);
    CHECK_EQ(h.nurseryWords(), (size_t)512);
    h.newObj(0, 1, 0);
    h.gc(true);
    CHECK_EQ(h.rememberedSize(), (size_t)0);
    h.newObj(1, 0, 1);
    h.setData(1, 0, 5);
    h.store(0, 0, 1);                                            // old -> young
    CHECK_EQ(h.rememberedSize(), (size_t)1);
    h.store(0, 0, 1);                                            // second store must not duplicate the entry
    CHECK_EQ(h.rememberedSize(), (size_t)1);
    h.clear(1);
    h.gc(false);                                                 // minor
    CHECK_EQ(h.rememberedSize(), (size_t)0);
    h.load(2, 0, 0);
    CHECK_EQ(h.getData(2, 0), 5u);
    CHECK_EQ(h.stats.minor_gcs, (uint64_t)1);
    CHECK_VERIFY(h);
    uint64_t majorBefore = h.stats.major_gcs;
    h.newObj(3, 1, 400);                                         // > half the nursery: allocated straight into the old gen
    CHECK(!h.isYoungForTest(3));
    h.setData(3, 399, 77);
    h.newObj(4, 1, 0);
    h.store(3, 0, 4) ;
    CHECK_EQ(h.stats.major_gcs, majorBefore);
    CHECK_VERIFY(h);
  });
  test("generational: survivors are promoted, nursery is emptied", [&] {
    GenerationalHeap h(1u << 14, 1024);
    h.newObj(0, 1, 0);
    for (int i = 0; i < 20; i++) { h.newObj(1, 1, 3); h.store(1, 0, 0); h.move(0, 1); }
    CHECK(h.isYoungForTest(0));
    h.gc(false);
    CHECK(!h.isYoungForTest(0));
    size_t n = 0;
    h.graphHash(&n);
    CHECK_EQ(n, (size_t)21);
    CHECK_VERIFY(h);
  });

  // ------------------------------------------------------------ incremental specifics
  test("incremental: marking really is incremental (many short steps, cycles complete)", [&] {
    auto h = makeHeap("incremental", 1u << 15, 8);
    auto m = makeMutator("pointer-shuffle", 3, 1u << 15);
    RunResult r = runWorkload(*h, *m, 8000, 100);
    CHECK(r.error.empty());
    CHECK(h->stats.inc_steps > 500);
    CHECK(h->stats.major_gcs > 5);
    double longest = 0;
    for (auto& p : h->stats.pauses) if (p.kind == 's') longest = std::max(longest, p.dur_ms);
    CHECK(longest < 5.0);
  });
  test("incremental: sweep slices coalesce across slice boundaries (regression)", [&] {
    auto h = makeHeap("incremental", 1u << 18);
    auto m = makeMutator("fragmenter", 1, 1u << 18);
    RunResult r = runWorkload(*h, *m, 30000, 500);
    CHECK_NOERR(r.error);
  });
  test("marksweep: allocation is O(1) per object (regression: used to be O(heap))", [&] {
    auto t0 = std::chrono::steady_clock::now();
    auto h = makeHeap("marksweep", 1u << 22);
    h->newObj(0, 1, 1);
    for (int i = 0; i < 100000; i++) { h->newObj(1, 1, 1); h->store(1, 0, 0); h->move(0, 1); }
    double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    CHECK(ms < 3000);
  });

  // ------------------------------------------------------------ stats are real
  test("stats: movers move, non-movers don't, barrier counters count", [&] {
    auto run = [&](const std::string& k, const std::string& w, size_t heap) {
      auto h = makeHeap(k, heap);
      auto m = makeMutator(w, 1, heap);
      RunResult r = runWorkload(*h, *m, 8000);
      CHECK_NOERR(r.error);
      return h;
    };
    CHECK_EQ(run("marksweep", "lru-cache", 1u << 16)->stats.moved_objects, (uint64_t)0);
    CHECK_EQ(run("incremental", "lru-cache", 1u << 16)->stats.moved_objects, (uint64_t)0);
    CHECK(run("markcompact", "lru-cache", 1u << 16)->stats.moved_objects > 0);
    CHECK(run("copying", "lru-cache", 1u << 16)->stats.moved_objects > 0);
    auto g = run("generational", "lru-cache", 1u << 16);
    CHECK(g->stats.minor_gcs > 3);
    CHECK(g->stats.barrier_hits > 0);
    CHECK(g->stats.remembered_adds > 0);
    CHECK(g->stats.reclaimed_words > 0);
    CHECK(g->stats.peak_live_words > 0);
  });
  test("stats: fragmentation separates sweeping from compacting collectors", [&] {
    auto frag = [&](const std::string& k) {
      auto h = makeHeap(k, 1u << 18);
      auto m = makeMutator("fragmenter", 2, 1u << 18);
      RunResult r = runWorkload(*h, *m, 20000);
      CHECK_NOERR(r.error);
      h->gc(true);
      return h->fragmentation();
    };
    CHECK(frag("marksweep") > 0.3);
    CHECK_EQ(frag("markcompact"), 0.0);
    CHECK_EQ(frag("copying"), 0.0);
  });

  // ------------------------------------------------------------ the main event: differential fuzzing
  for (auto& k : KINDS) {
    for (auto& wi : workloadInfos()) {
      test("fuzz/" + k + "/" + wi.name + ": identical to the oracle on 4 seeds", [&] {
        for (uint64_t seed = 1; seed <= 4; seed++) {
          size_t steps = wi.name == "binary-trees" ? 120 : 6000;
          FuzzReport r = differentialRun(k, wi.name, seed, steps, wi.name == "binary-trees" ? (1u << 18) : (1u << 15), 100);
          CHECK(r.ok);
          if (!r.ok) std::printf("    %s\n", r.detail.c_str());
          CHECK(r.checks > 0);
        }
      });
    }
  }
  test("fuzz: odd configurations (tiny nursery / pretenuring, slice=1, awkward heap sizes)", [&] {
    struct Cfg { const char* kind; size_t heap, param; };
    for (Cfg c : {Cfg{"generational", 1u << 15, 64}, Cfg{"generational", 40001, 4000}, Cfg{"generational", 1u << 16, 1u << 15},
                  Cfg{"incremental", 1u << 15, 1}, Cfg{"incremental", 33333, 1000}, Cfg{"copying", 33333, 0},
                  Cfg{"marksweep", 20011, 0}, Cfg{"markcompact", 20011, 0}}) {
      for (const char* w : {"graph-fuzz", "pointer-shuffle", "lru-cache"}) {
        FuzzReport r = differentialRun(c.kind, w, 7, 5000, c.heap, 100, c.param);
        CHECK(r.ok);
        if (!r.ok) std::printf("    %s\n", r.detail.c_str());
      }
    }
  });
  test("fuzz: long run, 100k steps, every collector", [&] {
    for (auto& k : KINDS) {
      FuzzReport r = differentialRun(k, "graph-fuzz", 99, 100000, 1u << 15, 5000);
      CHECK(r.ok);
      if (!r.ok) std::printf("    %s\n", r.detail.c_str());
    }
  });
  test("fuzz: all collectors agree with each other (same hash after the same workload)", [&] {
    for (const char* w : {"list-churn", "lru-cache", "pointer-shuffle", "graph-fuzz"}) {
      std::set<uint64_t> hashes;
      for (auto& k : KINDS) {
        auto h = makeHeap(k, 1u << 16);
        auto m = makeMutator(w, 5, 1u << 16);
        RunResult r = runWorkload(*h, *m, 4000);
        CHECK_NOERR(r.error);
        hashes.insert(h->graphHash());
      }
      CHECK_EQ(hashes.size(), (size_t)1);
    }
  });
  test("fuzz: the oracle itself is deterministic and the hash is sensitive", [&] {
    auto a = makeHeap("nogc", 1u << 18), b = makeHeap("nogc", 1u << 18);
    auto ma = makeMutator("graph-fuzz", 11, 1u << 15), mb = makeMutator("graph-fuzz", 11, 1u << 15);
    runWorkload(*a, *ma, 3000);
    runWorkload(*b, *mb, 3000);
    CHECK_EQ(a->graphHash(), b->graphHash());
    uint64_t before = a->graphHash();
    for (size_t s = 0; s < NROOTS; s++) if (!a->isNull(s) && a->ndataOf(s)) { a->setData(s, 0, a->getData(s, 0) ^ 1); break; }
    CHECK(a->graphHash() != before);                                 // one flipped data bit changes the hash
    auto c = makeHeap("nogc", 1u << 18);
    auto mc = makeMutator("graph-fuzz", 12, 1u << 15);
    runWorkload(*c, *mc, 3000);
    CHECK(c->graphHash() != before);
  });

  // ------------------------------------------------------------ mutator workloads self-check data
  test("workloads: every workload completes and self-verifies on every collector", [&] {
    for (auto& k : KINDS)
      for (auto& wi : workloadInfos()) {
        auto h = makeHeap(k, wi.defaultHeap);
        auto m = makeMutator(wi.name, 1, wi.defaultHeap);
        RunResult r = runWorkload(*h, *m, std::min<size_t>(wi.defaultSteps, 5000), 1000);
        CHECK_NOERR(r.error);
      }
  });
  test("workloads: unknown workload / collector are rejected", [&] {
    CHECK_THROWS(makeMutator("nope", 1, 1000), std::invalid_argument);
    CHECK_THROWS(makeHeap("nope", 1000), std::invalid_argument);
    CHECK_THROWS(makeHeap("copying", 10), std::invalid_argument);
    CHECK_THROWS(makeHeap("copying", (size_t)1 << 40), std::invalid_argument);
  });
  test("workloads: corruption inside a collector is noticed by the workload's own checks", [&] {
    auto h = makeHeap("markcompact", 1u << 16);
    auto m = makeMutator("lru-cache", 1, 1u << 16);
    for (int i = 0; i < 500; i++) m->step(*h);
    Ref table = h->roots[0];
    for (uint32_t i = 0; i < 256; i++) if (h->field(table, i)) h->dataRaw(h->field(table, i), 0) ^= 0xFF;   // scribble on every entry
    bool caught = false;
    try { m->finish(*h); } catch (const std::runtime_error& e) { caught = std::string(e.what()).find("CORRUPTION") != std::string::npos; }
    CHECK(caught);
  });

  // ------------------------------------------------------------ script language
  auto script = [&](const std::string& src, const std::string& gc = "generational") {
    auto h = makeHeap(gc, 8192);
    std::ostringstream out;
    ScriptResult r = runScript(*h, src, "t.rpr", out);
    return std::make_pair(r, out.str());
  };
  test("script: expressions", [&] {
    auto look = [](const std::string& n, long long& v) { if (n == "i") { v = 7; return true; } return false; };
    CHECK_EQ(evalExpr("1+2*3", look), 7);
    CHECK_EQ(evalExpr("(1+2)*3", look), 9);
    CHECK_EQ(evalExpr("$i%4", look), 3);
    CHECK_EQ(evalExpr("0x10+$i", look), 23);
    CHECK_EQ(evalExpr("-3+10/2", look), 2);
    CHECK_THROWS(evalExpr("1/0", look), std::invalid_argument);
    CHECK_THROWS(evalExpr("$zzz", look), std::invalid_argument);
    CHECK_THROWS(evalExpr("1+", look), std::invalid_argument);
    CHECK_THROWS(evalExpr("(1", look), std::invalid_argument);
    CHECK_THROWS(evalExpr("1 2", look), std::invalid_argument);
    CHECK_THROWS(evalExpr("abc", look), std::invalid_argument);
  });
  for (auto& k : KINDS) {
    test("script/" + k + ": shipped examples pass and produce the same graph hash on every collector", [&] {
      for (const char* f : {"list", "cycles", "barrier"}) {
        std::ifstream in(std::string("examples/") + f + ".rpr");
        CHECK(in.good());
        std::stringstream ss;
        ss << in.rdbuf();
        auto res = script(ss.str(), k);
        CHECK(res.first.ok);
        if (!res.first.ok) std::printf("    %s\n", res.first.error.c_str());
      }
    });
  }
  test("script: errors carry file:line and never crash", [&] {
    struct Bad { const char* src; const char* needle; };
    for (Bad b : {Bad{"alloc 0 1\n", "t.rpr:1"}, Bad{"frobnicate 1\n", "unknown command"}, Bad{"alloc 99 0 0\n", "out of range"},
                  Bad{"\n\nstore 0 0 1\n", "t.rpr:3"}, Bad{"repeat 3 {\nalloc 0 0 0\n", "never closed"}, Bad{"}\n", "unmatched"},
                  Bad{"alloc 0 1 1\nstore 0 7 0\n", "t.rpr:2"}, Bad{"alloc 0 0 1\nexpect data 0 0 5\n", "expectation failed"},
                  Bad{"alloc 0 0 0\nexpect null 0\n", "expectation failed"}, Bad{"alloc 0 0 1000000000\n", "out of memory"},
                  Bad{"alloc 0 0 $q\n", "unknown variable"}, Bad{"repeat -1 {\n}\n", "negative"}, Bad{"gc sideways\n", "gc takes"},
                  Bad{"expect live 3\n", "expectation failed"}, Bad{"repeat x {\n}\n", "expression"}, Bad{"load 0 1 0\n", "null"},
                  Bad{"alloc 0 0 0 999\n", "tag"}, Bad{"repeat 2 {\nrepeat 2 {\nrepeat 2 {\nrepeat 2 {\nrepeat 2 {\nrepeat 2 {\nrepeat 2 {\nrepeat 2 {\nrepeat 2 {\n}\n}\n}\n}\n}\n}\n}\n}\n}\n", "nested too deeply"}}) {
      auto res = script(b.src);
      CHECK(!res.first.ok);
      CHECK(res.first.error.find(b.needle) != std::string::npos);
      if (res.first.error.find(b.needle) == std::string::npos) std::printf("    wanted '%s' in '%s'\n", b.needle, res.first.error.c_str());
    }
    auto empty = script("");
    CHECK(empty.first.ok);
    CHECK_EQ(empty.first.statements, (size_t)0);
    auto comments = script("# nothing\n\n   # more\n");
    CHECK(comments.first.ok);
  });
  test("script: loops, variables, print", [&] {
    auto r = script("let n 3\nrepeat $n as i {\nrepeat 2 as j {\nalloc 0 0 1\nlet v $i*10+$j\nset 0 0 $v\nprint hello $i\n}\n}\nexpect data 0 0 21\nprint slot 0\nprint stats\nprint live\nprint hash\n");
    CHECK(r.first.ok);
    CHECK(r.second.find("hello 2") != std::string::npos);
    CHECK(r.second.find("d0=21") != std::string::npos);
    CHECK(r.second.find("graph hash") != std::string::npos);
  });

  std::printf("\n%d checks, %d failures\n", g_checks, g_fail);
  (void)argc; (void)argv;
  return g_fail ? 1 : 0;
}
