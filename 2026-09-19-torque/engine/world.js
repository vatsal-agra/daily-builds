// world.js -- ties the engine together: fixed-step loop of
// integrate-forces -> broad phase -> narrow phase -> warm start -> N
// velocity-solve iterations (joints and contacts interleaved so a chain of
// joints resting on a stack of boxes behaves as one coupled system) ->
// integrate positions -> sleep bookkeeping.
(function (root) {
  'use strict';

  let Vec2, computeBroadPhasePairs, collide, prepareContacts, warmStartContacts, solveVelocityContacts;
  if (typeof module !== 'undefined' && module.exports) {
    Vec2 = require('./vec2.js').Vec2;
    computeBroadPhasePairs = require('./aabb.js').computeBroadPhasePairs;
    collide = require('./collision.js').collide;
    const solver = require('./solver.js');
    prepareContacts = solver.prepareContacts;
    warmStartContacts = solver.warmStartContacts;
    solveVelocityContacts = solver.solveVelocityContacts;
  } else {
    Vec2 = root.Torque.Vec2;
    computeBroadPhasePairs = root.Torque.computeBroadPhasePairs;
    collide = root.Torque.collide;
    prepareContacts = root.Torque.prepareContacts;
    warmStartContacts = root.Torque.warmStartContacts;
    solveVelocityContacts = root.Torque.solveVelocityContacts;
  }

  const SLEEP_LINEAR_THRESHOLD = 0.05; // units/s
  const SLEEP_ANGULAR_THRESHOLD = 0.05; // rad/s
  const SLEEP_TIME_THRESHOLD = 0.5; // seconds below threshold before sleeping
  const WARM_START_MATCH_DIST = 0.06; // world units; nearest-point contact matching across frames
  const VELOCITY_ITERATIONS = 8;

  function World(options) {
    options = options || {};
    this.gravity = options.gravity || new Vec2(0, -10);
    this.bodies = [];
    this.joints = [];
    this.enableSleeping = options.enableSleeping !== false;
    this._contactCache = new Map(); // pairKey -> [{point, normalImpulse, tangentImpulse}]
    // last computed manifolds, exposed for renderers/debug and for tests
    this.contacts = [];
  }

  World.prototype.addBody = function (body) {
    this.bodies.push(body);
    return body;
  };

  World.prototype.removeBody = function (body) {
    const i = this.bodies.indexOf(body);
    if (i >= 0) this.bodies.splice(i, 1);
    // drop any joints that referenced it -- a dangling joint on a removed
    // body would crash the next prepare() call.
    this.joints = this.joints.filter((j) => j.bodyA !== body && j.bodyB !== body);
  };

  World.prototype.addJoint = function (joint) {
    this.joints.push(joint);
    return joint;
  };

  World.prototype.removeJoint = function (joint) {
    const i = this.joints.indexOf(joint);
    if (i >= 0) this.joints.splice(i, 1);
  };

  World.prototype.step = function (dt) {
    if (!(dt > 0)) throw new Error('World.step requires dt > 0');

    this._integrateForces(dt);

    const pairs = computeBroadPhasePairs(this.bodies);
    const manifoldEntries = this._narrowPhase(pairs);

    const constraints = prepareContacts(manifoldEntries, dt);
    for (let j = 0; j < this.joints.length; j++) this.joints[j].prepare(dt);

    warmStartContacts(constraints);
    for (let j = 0; j < this.joints.length; j++) this.joints[j].warmStart();

    for (let iter = 0; iter < VELOCITY_ITERATIONS; iter++) {
      for (let j = 0; j < this.joints.length; j++) this.joints[j].solveVelocity();
      solveVelocityContacts(constraints);
    }

    this._integratePositions(dt);
    this._updateContactCache(constraints);
    this.contacts = constraints;

    if (this.enableSleeping) this._updateSleeping(dt, constraints);
  };

  World.prototype._integrateForces = function (dt) {
    for (let i = 0; i < this.bodies.length; i++) {
      const b = this.bodies[i];
      if (b.isStatic || b.isSleeping) continue;
      b.velocity.x += (this.gravity.x + b.force.x * b.invMass) * dt;
      b.velocity.y += (this.gravity.y + b.force.y * b.invMass) * dt;
      b.angularVelocity += b.torque * b.invInertia * dt;
      b.velocity.x *= 1 / (1 + dt * b.linearDamping);
      b.velocity.y *= 1 / (1 + dt * b.linearDamping);
      b.angularVelocity *= 1 / (1 + dt * b.angularDamping);
      b.force.set(0, 0);
      b.torque = 0;
    }
  };

  World.prototype._integratePositions = function (dt) {
    for (let i = 0; i < this.bodies.length; i++) {
      const b = this.bodies[i];
      if (b.isStatic || b.isSleeping) continue;
      b.position.x += b.velocity.x * dt;
      b.position.y += b.velocity.y * dt;
      b.angle += b.angularVelocity * dt;
    }
  };

  function pairKey(a, b) {
    return a.id < b.id ? a.id + '_' + b.id : b.id + '_' + a.id;
  }

  World.prototype._narrowPhase = function (pairs) {
    const entries = [];
    for (let p = 0; p < pairs.length; p++) {
      let [b1, b2] = pairs[p];
      // canonicalize order by id so the manifold's A->B normal convention
      // is stable across frames regardless of broad-phase sort order --
      // otherwise warm-start impulse signs could flip and inject energy.
      const bodyA = b1.id < b2.id ? b1 : b2;
      const bodyB = b1.id < b2.id ? b2 : b1;

      // "active" = actually capable of having moved since last step. If
      // neither body is active, nothing changed and nothing needs waking
      // -- crucially this excludes a static body from ever counting as
      // the "other body is active" reason to wake a sleeping neighbor
      // (a static body's isSleeping is permanently false, but it never
      // moves, so it must never itself wake anything).
      const aActive = !bodyA.isStatic && !bodyA.isSleeping;
      const bActive = !bodyB.isStatic && !bodyB.isSleeping;
      if (!aActive && !bActive) continue;

      const manifold = collide(bodyA, bodyB);
      if (!manifold) continue;
      if (bodyA.isSleeping && bActive) bodyA.setAwake(true);
      if (bodyB.isSleeping && aActive) bodyB.setAwake(true);
      this._attachManifold(entries, bodyA, bodyB, manifold);
    }
    return entries;
  };

  World.prototype._attachManifold = function (entries, bodyA, bodyB, manifold) {
    const key = pairKey(bodyA, bodyB);
    const cached = this._contactCache.get(key);
    for (let i = 0; i < manifold.points.length; i++) {
      const mp = manifold.points[i];
      if (cached) {
        let best = null;
        let bestDist = WARM_START_MATCH_DIST;
        for (let c = 0; c < cached.length; c++) {
          const d = Vec2.distance(cached[c].point, mp.point);
          if (d < bestDist) {
            bestDist = d;
            best = cached[c];
          }
        }
        if (best) {
          mp.warmNormalImpulse = best.normalImpulse;
          mp.warmTangentImpulse = best.tangentImpulse;
        }
      }
    }
    entries.push({ bodyA: bodyA, bodyB: bodyB, manifold: manifold, key: key });
  };

  World.prototype._updateContactCache = function (constraints) {
    const next = new Map();
    for (let c = 0; c < constraints.length; c++) {
      const con = constraints[c];
      const key = pairKey(con.bodyA, con.bodyB);
      next.set(
        key,
        con.points.map((p) => ({
          point: p.point,
          normalImpulse: p.normalImpulse,
          tangentImpulse: p.tangentImpulse,
        }))
      );
    }
    this._contactCache = next;
  };

  World.prototype._updateSleeping = function (dt, constraints) {
    // A body may only sleep if every body it's touching this frame (via a
    // contact or a joint) is also below the velocity threshold -- otherwise
    // a box resting on top of a still-swinging pendulum bob would freeze
    // mid-air the instant its own velocity dipped low for one frame.
    const touchingActive = new Set();
    const below = (b) =>
      Vec2.lengthSq(b.velocity) < SLEEP_LINEAR_THRESHOLD * SLEEP_LINEAR_THRESHOLD &&
      b.angularVelocity * b.angularVelocity < SLEEP_ANGULAR_THRESHOLD * SLEEP_ANGULAR_THRESHOLD;

    const neighborsActive = (bodies) => {
      for (const b of bodies) {
        if (!b.isStatic && !below(b)) return true;
      }
      return false;
    };

    for (let c = 0; c < constraints.length; c++) {
      const con = constraints[c];
      if (neighborsActive([con.bodyA, con.bodyB])) {
        touchingActive.add(con.bodyA.id);
        touchingActive.add(con.bodyB.id);
      }
    }
    for (let j = 0; j < this.joints.length; j++) {
      const joint = this.joints[j];
      if (neighborsActive([joint.bodyA, joint.bodyB])) {
        touchingActive.add(joint.bodyA.id);
        touchingActive.add(joint.bodyB.id);
      }
    }

    for (let i = 0; i < this.bodies.length; i++) {
      const b = this.bodies[i];
      if (b.isStatic || b.isSleeping) continue;
      if (!below(b) || touchingActive.has(b.id)) {
        b.sleepTime = 0;
        continue;
      }
      b.sleepTime += dt;
      if (b.sleepTime > SLEEP_TIME_THRESHOLD) {
        b.setAwake(false);
      }
    }
  };

  const api = { World: World };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.World = World;
  }
})(typeof window !== 'undefined' ? window : globalThis);
