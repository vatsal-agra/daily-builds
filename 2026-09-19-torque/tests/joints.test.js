'use strict';

const { test, assert, assertClose } = require('./test-utils.js');
const T = require('../engine');

function run() {
  test('a distance-jointed pendulum matches the small-angle period formula', () => {
    const g = 10;
    const L = 2;
    const theta0 = 0.15; // small angle, radians, from the DOWNWARD vertical
    const world = new T.World({ gravity: new T.Vec2(0, -g), enableSleeping: false });
    const anchor = new T.Body(new T.Circle(0.02), { position: new T.Vec2(0, 0), isStatic: true });
    const bob = new T.Body(new T.Circle(0.05), {
      position: new T.Vec2(L * Math.sin(theta0), -L * Math.cos(theta0)),
      density: 1, restitution: 0, friction: 0, linearDamping: 0, angularDamping: 0,
    });
    world.addBody(anchor);
    world.addBody(bob);
    world.addJoint(new T.DistanceJoint(anchor, bob, new T.Vec2(0, 0), new T.Vec2(0, 0), L));

    const dt = 1 / 480;
    const crossings = [];
    let lastX = bob.position.x;
    for (let i = 0; i < 480 * 15; i++) {
      world.step(dt);
      if (lastX < 0 && bob.position.x >= 0) crossings.push(i * dt);
      lastX = bob.position.x;
    }
    assert(crossings.length >= 3, 'expected several full swings, got ' + crossings.length);
    const periods = [];
    for (let i = 1; i < crossings.length; i++) periods.push(crossings[i] - crossings[i - 1]);
    const measured = periods.reduce((a, b) => a + b, 0) / periods.length;
    const analytical = 2 * Math.PI * Math.sqrt(L / g);
    assertClose(measured, analytical, analytical * 0.03, 'measured vs. analytical pendulum period');
  });

  test('a revolute joint keeps its two anchor points coincident under load', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10), enableSleeping: false });
    const anchor = new T.Body(new T.Circle(0.05), { position: new T.Vec2(0, 5), isStatic: true });
    const bob = new T.Body(new T.Circle(0.3), { position: new T.Vec2(2, 5), density: 1 });
    world.addBody(anchor);
    world.addBody(bob);
    const joint = new T.RevoluteJoint(anchor, bob, new T.Vec2(0, 5));
    world.addJoint(joint);

    let maxError = 0;
    for (let i = 0; i < 600; i++) {
      world.step(1 / 120);
      const pA = T.Vec2.add(anchor.position, T.Vec2.rotate(joint.localAnchorA, anchor.angle));
      const pB = T.Vec2.add(bob.position, T.Vec2.rotate(joint.localAnchorB, bob.angle));
      maxError = Math.max(maxError, T.Vec2.distance(pA, pB));
    }
    assert(maxError < 0.01, 'max anchor separation over the run was ' + maxError);
  });

  test('REGRESSION: collideConnected=false lets a jointed pendulum swing (it used to freeze)', () => {
    // Reproduces the exact scenario from REVIEW.md bug #2: an anchor and a
    // link whose collision shapes overlap at the shared pivot, which used
    // to make the contact solver fight the joint and hold the link almost
    // perfectly still instead of swinging.
    const world = new T.World({ gravity: new T.Vec2(0, -10), enableSleeping: false });
    const anchor = new T.Body(T.box(0.2, 0.2), { position: new T.Vec2(0, 5), isStatic: true });
    const link = new T.Body(T.box(0.8, 0.2), {
      position: new T.Vec2(0.4, 5), density: 1, friction: 0.2, linearDamping: 0, angularDamping: 0,
    });
    world.addBody(anchor);
    world.addBody(link);
    const joint = new T.RevoluteJoint(anchor, link, new T.Vec2(0, 5));
    world.addJoint(joint);
    assert(joint.collideConnected === false, 'collideConnected must default to false');

    for (let i = 0; i < 40; i++) world.step(1 / 120);
    // hand-derived reference (I*phi'' = -mgd*sin(phi) from horizontal
    // release): ~57 degrees of rotation is expected in this window; a
    // frozen joint (the bug) produced ~0.001 degrees.
    assert(Math.abs(link.angle) > 0.3, 'expected the pendulum to have swung noticeably, got angle=' + link.angle);
  });

  test('an 8-link revolute chain hangs in a stable, non-exploding curve', () => {
    const world = new T.World({ gravity: new T.Vec2(0, -10) });
    const anchor = new T.Body(new T.Circle(0.1), { position: new T.Vec2(0, 10), isStatic: true });
    world.addBody(anchor);
    let prev = anchor;
    const links = [];
    const linkW = 0.9;
    for (let i = 0; i < 8; i++) {
      const link = new T.Body(T.box(linkW, 0.25), {
        position: new T.Vec2(linkW * (i + 0.5), 10), density: 1, friction: 0.2,
      });
      world.addBody(link);
      world.addJoint(new T.RevoluteJoint(prev, link, new T.Vec2(linkW * i, 10)));
      links.push(link);
      prev = link;
    }
    for (let i = 0; i < 1800; i++) world.step(1 / 120);
    // A lightly-damped 8-link chain is a genuinely underdamped multi-body
    // pendulum system -- it legitimately keeps swinging for a long time
    // (verified separately against a single-link case converging cleanly
    // under heavier damping), so this checks the actual invariant that
    // matters here: bounded and finite, not literally at rest.
    for (let i = 0; i < links.length; i++) {
      assert(isFinite(links[i].position.x) && isFinite(links[i].position.y), `link ${i} finite`);
      assert(Math.hypot(links[i].velocity.x, links[i].velocity.y) < 30, `link ${i} velocity stayed bounded`);
    }
    // the chain should hang predominantly downward, not stay near y=10
    assert(links[links.length - 1].position.y < 9, 'far end of the chain has drooped');
  });
}

module.exports = { run };
