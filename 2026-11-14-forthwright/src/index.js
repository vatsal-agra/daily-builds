/* Node entry: a ready-to-use VM with analyzer + optimizer attached. */
const Forth = require('./forth.js');
const Analyzer = require('./analyze.js');
let Optimizer = null;
try { Optimizer = require('./optimize.js'); } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
function create(opts) { return new Forth(opts).use({ analyzer: Analyzer, optimizer: Optimizer }); }
module.exports = { create, Forth, Analyzer, Optimizer };
