// Reaper test suite — no framework, just checks and a summary.
#include "collectors.hpp"
#include "workloads.hpp"
#include <cstdio>
#include <functional>
#include <set>

using namespace reaper;

static int g_checks = 0, g_fail = 0;
static std::string g_cur;
#define CHECK(c) do { g_checks++; if (!(c)) { g_fail++; std::printf("  FAIL [%s] %s:%d: %s\n", g_cur.c_str(), __FILE__, __LINE__, #c); } } while (0)
#define CHECK_EQ(a, b) do { g_checks++; auto _a = (a); auto _b = (b); if (!(_a == _b)) { g_fail++; std::printf("  FAIL [%s] %s:%d: %s == %s (%lld vs %lld)\n", g_cur.c_str(), __FILE__, __LINE__, #a, #b, (long long)_a, (long long)_b); } } while (0)
#define CHECK_VERIFY(heap) do { g_checks++; std::string _v = (heap).verify(); if (!_v.empty()) { g_fail++; std::printf("  FAIL [%s] %s:%d: verify: %s\n", g_cur.c_str(), __FILE__, __LINE__, _v.c_str()); } } while (0)
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

  std::printf("\n%d checks, %d failures\n", g_checks, g_fail);
  (void)argc; (void)argv;
  return g_fail ? 1 : 0;
}
