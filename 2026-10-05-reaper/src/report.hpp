#pragma once
#include "cli.hpp"

namespace reaper {
int cmdList();
int cmdRun(const Args& a);
int cmdBench(const Args& a);
int cmdFuzz(const Args& a);
int cmdScript(const Args& a);
int cmdViz(const Args& a);
}
