'use strict';

const { reset, summarize } = require('./test-utils.js');
const suites = [
  ['shapes', require('./shapes.test.js')],
  ['dynamics', require('./dynamics.test.js')],
  ['solver', require('./solver.test.js')],
  ['joints', require('./joints.test.js')],
];

let allPassed = true;
for (const [name, suite] of suites) {
  reset();
  suite.run();
  const ok = summarize(name);
  allPassed = allPassed && ok;
}

console.log(allPassed ? '\nALL SUITES PASSED' : '\nSOME SUITES FAILED');
process.exit(allPassed ? 0 : 1);
