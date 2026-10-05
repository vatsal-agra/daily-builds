#include "script.hpp"
#include <cctype>
#include <iostream>
#include <map>
#include <sstream>

namespace reaper {

namespace {

struct ExprParser {
  const std::string& s;
  const std::function<bool(const std::string&, long long&)>& lookup;
  size_t p = 0;
  [[noreturn]] void fail(const std::string& m) { throw std::invalid_argument(m + " in expression '" + s + "'"); }
  long long primary() {
    if (p >= s.size()) fail("unexpected end");
    char c = s[p];
    if (c == '(') {
      p++;
      long long v = sum();
      if (p >= s.size() || s[p] != ')') fail("missing ')'");
      p++;
      return v;
    }
    if (c == '-') { p++; return -primary(); }
    if (c == '$') {
      size_t b = ++p;
      while (p < s.size() && (isalnum((unsigned char)s[p]) || s[p] == '_')) p++;
      std::string name = s.substr(b, p - b);
      long long v;
      if (name.empty() || !lookup(name, v)) fail("unknown variable $" + name);
      return v;
    }
    if (isdigit((unsigned char)c)) {
      size_t b = p;
      int base = 10;
      if (c == '0' && p + 1 < s.size() && (s[p + 1] == 'x' || s[p + 1] == 'X')) { base = 16; p += 2; b = p; }
      while (p < s.size() && isxdigit((unsigned char)s[p]) && (base == 16 || isdigit((unsigned char)s[p]))) p++;
      if (p == b) fail("bad number");
      return (long long)std::stoull(s.substr(b, p - b), nullptr, base);
    }
    fail(std::string("unexpected '") + c + "'");
  }
  long long product() {
    long long v = primary();
    while (p < s.size() && (s[p] == '*' || s[p] == '/' || s[p] == '%')) {
      char op = s[p++];
      long long r = primary();
      if (op == '*') v *= r;
      else { if (r == 0) fail("division by zero"); v = op == '/' ? v / r : v % r; }
    }
    return v;
  }
  long long sum() {
    long long v = product();
    while (p < s.size() && (s[p] == '+' || s[p] == '-')) {
      char op = s[p++];
      long long r = product();
      v = op == '+' ? v + r : v - r;
    }
    return v;
  }
};

struct Stmt {
  std::string cmd;
  std::vector<std::string> args;
  int line = 0;
  std::vector<Stmt> body;
};

[[noreturn]] void err(int line, const std::string& m) { throw std::runtime_error(std::to_string(line) + ": " + m); }

std::vector<std::string> split(const std::string& l) {
  std::vector<std::string> out;
  std::istringstream is(l);
  std::string t;
  while (is >> t) out.push_back(t);
  return out;
}

// Parse lines [i, end) into statements; `closing` = expecting a '}' (nested block)
std::vector<Stmt> parseBlock(const std::vector<std::string>& lines, size_t& i, bool closing, int openLine) {
  std::vector<Stmt> out;
  while (i < lines.size()) {
    std::string l = lines[i];
    int lineNo = (int)i + 1;
    i++;
    size_t hash = l.find('#');
    if (hash != std::string::npos) l = l.substr(0, hash);
    auto tok = split(l);
    if (tok.empty()) continue;
    if (tok[0] == "}") {
      if (!closing) err(lineNo, "unmatched '}'");
      if (tok.size() > 1) err(lineNo, "unexpected text after '}'");
      return out;
    }
    Stmt s;
    s.cmd = tok[0];
    s.line = lineNo;
    s.args.assign(tok.begin() + 1, tok.end());
    if (s.cmd == "repeat") {
      if (s.args.empty() || s.args.back() != "{") err(lineNo, "repeat needs a trailing '{':  repeat N [as i] {");
      s.args.pop_back();
      if (s.args.size() != 1 && !(s.args.size() == 3 && s.args[1] == "as")) err(lineNo, "usage: repeat N [as var] {");
      s.body = parseBlock(lines, i, true, lineNo);
    }
    out.push_back(std::move(s));
  }
  if (closing) err(openLine, "repeat block is never closed");
  return out;
}

struct Interp {
  Heap& h;
  std::ostream& out;
  std::map<std::string, long long> vars;
  size_t count = 0, depth = 0;

  long long ev(const Stmt& s, size_t k) {
    if (k >= s.args.size()) err(s.line, "'" + s.cmd + "' is missing an argument");
    auto lookup = [&](const std::string& n, long long& v) { auto it = vars.find(n); if (it == vars.end()) return false; v = it->second; return true; };
    try {
      ExprParser ep{s.args[k], lookup};
      long long v = ep.sum();
      if (ep.p != s.args[k].size()) throw std::invalid_argument("trailing characters in expression '" + s.args[k] + "'");
      return v;
    } catch (const std::invalid_argument& e) { err(s.line, e.what()); }
  }
  size_t slot(const Stmt& s, size_t k) {
    long long v = ev(s, k);
    if (v < 0 || v >= (long long)NROOTS) err(s.line, "slot " + std::to_string(v) + " out of range 0.." + std::to_string(NROOTS - 1));
    return (size_t)v;
  }
  uint32_t idx(const Stmt& s, size_t k) {
    long long v = ev(s, k);
    if (v < 0 || v > 0x7FFFFFFF) err(s.line, "index " + std::to_string(v) + " out of range");
    return (uint32_t)v;
  }
  void arity(const Stmt& s, size_t n) {
    if (s.args.size() != n) err(s.line, "'" + s.cmd + "' takes " + std::to_string(n) + " argument(s), got " + std::to_string(s.args.size()));
  }

  void run(const std::vector<Stmt>& block) {
    for (auto& s : block) {
      count++;
      try { exec(s); }
      catch (const OutOfMemory& e) { err(s.line, std::string("out of memory: ") + e.what()); }
      catch (const std::out_of_range& e) { err(s.line, std::string("out of range: ") + e.what()); }
      catch (const std::invalid_argument& e) { err(s.line, e.what()); }
    }
  }

  void exec(const Stmt& s) {
    const std::string& c = s.cmd;
    if (c == "alloc") {                                   // alloc <slot> <nptrs> <ndata> [tag]
      if (s.args.size() < 3 || s.args.size() > 4) err(s.line, "usage: alloc <slot> <nptrs> <ndata> [tag]");
      long long np = ev(s, 1), nd = ev(s, 2), tag = s.args.size() == 4 ? ev(s, 3) : 1;
      if (np < 0 || nd < 0 || tag < 0) err(s.line, "negative size");
      h.newObj(slot(s, 0), (uint32_t)np, (uint32_t)nd, (uint32_t)tag);
    } else if (c == "store") { arity(s, 3); h.store(slot(s, 0), idx(s, 1), slot(s, 2)); }
    else if (c == "nil") { arity(s, 2); h.storeNil(slot(s, 0), idx(s, 1)); }
    else if (c == "load") { arity(s, 3); h.load(slot(s, 0), slot(s, 1), idx(s, 2)); }
    else if (c == "set") { arity(s, 3); h.setData(slot(s, 0), idx(s, 1), (Word)ev(s, 2)); }
    else if (c == "move") { arity(s, 2); h.move(slot(s, 0), slot(s, 1)); }
    else if (c == "clear") { arity(s, 1); h.clear(slot(s, 0)); }
    else if (c == "let") {
      if (s.args.size() != 2) err(s.line, "usage: let <name> <expr>");
      vars[s.args[0]] = ev(s, 1);
    } else if (c == "gc") {
      if (s.args.size() > 1) err(s.line, "usage: gc [minor|full]");
      bool full = s.args.empty() || s.args[0] == "full";
      if (!s.args.empty() && s.args[0] != "full" && s.args[0] != "minor") err(s.line, "gc takes 'minor' or 'full'");
      h.gc(full);
    } else if (c == "repeat") {
      long long n = ev(s, 0);
      if (n < 0) err(s.line, "negative repeat count");
      if (++depth > 8) err(s.line, "repeat blocks nested too deeply");
      std::string var = s.args.size() == 3 ? s.args[2] : "i";
      for (long long k = 0; k < n; k++) { vars[var] = k; run(s.body); }
      vars.erase(var);
      depth--;
    } else if (c == "expect") {
      expect(s);
    } else if (c == "print") {
      print(s);
    } else err(s.line, "unknown command '" + c + "'");
  }

  void expect(const Stmt& s) {
    // expect null <slot> | expect set <slot> | expect data <slot> <j> <value> | expect live <objects> | expect words <live words>
    // expect used <= <words> | expect verify
    if (s.args.empty()) err(s.line, "expect what? (null/set/data/live/words/used/verify)");
    const std::string& w = s.args[0];
    auto fail = [&](const std::string& m) { err(s.line, "expectation failed: " + m); };
    Stmt a = s;
    a.args.erase(a.args.begin());
    if (w == "null") { arity(a, 1); if (!h.isNull(slot(a, 0))) fail("slot " + a.args[0] + " is not null"); }
    else if (w == "set") { arity(a, 1); if (h.isNull(slot(a, 0))) fail("slot " + a.args[0] + " is null"); }
    else if (w == "data") {
      arity(a, 3);
      size_t sl = slot(a, 0);
      if (h.isNull(sl)) fail("slot " + a.args[0] + " is null");
      Word got = h.getData(sl, idx(a, 1)), want = (Word)ev(a, 2);
      if (got != want) fail("slot " + a.args[0] + " data[" + a.args[1] + "] is " + std::to_string(got) + ", wanted " + std::to_string(want));
    } else if (w == "live" || w == "words") {
      arity(a, 1);
      size_t objs = 0, words = 0;
      h.graphHash(&objs, &words);
      long long want = ev(a, 0);
      long long got = w == "live" ? (long long)objs : (long long)words;
      if (got != want) fail(std::to_string(got) + " live " + (w == "live" ? "objects" : "words") + ", wanted " + std::to_string(want));
    } else if (w == "used") {
      if (a.args.size() != 2 || a.args[0] != "<=") err(s.line, "usage: expect used <= <words>");
      Stmt b = a; b.args.erase(b.args.begin());
      long long cap = ev(b, 0);
      if ((long long)h.usedWords() > cap) fail(std::to_string(h.usedWords()) + " words in use, wanted <= " + std::to_string(cap));
    } else if (w == "verify") {
      std::string v = h.verify();
      if (!v.empty()) fail("heap verifier: " + v);
    } else err(s.line, "unknown expectation '" + w + "'");
  }

  void print(const Stmt& s) {
    if (s.args.empty()) err(s.line, "print what? (stats/hash/live/slot <n>/<text>)");
    const std::string& w = s.args[0];
    if (w == "stats") {
      const Stats& st = h.stats;
      out << h.name() << ": " << st.allocs << " allocs, " << st.minor_gcs << " minor + " << st.major_gcs << " major GCs, "
          << st.moved_objects << " objects moved, " << h.usedWords() << "/" << h.capacityWords() << " words in use\n";
    } else if (w == "hash") {
      char b[32];
      snprintf(b, sizeof b, "%016llx", (unsigned long long)h.graphHash());
      out << "graph hash " << b << "\n";
    } else if (w == "live") {
      size_t o = 0, wd = 0;
      h.graphHash(&o, &wd);
      out << "live: " << o << " objects, " << wd << " words\n";
    } else if (w == "slot") {
      Stmt a = s; a.args.erase(a.args.begin());
      size_t sl = slot(a, 0);
      if (h.isNull(sl)) { out << "slot " << sl << " = null\n"; return; }
      out << "slot " << sl << " = object(ptrs=" << h.nptrsOf(sl) << ", data=" << h.ndataOf(sl) << ")";
      for (uint32_t j = 0; j < h.ndataOf(sl) && j < 8; j++) out << " d" << j << "=" << h.getData(sl, j);
      out << "\n";
    } else {
      for (size_t k = 0; k < s.args.size(); k++) {          // words starting with '$' are evaluated as expressions
        out << (k ? " " : "");
        if (s.args[k][0] == '$') out << ev(s, k); else out << s.args[k];
      }
      out << "\n";
    }
  }
};

}  // namespace

long long evalExpr(const std::string& expr, const std::function<bool(const std::string&, long long&)>& lookup) {
  ExprParser ep{expr, lookup};
  long long v = ep.sum();
  if (ep.p != expr.size()) throw std::invalid_argument("trailing characters in expression '" + expr + "'");
  return v;
}

ScriptResult runScript(Heap& h, const std::string& source, const std::string& filename, std::ostream& out) {
  ScriptResult res;
  std::vector<std::string> lines;
  std::istringstream is(source);
  for (std::string l; std::getline(is, l);) lines.push_back(l);
  try {
    size_t i = 0;
    auto prog = parseBlock(lines, i, false, 0);
    Interp in{h, out, {}, 0, 0};
    in.run(prog);
    res.statements = in.count;
  } catch (const std::runtime_error& e) {
    res.ok = false;
    res.error = filename + ":" + e.what();
  }
  return res;
}

}  // namespace reaper
