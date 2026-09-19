// shapes.js -- Circle and Polygon shape definitions with analytical mass
// and moment-of-inertia computation. Internal convention: math coordinates
// (y-up), CCW winding for polygons. The demo's canvas renderer flips y when
// drawing; the engine itself never assumes screen coordinates.
(function (root) {
  'use strict';

  const dep = typeof module !== 'undefined' && module.exports
    ? require('./vec2.js')
    : { Vec2: root.Torque.Vec2 };
  const Vec2 = dep.Vec2;

  function Circle(radius) {
    if (!(radius > 0)) throw new Error('Circle radius must be > 0');
    this.type = 'circle';
    this.radius = radius;
  }

  Circle.prototype.computeMass = function (density) {
    const mass = density * Math.PI * this.radius * this.radius;
    // solid disc about its own center: I = 1/2 m r^2
    const inertia = 0.5 * mass * this.radius * this.radius;
    return { mass: mass, inertia: inertia, centroid: new Vec2(0, 0) };
  };

  Circle.prototype.computeAABB = function (position) {
    return {
      minX: position.x - this.radius,
      minY: position.y - this.radius,
      maxX: position.x + this.radius,
      maxY: position.y + this.radius,
    };
  };

  // Polygon: vertices given in any winding/reference frame; the constructor
  // recenters them so the shape's local origin is the centroid (= body's
  // center of mass) and normalizes winding to CCW, which every downstream
  // algorithm (SAT normals, inertia sign) assumes.
  function Polygon(inputVertices) {
    if (!inputVertices || inputVertices.length < 3) {
      throw new Error('Polygon needs at least 3 vertices');
    }
    this.type = 'polygon';

    const signedArea = shoelaceSigned(inputVertices);
    if (Math.abs(signedArea) < 1e-9) {
      throw new Error('degenerate polygon (zero area)');
    }
    const verts = signedArea < 0 ? inputVertices.slice().reverse() : inputVertices.slice();

    const massData = polygonMassData(verts, 1); // density 1 -> recenters, gives centroid
    // store local vertices already recentered on centroid
    this.vertices = massData.localVertices.map((v) => new Vec2(v.x, v.y));
    this.normals = computeNormals(this.vertices);
    this._unitInertia = massData.inertia; // inertia at density=1, about centroid
    this._unitArea = Math.abs(shoelaceSigned(this.vertices));
  }

  Polygon.prototype.computeMass = function (density) {
    const mass = density * this._unitArea;
    const inertia = density * this._unitInertia;
    return { mass: mass, inertia: inertia, centroid: new Vec2(0, 0) };
  };

  Polygon.prototype.computeAABB = function (position, angle) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (let i = 0; i < this.vertices.length; i++) {
      const w = Vec2.add(position, Vec2.rotate(this.vertices[i], angle));
      if (w.x < minX) minX = w.x;
      if (w.y < minY) minY = w.y;
      if (w.x > maxX) maxX = w.x;
      if (w.y > maxY) maxY = w.y;
    }
    return { minX: minX, minY: minY, maxX: maxX, maxY: maxY };
  };

  Polygon.prototype.worldVertices = function (position, angle) {
    const out = new Array(this.vertices.length);
    for (let i = 0; i < this.vertices.length; i++) {
      out[i] = Vec2.add(position, Vec2.rotate(this.vertices[i], angle));
    }
    return out;
  };

  Polygon.prototype.worldNormals = function (angle) {
    const out = new Array(this.normals.length);
    for (let i = 0; i < this.normals.length; i++) {
      out[i] = Vec2.rotate(this.normals[i], angle);
    }
    return out;
  };

  function box(width, height) {
    const hx = width / 2;
    const hy = height / 2;
    return new Polygon([
      new Vec2(-hx, -hy),
      new Vec2(hx, -hy),
      new Vec2(hx, hy),
      new Vec2(-hx, hy),
    ]);
  }

  function regularPolygon(numSides, radius) {
    if (numSides < 3) throw new Error('regularPolygon needs >= 3 sides');
    const verts = [];
    for (let i = 0; i < numSides; i++) {
      const angle = (i / numSides) * Math.PI * 2;
      verts.push(new Vec2(radius * Math.cos(angle), radius * Math.sin(angle)));
    }
    return new Polygon(verts);
  }

  // --- internal helpers ---

  function shoelaceSigned(vertices) {
    let area = 0;
    for (let i = 0; i < vertices.length; i++) {
      const a = vertices[i];
      const b = vertices[(i + 1) % vertices.length];
      area += a.x * b.y - b.x * a.y;
    }
    return 0.5 * area;
  }

  // Standard triangle-fan-from-reference-point algorithm (as used by
  // Box2D's b2PolygonShape::ComputeMass) for polygon centroid + inertia.
  // Works for any simple polygon, convex or not, regardless of reference
  // point location, since it sums signed triangle contributions.
  function polygonMassData(vertices, density) {
    const s = vertices[0];
    const inv3 = 1 / 3;
    let area = 0;
    let cx = 0, cy = 0;
    for (let i = 0; i < vertices.length; i++) {
      const e1x = vertices[i].x - s.x;
      const e1y = vertices[i].y - s.y;
      const j = (i + 1) % vertices.length;
      const e2x = vertices[j].x - s.x;
      const e2y = vertices[j].y - s.y;
      const cross = e1x * e2y - e1y * e2x;
      const triArea = 0.5 * cross;
      area += triArea;
      cx += triArea * inv3 * (e1x + e2x);
      cy += triArea * inv3 * (e1y + e2y);
    }
    if (Math.abs(area) < 1e-12) throw new Error('degenerate polygon (zero area)');
    cx /= area;
    cy /= area;
    const centroid = new Vec2(cx + s.x, cy + s.y);

    const local = vertices.map((v) => new Vec2(v.x - centroid.x, v.y - centroid.y));
    let I = 0;
    for (let i = 0; i < local.length; i++) {
      const e1 = local[i];
      const j = (i + 1) % local.length;
      const e2 = local[j];
      const cross = e1.x * e2.y - e1.y * e2.x;
      const intx2 = e1.x * e1.x + e2.x * e1.x + e2.x * e2.x;
      const inty2 = e1.y * e1.y + e2.y * e1.y + e2.y * e2.y;
      I += (0.25 * inv3 * cross) * (intx2 + inty2);
    }
    return {
      mass: density * Math.abs(area),
      centroid: centroid,
      inertia: density * Math.abs(I),
      localVertices: local,
    };
  }

  function computeNormals(localVertices) {
    const n = localVertices.length;
    const normals = new Array(n);
    for (let i = 0; i < n; i++) {
      const a = localVertices[i];
      const b = localVertices[(i + 1) % n];
      const edge = Vec2.sub(b, a);
      // outward normal for CCW winding: rotate edge -90deg
      normals[i] = Vec2.normalize(new Vec2(edge.y, -edge.x));
    }
    return normals;
  }

  const api = { Circle: Circle, Polygon: Polygon, box: box, regularPolygon: regularPolygon };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.Circle = Circle;
    root.Torque.Polygon = Polygon;
    root.Torque.box = box;
    root.Torque.regularPolygon = regularPolygon;
  }
})(typeof window !== 'undefined' ? window : globalThis);
