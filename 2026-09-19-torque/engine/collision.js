// collision.js -- narrow-phase collision tests. Three pair types:
// circle-circle, polygon-circle, polygon-polygon (SAT + reference/incident
// face clipping for a proper up-to-2-point contact manifold, not just a
// single average point -- that 2-point manifold is what lets a box rest
// flat on the ground without rocking).
//
// Convention used everywhere below: a returned manifold's `normal` always
// points from bodyA toward bodyB, and each contact point's `penetration`
// is the overlap depth along that normal (positive = overlapping).
(function (root) {
  'use strict';

  const dep = typeof module !== 'undefined' && module.exports
    ? require('./vec2.js')
    : { Vec2: root.Torque.Vec2 };
  const Vec2 = dep.Vec2;

  const LINEAR_SLOP = 0.005; // tiny tolerance so resting contacts aren't dropped by fp noise

  function circleCircle(bodyA, bodyB) {
    const ra = bodyA.shape.radius;
    const rb = bodyB.shape.radius;
    const d = Vec2.sub(bodyB.position, bodyA.position);
    const dist = Vec2.len(d);
    const radiusSum = ra + rb;
    if (dist >= radiusSum) return null;

    const normal = dist > 1e-9 ? Vec2.scale(d, 1 / dist) : new Vec2(1, 0);
    const penetration = radiusSum - dist;
    const pA = Vec2.add(bodyA.position, Vec2.scale(normal, ra));
    const pB = Vec2.sub(bodyB.position, Vec2.scale(normal, rb));
    const point = Vec2.lerp(pA, pB, 0.5);

    return { normal: normal, points: [{ point: point, penetration: penetration }] };
  }

  // Returns a manifold with normal pointing from the polygon body to the
  // circle body (caller flips it if the polygon isn't bodyA).
  function polygonCircle(polyBody, circleBody) {
    const poly = polyBody.shape;
    const radius = circleBody.shape.radius;
    const angle = polyBody.angle;
    const centerLocal = Vec2.rotate(Vec2.sub(circleBody.position, polyBody.position), -angle);

    let separation = -Infinity;
    let faceIndex = 0;
    for (let i = 0; i < poly.vertices.length; i++) {
      const s = Vec2.dot(poly.normals[i], Vec2.sub(centerLocal, poly.vertices[i]));
      if (s > radius) return null; // definitely separated on this axis
      if (s > separation) {
        separation = s;
        faceIndex = i;
      }
    }

    const v1 = poly.vertices[faceIndex];
    const v2 = poly.vertices[(faceIndex + 1) % poly.vertices.length];

    let normalLocal;
    let penetration;

    if (separation < 1e-9) {
      // circle center is inside the polygon
      normalLocal = poly.normals[faceIndex];
      penetration = radius - separation;
    } else {
      const u1 = Vec2.dot(Vec2.sub(centerLocal, v1), Vec2.sub(v2, v1));
      const u2 = Vec2.dot(Vec2.sub(centerLocal, v2), Vec2.sub(v1, v2));

      if (u1 <= 0) {
        const d = Vec2.distance(centerLocal, v1);
        if (d > radius) return null;
        normalLocal = Vec2.normalize(Vec2.sub(centerLocal, v1));
        penetration = radius - d;
      } else if (u2 <= 0) {
        const d = Vec2.distance(centerLocal, v2);
        if (d > radius) return null;
        normalLocal = Vec2.normalize(Vec2.sub(centerLocal, v2));
        penetration = radius - d;
      } else {
        if (separation > radius) return null;
        normalLocal = poly.normals[faceIndex];
        penetration = radius - separation;
      }
    }

    const normalWorld = Vec2.rotate(normalLocal, angle);
    const contactPoint = Vec2.sub(circleBody.position, Vec2.scale(normalWorld, radius));

    return { normal: normalWorld, points: [{ point: contactPoint, penetration: penetration }] };
  }

  // Max separation of B's vertices behind A's faces: for each face normal
  // of A, the deepest (most negative) signed distance among B's vertices,
  // then the max of those over all of A's faces. A positive result is a
  // separating axis (early-outable by the caller).
  function findMaxSeparation(bodyA, bodyB) {
    const polyA = bodyA.shape;
    const normalsA = polyA.worldNormals(bodyA.angle);
    const vertsA = polyA.worldVertices(bodyA.position, bodyA.angle);
    const vertsB = bodyB.shape.worldVertices(bodyB.position, bodyB.angle);

    let bestSeparation = -Infinity;
    let bestIndex = 0;
    for (let i = 0; i < normalsA.length; i++) {
      const n = normalsA[i];
      const v1 = vertsA[i];
      let minDot = Infinity;
      for (let j = 0; j < vertsB.length; j++) {
        const d = Vec2.dot(n, vertsB[j]);
        if (d < minDot) minDot = d;
      }
      const separation = minDot - Vec2.dot(n, v1);
      if (separation > bestSeparation) {
        bestSeparation = separation;
        bestIndex = i;
      }
    }
    return { separation: bestSeparation, faceIndex: bestIndex };
  }

  function findIncidentEdge(refNormalWorld, incBody) {
    const normals = incBody.shape.worldNormals(incBody.angle);
    let minDot = Infinity;
    let index = 0;
    for (let i = 0; i < normals.length; i++) {
      const d = Vec2.dot(refNormalWorld, normals[i]);
      if (d < minDot) {
        minDot = d;
        index = i;
      }
    }
    return index;
  }

  // Sutherland-Hodgman clip of a 2-point segment against the half-plane
  // dot(normal, p) <= offset, replacing any point outside it with the
  // line/plane intersection.
  function clipSegment(points, normal, offset) {
    const out = [];
    const d0 = Vec2.dot(normal, points[0]) - offset;
    const d1 = Vec2.dot(normal, points[1]) - offset;
    if (d0 <= 0) out.push(points[0]);
    if (d1 <= 0) out.push(points[1]);
    if (d0 * d1 < 0) {
      const t = d0 / (d0 - d1);
      out.push(Vec2.lerp(points[0], points[1], t));
    }
    return out;
  }

  function polygonPolygon(bodyA, bodyB) {
    const sepA = findMaxSeparation(bodyA, bodyB);
    if (sepA.separation > 0) return null;
    const sepB = findMaxSeparation(bodyB, bodyA);
    if (sepB.separation > 0) return null;

    let refBody, incBody, refIndex, flip;
    const bias = 0.001; // tie-break toward A to damp face flip-flopping
    if (sepB.separation > sepA.separation + bias) {
      refBody = bodyB;
      incBody = bodyA;
      refIndex = sepB.faceIndex;
      flip = true;
    } else {
      refBody = bodyA;
      incBody = bodyB;
      refIndex = sepA.faceIndex;
      flip = false;
    }

    const refPoly = refBody.shape;
    const refVerts = refPoly.worldVertices(refBody.position, refBody.angle);
    const refNormals = refPoly.worldNormals(refBody.angle);
    const v1 = refVerts[refIndex];
    const v2 = refVerts[(refIndex + 1) % refVerts.length];
    const refNormal = refNormals[refIndex];

    const incIndex = findIncidentEdge(refNormal, incBody);
    const incVerts = incBody.shape.worldVertices(incBody.position, incBody.angle);
    let incidentEdge = [incVerts[incIndex], incVerts[(incIndex + 1) % incVerts.length]];

    const tangent = Vec2.normalize(Vec2.sub(v2, v1));
    const negSide = -Vec2.dot(tangent, v1);
    const posSide = Vec2.dot(tangent, v2);

    let clipped = clipSegment(incidentEdge, Vec2.neg(tangent), negSide);
    if (clipped.length < 2) return null;
    clipped = clipSegment(clipped, tangent, posSide);
    if (clipped.length < 2) return null;

    const points = [];
    for (let i = 0; i < clipped.length; i++) {
      const separation = Vec2.dot(refNormal, Vec2.sub(clipped[i], v1));
      if (separation <= LINEAR_SLOP) {
        points.push({ point: clipped[i], penetration: -separation });
      }
    }
    if (points.length === 0) return null;

    const normal = flip ? Vec2.neg(refNormal) : refNormal;
    return { normal: normal, points: points };
  }

  // Dispatcher: always returns a manifold with normal pointing A -> B, or
  // null if the pair isn't touching.
  function collide(bodyA, bodyB) {
    const ta = bodyA.shape.type;
    const tb = bodyB.shape.type;
    if (ta === 'circle' && tb === 'circle') {
      return circleCircle(bodyA, bodyB);
    }
    if (ta === 'polygon' && tb === 'polygon') {
      return polygonPolygon(bodyA, bodyB);
    }
    if (ta === 'polygon' && tb === 'circle') {
      return polygonCircle(bodyA, bodyB);
    }
    if (ta === 'circle' && tb === 'polygon') {
      const m = polygonCircle(bodyB, bodyA);
      if (!m) return null;
      return { normal: Vec2.neg(m.normal), points: m.points };
    }
    throw new Error('unknown shape pair: ' + ta + '/' + tb);
  }

  const api = { collide: collide };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.collide = collide;
  }
})(typeof window !== 'undefined' ? window : globalThis);
