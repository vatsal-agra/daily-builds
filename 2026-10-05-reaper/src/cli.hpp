#pragma once
#include <map>
#include <string>
#include <vector>
#include <cstdlib>
#include <stdexcept>

namespace reaper {
struct Args {
  std::vector<std::string> pos;
  std::map<std::string, std::string> opt;
  static Args parse(int argc, char** argv, int from) {
    Args a;
    for (int i = from; i < argc; i++) {
      std::string s = argv[i];
      if (s.rfind("--", 0) == 0) {
        std::string k = s.substr(2), v = "1";
        auto eq = k.find('=');
        if (eq != std::string::npos) { v = k.substr(eq + 1); k = k.substr(0, eq); }
        else if (i + 1 < argc && std::string(argv[i + 1]).rfind("--", 0) != 0) v = argv[++i];
        a.opt[k] = v;
      } else a.pos.push_back(s);
    }
    return a;
  }
  bool has(const std::string& k) const { return opt.count(k) > 0; }
  std::string str(const std::string& k, const std::string& d) const { auto it = opt.find(k); return it == opt.end() ? d : it->second; }
  unsigned long long num(const std::string& k, unsigned long long d) const {
    auto it = opt.find(k);
    if (it == opt.end()) return d;
    char* end = nullptr;
    unsigned long long v = std::strtoull(it->second.c_str(), &end, 10);
    if (!end || *end || it->second.empty() || it->second[0] == '-')
      throw std::invalid_argument("--" + k + " expects a non-negative integer, got '" + it->second + "'");
    return v;
  }
};
}  // namespace reaper
