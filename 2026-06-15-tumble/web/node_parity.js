/* Headless parity harness for the JS engine (run by tests/test_tumble.py).
 *
 *   node node_parity.js build <scene>
 *       -> prints the scene's World.toDict() JSON (pre-step) for builder parity
 *
 *   node node_parity.js step <scene> <steps>
 *       -> builds the named scene, advances <steps>, prints particle positions
 *
 *   node node_parity.js stepjson <steps>   (World JSON on stdin)
 *       -> loads a World from stdin JSON, advances <steps>, prints positions
 *
 * "positions" output is {"positions": [[x,y,px,py], ...]} with full precision.
 */
const T = require("./engine.js");

function dumpPositions(w) {
  const out = w.particles.map((p) => [p.x, p.y, p.px, p.py]);
  process.stdout.write(JSON.stringify({ positions: out }));
}

function readStdin() {
  return require("fs").readFileSync(0, "utf8");
}

const [, , cmd, a, b] = process.argv;

if (cmd === "build") {
  const w = T.buildScene(a);
  process.stdout.write(JSON.stringify(w.toDict()));
} else if (cmd === "step") {
  const w = T.buildScene(a);
  const steps = parseInt(b, 10);
  for (let i = 0; i < steps; i++) w.step();
  dumpPositions(w);
} else if (cmd === "stepjson") {
  const steps = parseInt(a, 10);
  const w = T.World.fromDict(JSON.parse(readStdin()));
  for (let i = 0; i < steps; i++) w.step();
  dumpPositions(w);
} else {
  process.stderr.write("usage: node node_parity.js build|step|stepjson ...\n");
  process.exit(2);
}
