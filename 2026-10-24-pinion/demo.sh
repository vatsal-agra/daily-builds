#!/usr/bin/env bash
# Guided tour of Pinion on the bundled example project. Works on a temp copy; leaves the repo clean.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PIN="$HERE/bin/pinion"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$HERE"/examples/webapp/*.json "$WORK/"
cd "$WORK"

step() { printf '\n\033[1m── %s\033[0m\n$ pinion %s\n' "$1" "$2"; }

step "1. Constraint language & exact version-set algebra" "range '^1.2.3 || >=3.0.0 <3.5.0' 1.2.2 1.9.0 3.2.0"
"$PIN" range '^1.2.3 || >=3.0.0 <3.5.0' 1.2.2 1.9.0 3.2.0

step "2. Resolve a real-looking project (shopfront)" "resolve --stats"
"$PIN" resolve --stats

step "3. Dependency tree" "tree"
"$PIN" tree

step "4. Why is tlslib 2.1.1 here, and why not 3.x?" "why tlslib"
"$PIN" why tlslib

step "5. An unsolvable project — explained, not just rejected" "resolve conflict.json"
"$PIN" resolve conflict.json && exit 1 || echo "(exit code $?)"

step "6. A typo'd package name" "resolve typo.json"
echo '{"name":"shopfront","dependencies":{"webkit":"^2","logsmth":"^1"}}' > typo.json
"$PIN" resolve typo.json && exit 1 || echo "(exit code $?)"

step "7. Prerelease opt-in via the range itself" "resolve pre.json"
"$PIN" resolve pre.json

step "8. Lock, verify, tamper, detect" "lock && verify"
"$PIN" lock
"$PIN" verify
python3 - <<'PY'
import json
r = json.load(open("registry.json"))
r["packages"]["tlslib"]["2.1.1"]["dependencies"]["evil-pkg"] = "*"
json.dump(r, open("registry.json", "w"))
PY
echo "(registry entry for tlslib 2.1.1 was just edited behind the lockfile's back)"
"$PIN" verify && exit 1 || echo "(exit code $?)"

step "9. Conservative update — new releases appear, only the named package moves" "update logsmith"
python3 - <<'PY'
import json
r = json.load(open("registry.json"))
r["packages"]["tlslib"]["2.1.1"]["dependencies"].pop("evil-pkg")
r["packages"]["logsmith"]["1.5.0"] = {"dependencies": {}}
r["packages"]["jsonkit"]["1.3.0"] = {"dependencies": {"unicodedata": "^1.0"}}
json.dump(r, open("registry.json", "w"))
PY
"$PIN" update logsmith
echo "-- and now everything:"
"$PIN" update

step "10. HTML dependency graph" "graph -o graph.html"
"$PIN" graph -o graph.html
test -s graph.html && echo "graph.html: $(wc -c < graph.html) bytes, self-contained"

step "11. Differential fuzzing against a brute-force oracle" "fuzz --count 150"
"$PIN" fuzz --count 150

printf '\n\033[1mdemo complete\033[0m\n'
