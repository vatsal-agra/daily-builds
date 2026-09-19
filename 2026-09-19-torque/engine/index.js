// index.js -- Node-only convenience entry point that requires every engine
// module and re-exports a single flat namespace, so tests can
// `const Torque = require('../engine')` instead of wiring up each file.
// The browser doesn't use this file; demo/index.html loads the same
// per-module files directly via <script> tags in dependency order.
'use strict';

module.exports = Object.assign(
  {},
  require('./vec2.js'),
  require('./shapes.js'),
  require('./body.js'),
  require('./aabb.js'),
  require('./collision.js'),
  require('./solver.js'),
  require('./joints.js'),
  require('./world.js')
);
