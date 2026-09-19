'use strict';

const { test, assert, assertClose } = require('./test-utils.js');
const T = require('../engine');

function run() {
  test('free fall matches semi-implicit Euler integration exactly', () => {
    // semi-implicit Euler: v += g*dt; x += v*dt (that ordering, so it is
    // NOT the closed-form x = 1/2 g t^2 -- assert against the same
    // integration scheme the engine actually uses, not calculus.
    const world = new T.World({ gravity: new T.Vec2(0, -10), enableSleeping: false });
    const body = new T.Body(new T.Circle(0.1), {
      position: new T.Vec2(0, 100), density: 1, linearDamping: 0, angularDamping: 0,
    });
    world.addBody(body);

    const dt = 1 / 120;
    let expectedV = 0, expectedY = 100;
    for (let i = 0; i < 100; i++) {
      world.step(dt);
      expectedV += -10 * dt;
      expectedY += expectedV * dt;
    }
    assertClose(body.velocity.y, expectedV, 1e-6, 'velocity');
    assertClose(body.position.y, expectedY, 1e-6, 'position');
  });

  test('a box dropped on the ground settles at the expected resting height', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10) });
    world.addBody(new T.Body(T.box(20, 1), { position: new T.Vec2(0, -0.5), isStatic: true, friction: 0.5 }));
    const box = new T.Body(T.box(1, 1), { position: new T.Vec2(0, 5), density: 1, restitution: 0.1, friction: 0.5 });
    world.addBody(box);
    for (let i = 0; i < 600; i++) world.step(1 / 120);
    assertClose(box.position.y, 0.5, 0.02, 'resting height (ground top at y=0, half-height 0.5)');
    assertClose(box.angle, 0, 0.02, 'stays upright');
  });

  test('a box at rest goes to sleep and stays asleep', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10) });
    world.addBody(new T.Body(T.box(20, 1), { position: new T.Vec2(0, -0.5), isStatic: true, friction: 0.5 }));
    const box = new T.Body(T.box(1, 1), { position: new T.Vec2(0, 3), density: 1, restitution: 0, friction: 0.5 });
    world.addBody(box);
    for (let i = 0; i < 300; i++) world.step(1 / 120);
    assert(box.isSleeping, 'expected the box to have fallen asleep by t=2.5s');
    // regression test for the sleep/wake bug found in REVIEW.md: a sleeping
    // body touching a static one must never be re-woken every frame
    const yBefore = box.position.y;
    for (let i = 0; i < 120; i++) world.step(1 / 120);
    assert(box.isSleeping, 'a static neighbor must never wake a sleeping body back up');
    assertClose(box.position.y, yBefore, 1e-9, 'a sleeping body must not silently drift');
  });

  test('a 6-box stack settles without sinking or exploding', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10) });
    world.addBody(new T.Body(T.box(20, 1), { position: new T.Vec2(0, -0.5), isStatic: true, friction: 0.6 }));
    const boxes = [];
    for (let i = 0; i < 6; i++) {
      const b = new T.Body(T.box(1, 1), { position: new T.Vec2(0, 0.5 + i * 1.01), density: 1, friction: 0.6 });
      world.addBody(b);
      boxes.push(b);
    }
    for (let i = 0; i < 900; i++) world.step(1 / 120);
    for (let i = 0; i < boxes.length; i++) {
      assert(isFinite(boxes[i].position.x) && isFinite(boxes[i].position.y), `box ${i} position is finite`);
      assertClose(boxes[i].position.y, 0.5 + i, 0.05, `box ${i} settles at its expected shelf height`);
      assert(Math.abs(boxes[i].angle) < 0.05, `box ${i} stays upright`);
    }
  });

  test('input validation rejects nonsense at construction and at step time', () => {
    const mustThrow = (fn, what) => {
      let threw = false;
      try {
        fn();
      } catch (e) {
        threw = true;
      }
      assert(threw, 'expected ' + what + ' to throw');
    };
    mustThrow(() => new T.Body(T.box(1, 1), { density: 0 }), 'zero density');
    mustThrow(() => new T.Circle(-1), 'negative radius');
    mustThrow(() => new T.Polygon([new T.Vec2(0, 0), new T.Vec2(1, 0)]), '2-vertex polygon');
    mustThrow(() => new T.World().step(0), 'dt = 0');
    mustThrow(() => new T.World().step(-1), 'negative dt');
  });

  test('removing a body drops joints that referenced it instead of crashing', () => {
    const world = new T.World();
    const a = new T.Body(new T.Circle(0.5), { position: new T.Vec2(0, 0) });
    const b = new T.Body(new T.Circle(0.5), { position: new T.Vec2(1, 0) });
    world.addBody(a);
    world.addBody(b);
    world.addJoint(new T.DistanceJoint(a, b, new T.Vec2(0, 0), new T.Vec2(0, 0)));
    world.removeBody(a);
    assert(world.joints.length === 0, 'dangling joint should have been dropped');
    world.step(1 / 60); // must not throw
  });
}

module.exports = { run };
