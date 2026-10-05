#pragma once
#include "heap.hpp"
#include <iosfwd>
#include <string>

namespace reaper {

struct ScriptResult {
  bool ok = true;
  std::string error;     // "file:line: message" on failure
  size_t statements = 0;
};

// Run a mutator script (see README "Script language") against `h`. Output of `print` goes to `out`.
ScriptResult runScript(Heap& h, const std::string& source, const std::string& filename, std::ostream& out);

// Evaluate an integer expression ("$i*2+1", "0x10", "7%3"); throws std::invalid_argument.
long long evalExpr(const std::string& expr, const std::function<bool(const std::string&, long long&)>& lookup);

}  // namespace reaper
