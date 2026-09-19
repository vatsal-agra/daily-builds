// vec2.js -- minimal 2D vector math. UMD-style: works in Node (module.exports)
// and in the browser (window.Torque.Vec2), with no build step either way.
(function (root) {
  'use strict';

  function Vec2(x, y) {
    this.x = x || 0;
    this.y = y || 0;
  }

  Vec2.prototype.clone = function () {
    return new Vec2(this.x, this.y);
  };

  Vec2.prototype.set = function (x, y) {
    this.x = x;
    this.y = y;
    return this;
  };

  Vec2.add = function (a, b) {
    return new Vec2(a.x + b.x, a.y + b.y);
  };

  Vec2.sub = function (a, b) {
    return new Vec2(a.x - b.x, a.y - b.y);
  };

  Vec2.scale = function (a, s) {
    return new Vec2(a.x * s, a.y * s);
  };

  Vec2.neg = function (a) {
    return new Vec2(-a.x, -a.y);
  };

  // dot product
  Vec2.dot = function (a, b) {
    return a.x * b.x + a.y * b.y;
  };

  // 2D "cross product" of two vectors is a scalar (the z-component of the
  // 3D cross product with both inputs' z = 0).
  Vec2.cross = function (a, b) {
    return a.x * b.y - a.y * b.x;
  };

  // 2D cross of a scalar (z-component) and a vector: s * (0,0,1) x v
  Vec2.crossSV = function (s, v) {
    return new Vec2(-s * v.y, s * v.x);
  };

  // 2D cross of a vector and a scalar: v x (0,0,1)*s
  Vec2.crossVS = function (v, s) {
    return new Vec2(s * v.y, -s * v.x);
  };

  Vec2.len = function (a) {
    return Math.sqrt(a.x * a.x + a.y * a.y);
  };

  Vec2.lengthSq = function (a) {
    return a.x * a.x + a.y * a.y;
  };

  Vec2.normalize = function (a) {
    const len = Vec2.len(a);
    if (len < 1e-12) return new Vec2(0, 0);
    return new Vec2(a.x / len, a.y / len);
  };

  // perpendicular, rotated +90deg (counter-clockwise)
  Vec2.perp = function (a) {
    return new Vec2(-a.y, a.x);
  };

  Vec2.rotate = function (a, angle) {
    const c = Math.cos(angle);
    const s = Math.sin(angle);
    return new Vec2(a.x * c - a.y * s, a.x * s + a.y * c);
  };

  Vec2.lerp = function (a, b, t) {
    return new Vec2(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t);
  };

  Vec2.distance = function (a, b) {
    return Vec2.len(Vec2.sub(a, b));
  };

  const api = { Vec2: Vec2 };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.Torque = root.Torque || {};
    root.Torque.Vec2 = Vec2;
  }
})(typeof window !== 'undefined' ? window : globalThis);
