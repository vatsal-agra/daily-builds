// solver.js -- sequential-impulse contact resolution: warm starting,
// restitution, Coulomb friction, and Baumgarte position-error bias, all in
// the classic Erin Catto "sequential impulses" formulation (the same
// algorithm Box2D and Chipmunk are built on).
(function (root) {
  'use strict';

  const dep = typeof module !== 'undefined' && module.exports
    ? require('./vec2.js')
    : { Vec2: root.Torque.Vec2 };
  const Vec2 = dep.Vec2;

  const BAUMGARTE = 0.2; // fraction of penetration error corrected per step
  const SLOP = 0.005; // allowed penetration before correction kicks in
  const RESTITUTION_THRESHOLD = 0.5; // relative velocity below this never bounces (kills jitter)
  const MAX_BAUMGARTE_BIAS = 4.0; // clamp so deep/tunneled overlaps don't explode

  function mixFriction(a, b) {
    return Math.sqrt(a.friction * b.friction);
  }

  function mixRestitution(a, b) {
    return Math.max(a.restitution, b.restitution);
  }

  // Builds solver-ready contact constraints from raw narrow-phase
  // manifolds, pulling in warm-start impulses matched from last frame's
  // cache (see world.js). Must run once per step, before any iterations.
  function prepareContacts(manifoldEntries, dt) {
    const constraints = [];
    for (let m = 0; m < manifoldEntries.length; m++) {
      const entry = manifoldEntries[m];
      const bodyA = entry.bodyA;
      const bodyB = entry.bodyB;
      const normal = entry.manifold.normal;
      const tangent = new Vec2(normal.y, -normal.x);

      const cPoints = [];
      for (let i = 0; i < entry.manifold.points.length; i++) {
        const mp = entry.manifold.points[i];
        const rA = Vec2.sub(mp.point, bodyA.position);
        const rB = Vec2.sub(mp.point, bodyB.position);

        const rn1 = Vec2.cross(rA, normal);
        const rn2 = Vec2.cross(rB, normal);
        const kNormal = bodyA.invMass + bodyB.invMass +
          bodyA.invInertia * rn1 * rn1 + bodyB.invInertia * rn2 * rn2;

        const rt1 = Vec2.cross(rA, tangent);
        const rt2 = Vec2.cross(rB, tangent);
        const kTangent = bodyA.invMass + bodyB.invMass +
          bodyA.invInertia * rt1 * rt1 + bodyB.invInertia * rt2 * rt2;

        const relVel = Vec2.dot(normal, Vec2.sub(bodyB.velocityAtPoint(mp.point), bodyA.velocityAtPoint(mp.point)));
        let restitutionBias = 0;
        if (relVel < -RESTITUTION_THRESHOLD) {
          restitutionBias = -mixRestitution(bodyA, bodyB) * relVel;
        }
        const baumgarteBias = Math.min(
          MAX_BAUMGARTE_BIAS,
          (BAUMGARTE / dt) * Math.max(mp.penetration - SLOP, 0)
        );

        cPoints.push({
          point: mp.point,
          rA: rA,
          rB: rB,
          normalMass: kNormal > 0 ? 1 / kNormal : 0,
          tangentMass: kTangent > 0 ? 1 / kTangent : 0,
          bias: Math.max(restitutionBias, baumgarteBias),
          normalImpulse: mp.warmNormalImpulse || 0,
          tangentImpulse: mp.warmTangentImpulse || 0,
        });
      }

      constraints.push({
        bodyA: bodyA,
        bodyB: bodyB,
        normal: normal,
        tangent: tangent,
        friction: mixFriction(bodyA, bodyB),
        points: cPoints,
      });
    }
    return constraints;
  }

  function warmStartContacts(constraints) {
    for (let c = 0; c < constraints.length; c++) {
      const con = constraints[c];
      for (let i = 0; i < con.points.length; i++) {
        const p = con.points[i];
        const impulse = Vec2.add(
          Vec2.scale(con.normal, p.normalImpulse),
          Vec2.scale(con.tangent, p.tangentImpulse)
        );
        con.bodyA.applyImpulse(Vec2.neg(impulse), p.point);
        con.bodyB.applyImpulse(impulse, p.point);
      }
    }
  }

  function solveVelocityContacts(constraints) {
    for (let c = 0; c < constraints.length; c++) {
      const con = constraints[c];
      const A = con.bodyA;
      const B = con.bodyB;
      for (let i = 0; i < con.points.length; i++) {
        const p = con.points[i];

        // normal impulse
        let dv = Vec2.sub(B.velocityAtPoint(p.point), A.velocityAtPoint(p.point));
        let vn = Vec2.dot(dv, con.normal);
        let dPn = p.normalMass * (p.bias - vn);
        const newImpulse = Math.max(p.normalImpulse + dPn, 0);
        dPn = newImpulse - p.normalImpulse;
        p.normalImpulse = newImpulse;
        const Pn = Vec2.scale(con.normal, dPn);
        A.applyImpulse(Vec2.neg(Pn), p.point);
        B.applyImpulse(Pn, p.point);

        // friction impulse, clamped to the Coulomb cone using the
        // *updated* normal impulse
        dv = Vec2.sub(B.velocityAtPoint(p.point), A.velocityAtPoint(p.point));
        const vt = Vec2.dot(dv, con.tangent);
        let dPt = p.tangentMass * -vt;
        const maxFriction = con.friction * p.normalImpulse;
        const newTangentImpulse = clamp(p.tangentImpulse + dPt, -maxFriction, maxFriction);
        dPt = newTangentImpulse - p.tangentImpulse;
        p.tangentImpulse = newTangentImpulse;
        const Pt = Vec2.scale(con.tangent, dPt);
        A.applyImpulse(Vec2.neg(Pt), p.point);
        B.applyImpulse(Pt, p.point);
      }
    }
  }

  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  const api = {
    prepareContacts: prepareContacts,
    warmStartContacts: warmStartContacts,
    solveVelocityContacts: solveVelocityContacts,
  };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.prepareContacts = prepareContacts;
    root.Torque.warmStartContacts = warmStartContacts;
    root.Torque.solveVelocityContacts = solveVelocityContacts;
  }
})(typeof window !== 'undefined' ? window : globalThis);
