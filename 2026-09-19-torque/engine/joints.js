// joints.js -- DistanceJoint (rigid rod between two anchor points) and
// RevoluteJoint (pin: forces two anchor points to coincide, 2 equations).
// Both are solved as velocity constraints in the same iterative loop as
// contacts (see world.js), with their own warm-started accumulated
// impulses persisted on the joint object across frames.
(function (root) {
  'use strict';

  const dep = typeof module !== 'undefined' && module.exports
    ? require('./vec2.js')
    : { Vec2: root.Torque.Vec2 };
  const Vec2 = dep.Vec2;

  const BAUMGARTE = 0.2;
  // Caps how fast a joint is allowed to try to close a positional error in
  // one step, same idea as the contact solver's MAX_BAUMGARTE_BIAS: at a
  // fine timestep BAUMGARTE/dt is large (e.g. 24 at 1/120s), so an
  // uncapped position error -- like a user yanking a mouse-dragged body
  // several units in one frame -- would otherwise produce a single violent
  // impulse instead of a fast-but-bounded pull.
  const MAX_CORRECTION_SPEED = 10;

  function clampVectorLength(v, maxLen) {
    const lenSq = v.x * v.x + v.y * v.y;
    if (lenSq <= maxLen * maxLen) return v;
    const scale = maxLen / Math.sqrt(lenSq);
    return new Vec2(v.x * scale, v.y * scale);
  }

  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  function anchorWorld(body, localAnchor) {
    return Vec2.add(body.position, Vec2.rotate(localAnchor, body.angle));
  }

  // localAnchorA/B are in each body's local frame. length defaults to the
  // initial world distance between the anchors if not given.
  //
  // collideConnected defaults to false: two bodies linked by a joint
  // almost always share or overlap geometry at their anchor point (a
  // chain link's neighbor, a pendulum bob and its anchor), so letting the
  // contact solver *also* push them apart would fight the joint's own
  // constraint every step -- a real instability, not a cosmetic one (see
  // REVIEW.md).
  function DistanceJoint(bodyA, bodyB, localAnchorA, localAnchorB, length, collideConnected) {
    this.bodyA = bodyA;
    this.bodyB = bodyB;
    this.localAnchorA = localAnchorA.clone();
    this.localAnchorB = localAnchorB.clone();
    if (length === undefined) {
      const pA = anchorWorld(bodyA, localAnchorA);
      const pB = anchorWorld(bodyB, localAnchorB);
      length = Vec2.distance(pA, pB);
    }
    this.length = length;
    this.impulse = 0;
    this.collideConnected = !!collideConnected;
  }

  DistanceJoint.prototype.prepare = function (dt) {
    const A = this.bodyA, B = this.bodyB;
    const pA = anchorWorld(A, this.localAnchorA);
    const pB = anchorWorld(B, this.localAnchorB);
    this.rA = Vec2.sub(pA, A.position);
    this.rB = Vec2.sub(pB, B.position);
    const d = Vec2.sub(pB, pA);
    let dist = Vec2.len(d);
    this.u = dist > 1e-9 ? Vec2.scale(d, 1 / dist) : new Vec2(1, 0);

    const crA = Vec2.cross(this.rA, this.u);
    const crB = Vec2.cross(this.rB, this.u);
    const k = A.invMass + B.invMass + A.invInertia * crA * crA + B.invInertia * crB * crB;
    this.mass = k > 0 ? 1 / k : 0;

    const C = dist - this.length;
    const rawBias = (BAUMGARTE / dt) * C;
    this.bias = clamp(rawBias, -MAX_CORRECTION_SPEED, MAX_CORRECTION_SPEED);
    this._pA = pA;
    this._pB = pB;
  };

  DistanceJoint.prototype.warmStart = function () {
    const P = Vec2.scale(this.u, this.impulse);
    this.bodyA.applyImpulse(Vec2.neg(P), this._pA);
    this.bodyB.applyImpulse(P, this._pB);
  };

  DistanceJoint.prototype.solveVelocity = function () {
    const A = this.bodyA, B = this.bodyB;
    const vA = A.velocityAtPoint(this._pA);
    const vB = B.velocityAtPoint(this._pB);
    const Cdot = Vec2.dot(this.u, Vec2.sub(vB, vA));
    const lambda = -this.mass * (Cdot + this.bias);
    this.impulse += lambda;
    const P = Vec2.scale(this.u, lambda);
    A.applyImpulse(Vec2.neg(P), this._pA);
    B.applyImpulse(P, this._pB);
  };

  // Point-to-point (pin) joint: forces anchorWorld(A) == anchorWorld(B).
  // See the DistanceJoint comment above -- collideConnected also defaults
  // to false here, for the same reason.
  function RevoluteJoint(bodyA, bodyB, worldAnchor, collideConnected) {
    this.bodyA = bodyA;
    this.bodyB = bodyB;
    this.localAnchorA = Vec2.rotate(Vec2.sub(worldAnchor, bodyA.position), -bodyA.angle);
    this.localAnchorB = Vec2.rotate(Vec2.sub(worldAnchor, bodyB.position), -bodyB.angle);
    this.impulse = new Vec2(0, 0);
    this.collideConnected = !!collideConnected;
  }

  RevoluteJoint.prototype.prepare = function (dt) {
    const A = this.bodyA, B = this.bodyB;
    const pA = anchorWorld(A, this.localAnchorA);
    const pB = anchorWorld(B, this.localAnchorB);
    this.rA = Vec2.sub(pA, A.position);
    this.rB = Vec2.sub(pB, B.position);
    this._pA = pA;
    this._pB = pB;

    const mA = A.invMass, mB = B.invMass, iA = A.invInertia, iB = B.invInertia;
    const rA = this.rA, rB = this.rB;

    const k11 = mA + mB + iA * rA.y * rA.y + iB * rB.y * rB.y;
    const k12 = -iA * rA.x * rA.y - iB * rB.x * rB.y;
    const k22 = mA + mB + iA * rA.x * rA.x + iB * rB.x * rB.x;
    this.K = { k11: k11, k12: k12, k22: k22 };

    const C = Vec2.sub(pB, pA);
    this.bias = clampVectorLength(Vec2.scale(C, BAUMGARTE / dt), MAX_CORRECTION_SPEED);
  };

  RevoluteJoint.prototype.warmStart = function () {
    this.bodyA.applyImpulse(Vec2.neg(this.impulse), this._pA);
    this.bodyB.applyImpulse(this.impulse, this._pB);
  };

  RevoluteJoint.prototype.solveVelocity = function () {
    const A = this.bodyA, B = this.bodyB;
    const vA = A.velocityAtPoint(this._pA);
    const vB = B.velocityAtPoint(this._pB);
    const Cdot = Vec2.add(Vec2.sub(vB, vA), this.bias);

    const k = this.K;
    const det = k.k11 * k.k22 - k.k12 * k.k12;
    let impulse;
    if (Math.abs(det) < 1e-12) {
      impulse = new Vec2(0, 0);
    } else {
      const invDet = 1 / det;
      impulse = new Vec2(
        -invDet * (k.k22 * Cdot.x - k.k12 * Cdot.y),
        -invDet * (k.k11 * Cdot.y - k.k12 * Cdot.x)
      );
    }
    this.impulse.x += impulse.x;
    this.impulse.y += impulse.y;
    A.applyImpulse(Vec2.neg(impulse), this._pA);
    B.applyImpulse(impulse, this._pB);
  };

  const api = { DistanceJoint: DistanceJoint, RevoluteJoint: RevoluteJoint };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.DistanceJoint = DistanceJoint;
    root.Torque.RevoluteJoint = RevoluteJoint;
  }
})(typeof window !== 'undefined' ? window : globalThis);
