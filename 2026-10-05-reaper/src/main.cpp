#include "cli.hpp"
#include "collectors.hpp"
#include "workloads.hpp"
#include "report.hpp"
#include <cstdio>
#include <cstring>
#include <iostream>

using namespace reaper;

static void usage() {
  std::puts(
      "reaper — a garbage-collector laboratory\n\n"
      "usage:\n"
      "  reaper list                                   collectors and workloads\n"
      "  reaper run <gc> <workload> [opts]             run one workload on one collector\n"
      "  reaper bench [opts]                           all workloads x all collectors\n"
      "  reaper fuzz [opts]                            differential fuzz vs. the never-collecting oracle\n"
      "  reaper script <file.rpr> [--gc X]             run a mutator script\n"
      "  reaper viz <out.html> [opts]                  heap-map + pause-timeline report\n\n"
      "common options: --heap WORDS (default 1048576)  --steps N  --seed N  --param N (nursery / GC slice)\n"
      "run:   --verify-every N      fuzz: --seeds N --gc X --workload W --check-every N");
}

int main(int argc, char** argv) {
  if (argc < 2 || !strcmp(argv[1], "--help") || !strcmp(argv[1], "-h") || !strcmp(argv[1], "help")) { usage(); return argc < 2 ? 2 : 0; }
  try {
    std::string cmd = argv[1];
    Args a = Args::parse(argc, argv, 2);
    if (cmd == "list") return cmdList();
    if (cmd == "run") return cmdRun(a);
    if (cmd == "bench") return cmdBench(a);
    if (cmd == "fuzz") return cmdFuzz(a);
    if (cmd == "script") return cmdScript(a);
    if (cmd == "viz") return cmdViz(a);
    std::fprintf(stderr, "reaper: unknown command '%s'\n\n", cmd.c_str());
    usage();
    return 2;
  } catch (const std::exception& e) {
    std::fprintf(stderr, "reaper: error: %s\n", e.what());
    return 1;
  }
}
