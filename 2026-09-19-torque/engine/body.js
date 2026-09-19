// body.js -- RigidBody: transform, velocities, mass/inertia, force
// accumulators, and material properties (restitution, friction).
(function (root) {
  'use strict';

  const dep = typeof module !== 'undefined' && module.exports
    ? require('./vec2.js')
    : { Vec2: root.Torque.Vec2 };
  const Vec2 = dep.Vec2;

  let nextId = 1;

  // options: { position, angle, density, restitution, friction, isStatic,
  //            linearDamping, angularDamping, fixedRotation }
  function Body(shape, options) {
    options = options || {};
    this.id = nextId++;
    this.shape = shape;
    this.position = (options.position || new Vec2(0, 0)).clone();
    this.angle = options.angle || 0;

    this.velocity = new Vec2(0, 0);
    this.angularVelocity = 0;

    this.force = new Vec2(0, 0);
    this.torque = 0;

    this.isStatic = !!options.isStatic;
    this.restitution = options.restitution !== undefined ? options.restitution : 0.2;
    this.friction = options.friction !== undefined ? options.friction : 0.4;
    this.linearDamping = options.linearDamping !== undefined ? options.linearDamping : 0.01;
    this.angularDamping = options.angularDamping !== undefined ? options.angularDamping : 0.01;

    const density = options.density !== undefined ? options.density : 1;

    if (this.isStatic) {
      this.mass = 0;
      this.invMass = 0;
      this.inertia = 0;
      this.invInertia = 0;
    } else {
      const md = shape.computeMass(density);
      if (!(md.mass > 0)) throw new Error('body mass must be > 0 for a dynamic body');
      this.mass = md.mass;
      this.invMass = 1 / md.mass;
      // fixedRotation (e.g. a character controller) pins angular inertia
      // to infinite -- the body can never be spun by torque or friction.
      if (options.fixedRotation || md.inertia <= 0) {
        this.inertia = Infinity;
        this.invInertia = 0;
      } else {
        this.inertia = md.inertia;
        this.invInertia = 1 / md.inertia;
      }
    }

    this.isSleeping = false;
    this.sleepTime = 0;
    // userData is free for callers (e.g. the demo) to stash render info on.
    this.userData = options.userData || null;
  }

  Body.prototype.applyForce = function (force, worldPoint) {
    if (this.isStatic || this.isSleeping) return;
    this.force.x += force.x;
    this.force.y += force.y;
    if (worldPoint) {
      const r = Vec2.sub(worldPoint, this.position);
      this.torque += Vec2.cross(r, force);
    }
  };

  Body.prototype.applyTorque = function (torque) {
    if (this.isStatic || this.isSleeping) return;
    this.torque += torque;
  };

  // Directly changes velocity/angularVelocity -- used by the contact and
  // joint solvers (impulses resolve instantaneously, not over a timestep).
  // Sleeping bodies must never be silently perturbed here: World wakes a
  // body explicitly (setAwake) before any solver touches it, so a solver
  // impulse reaching a still-sleeping body would corrupt its velocity
  // without the position integrator ever picking that velocity up.
  Body.prototype.applyImpulse = function (impulse, worldPoint) {
    if (this.isStatic || this.isSleeping) return;
    this.velocity.x += impulse.x * this.invMass;
    this.velocity.y += impulse.y * this.invMass;
    if (worldPoint) {
      const r = Vec2.sub(worldPoint, this.position);
      this.angularVelocity += this.invInertia * Vec2.cross(r, impulse);
    }
  };

  Body.prototype.setAwake = function (awake) {
    if (this.isStatic) return;
    if (awake) {
      this.isSleeping = false;
      this.sleepTime = 0;
    } else {
      this.isSleeping = true;
      this.velocity.set(0, 0);
      this.angularVelocity = 0;
    }
  };

  // Velocity of the material point currently at worldPoint (linear + the
  // rotational contribution omega x r). Used by contact/joint Jacobians.
  Body.prototype.velocityAtPoint = function (worldPoint) {
    const r = Vec2.sub(worldPoint, this.position);
    return Vec2.add(this.velocity, Vec2.crossSV(this.angularVelocity, r));
  };

  Body.prototype.worldAABB = function () {
    if (this.shape.type === 'circle') {
      return this.shape.computeAABB(this.position);
    }
    return this.shape.computeAABB(this.position, this.angle);
  };

  const api = { Body: Body };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.Body = Body;
  }
})(typeof window !== 'undefined' ? window : globalThis);
