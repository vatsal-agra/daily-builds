'use strict';

const { test, assertClose } = require('./test-utils.js');
const T = require('../engine');

function run() {
  test('circle mass/inertia match analytical formulas', () => {
    const r = 1.3;
    const density = 2.1;
    const shape = new T.Circle(r);
    const md = shape.computeMass(density);
    assertClose(md.mass, density * Math.PI * r * r, 1e-9, 'mass');
    assertClose(md.inertia, 0.5 * md.mass * r * r, 1e-9, 'inertia about center');
  });

  test('box mass/inertia match the standard rectangle formula', () => {
    const w = 2, h = 0.5, density = 3;
    const shape = T.box(w, h);
    const md = shape.computeMass(density);
    assertClose(md.mass, density * w * h, 1e-9, 'mass');
    const expectedI = (md.mass / 12) * (w * w + h * h);
    assertClose(md.inertia, expectedI, 1e-9, 'inertia about center');
  });

  test('a general Polygon built as a square matches the box formula', () => {
    const w = 1.4;
    const half = w / 2;
    const poly = new T.Polygon([
      new T.Vec2(-half, -half),
      new T.Vec2(half, -half),
      new T.Vec2(half, half),
      new T.Vec2(-half, half),
    ]);
    const density = 1.7;
    const md = poly.computeMass(density);
    assertClose(md.mass, density * w * w, 1e-9, 'mass');
    const expectedI = (md.mass / 12) * (w * w + w * w);
    assertClose(md.inertia, expectedI, 1e-6, 'inertia');
  });

  test('Polygon recenters an off-origin vertex list onto its own centroid', () => {
    // a 2x2 square whose input vertices are NOT centered on the origin
    const poly = new T.Polygon([
      new T.Vec2(10, 10),
      new T.Vec2(12, 10),
      new T.Vec2(12, 12),
      new T.Vec2(10, 12),
    ]);
    const md = poly.computeMass(1);
    assertClose(md.centroid.x, 0, 1e-9, 'recentered centroid x');
    assertClose(md.centroid.y, 0, 1e-9, 'recentered centroid y');
    assertClose(md.mass, 4, 1e-9, 'area preserved after recentering');
  });

  test('a clockwise-wound polygon is normalized to CCW', () => {
    const cw = new T.Polygon([
      new T.Vec2(-1, -1),
      new T.Vec2(-1, 1),
      new T.Vec2(1, 1),
      new T.Vec2(1, -1),
    ]);
    // outward normal of the first CCW edge should point away from center
    const n0 = cw.normals[0];
    const mid0 = T.Vec2.lerp(cw.vertices[0], cw.vertices[1], 0.5);
    assertClose(T.Vec2.dot(n0, mid0), T.Vec2.len(mid0), 1e-6, 'normal points outward');
  });

  test('degenerate shapes are rejected at construction', () => {
    let threw = false;
    try {
      new T.Polygon([new T.Vec2(0, 0), new T.Vec2(1, 0), new T.Vec2(2, 0)]); // collinear, zero area
    } catch (e) {
      threw = true;
    }
    if (!threw) throw new Error('expected a zero-area polygon to throw');
  });
}

module.exports = { run };
