"""Reference generator for differential tests: reads JSON cases on stdin
[{text, version, ecc, mask, eci}], prints JSON list of matrices as '0'/'1' strings.
Uses the independent `segno` library; not part of Quietzone itself."""
import json, sys, segno
out = []
for c in json.load(sys.stdin):
    q = segno.make(c["text"], error=c["ecc"].lower(), version=c["version"], mask=c["mask"],
                   boost_error=False, encoding="utf-8", micro=False, eci=c.get("eci", False))
    out.append(["".join("1" if v else "0" for v in row) for row in q.matrix])
json.dump(out, sys.stdout)
