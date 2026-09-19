'use strict';

const { test, assert, assertClose } = require('./test-utils.js');
const T = require('../engine');

function run() {
  test('perfectly elastic equal-mass head-on collision swaps velocities exactly', () => {
    // damping off deliberately: this isolates the contact solver itself
    // from the (separate, correct) effect of default per-body damping.
    const world = new T.World({ gravity: new T.Vec2(0, 0), enableSleeping: false });
    const a = new T.Body(new T.Circle(0.5), {
      position: new T.Vec2(-1, 0), density: 1, restitution: 1, friction: 0, linearDamping: 0, angularDamping: 0,
    });
    a.velocity.x = 3;
    const b = new T.Body(new T.Circle(0.5), {
      position: new T.Vec2(1, 0), density: 1, restitution: 1, friction: 0, linearDamping: 0, angularDamping: 0,
    });
    world.addBody(a);
    world.addBody(b);
    const p0 = a.mass * a.velocity.x + b.mass * b.velocity.x;
    const e0 = 0.5 * a.mass * a.velocity.x * a.velocity.x;

    for (let i = 0; i < 300; i++) world.step(1 / 120);

    assertClose(a.velocity.x, 0, 1e-4, 'A stops');
    assertClose(b.velocity.x, 3, 1e-4, 'B takes A\'s velocity');
    const p1 = a.mass * a.velocity.x + b.mass * b.velocity.x;
    const e1 = 0.5 * a.mass * a.velocity.x * a.velocity.x + 0.5 * b.mass * b.velocity.x * b.velocity.x;
    assertClose(p1, p0, 1e-4, 'momentum conserved');
    assertClose(e1, e0, 1e-4, 'energy conserved');
  });

  test('restitution produces the energy-conservation-predicted bounce height', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10) });
    world.addBody(new T.Body(T.box(20, 1), { position: new T.Vec2(0, -0.5), isStatic: true, friction: 0.3 }));
    const restitution = 0.8;
    const dropHeight = 4.5; // from y=5 to resting y=0.5
    const ball = new T.Body(new T.Circle(0.5), {
      position: new T.Vec2(0, 5), density: 1, restitution: restitution, friction: 0.3,
    });
    world.addBody(ball);

    let hitGround = false;
    let peakY = 0;
    for (let i = 0; i < 600; i++) {
      world.step(1 / 120);
      if (!hitGround && ball.position.y < 0.55) hitGround = true;
      if (hitGround && ball.velocity.y > 0) peakY = Math.max(peakY, ball.position.y);
    }
    const predicted = 0.5 + restitution * restitution * dropHeight;
    assertClose(peakY, predicted, 0.15, 'first bounce peak height');
  });

  test('friction brings a sliding box to a full stop', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10) });
    world.addBody(new T.Body(T.box(50, 1), { position: new T.Vec2(0, -0.5), isStatic: true, friction: 0.8 }));
    const box = new T.Body(T.box(1, 1), { position: new T.Vec2(-15, 0.5), density: 1, friction: 0.8, restitution: 0 });
    box.velocity.x = 5;
    world.addBody(box);
    for (let i = 0; i < 600; i++) world.step(1 / 120);
    assertClose(box.velocity.x, 0, 0.01, 'friction stops the box');
  });

  test('zero friction lets a box slide indefinitely', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10), enableSleeping: false });
    world.addBody(new T.Body(T.box(50, 1), {
      position: new T.Vec2(0, -0.5), isStatic: true, friction: 0, restitution: 0,
    }));
    const box = new T.Body(T.box(1, 1), {
      position: new T.Vec2(-15, 0.5), density: 1, friction: 0, restitution: 0, linearDamping: 0,
    });
    box.velocity.x = 5;
    world.addBody(box);
    for (let i = 0; i < 300; i++) world.step(1 / 120);
    assertClose(box.velocity.x, 5, 0.02, 'no friction, no deceleration');
  });

  test('circle-polygon and polygon-polygon collisions produce finite, sensible results under rotation', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10) });
    world.addBody(new T.Body(T.box(20, 1), { position: new T.Vec2(0, -0.5), isStatic: true, friction: 0.5 }));
    const rotatedBox = new T.Body(T.box(1, 1), {
      position: new T.Vec2(-3, 5), angle: Math.PI / 4, density: 1, friction: 0.5, restitution: 0.1,
    });
    const ball = new T.Body(new T.Circle(0.4), {
      position: new T.Vec2(3, 5), density: 1, friction: 0.3, restitution: 0.2,
    });
    world.addBody(rotatedBox);
    world.addBody(ball);
    for (let i = 0; i < 600; i++) world.step(1 / 120);
    assert(isFinite(rotatedBox.position.x) && isFinite(rotatedBox.position.y), 'rotated box stable');
    assert(isFinite(ball.position.x) && isFinite(ball.position.y), 'ball stable');
    assert(rotatedBox.position.y > -0.5 && rotatedBox.position.y < 2, 'rotated box settled near the ground');
    assert(ball.position.y > -0.5 && ball.position.y < 2, 'ball settled near the ground');
  });
}

module.exports = { run };
