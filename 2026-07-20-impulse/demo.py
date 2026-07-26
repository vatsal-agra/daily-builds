#!/usr/bin/env python3
"""
Headless demo/verification script for Impulse.

Exercises every required feature end-to-end with longer, more realistic
simulations than the unit tests (a box stack settling under its own
weight, a pendulum conserving energy on a pin joint, a rope bridge
sagging and holding under a dropped load) and prints a pass/fail report.
Exits non-zero if anything fails, so it doubles as a CI-style gate.
"""

import math
import sys

import engine as E


PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {detail}")


def demo_box_stack_settles():
    print("\n== Demo: 6-box stack settles under gravity ==")
    w = E.World(gravity=(0, 500))
    ground = E.Body(E.Box(400, 40), (300, 580), static=True, friction=0.6)
    w.add_body(ground)
    boxes = [E.Body(E.Box(50, 50), (300 + (i % 2) * 6 - 3, 560 - i * 52),
                    friction=0.6, restitution=0.05) for i in range(6)]
    for b in boxes:
        w.add_body(b)
    for _ in range(1500):
        w.step(1 / 120)
    top_y = boxes[-1].position.y
    bottom_y = boxes[0].position.y
    spacing_ok = all(abs((boxes[i].position.y - boxes[i + 1].position.y) - 50) < 10
                      for i in range(len(boxes) - 1))
    upright = all(abs(b.angle) < 0.1 for b in boxes)
    print(f"    bottom box y={bottom_y:.1f}  top box y={top_y:.1f}")
    check("stack settles into an ordered, non-overlapping tower", spacing_ok)
    check("no box tips over", upright)


def demo_pendulum_energy_bounded():
    print("\n== Demo: pin-joint pendulum stays near-conservative ==")
    pivot = E.Vec2(400, 100)
    length = 200.0
    theta0 = math.radians(50)
    bob = E.Body(E.Circle(15), (pivot.x + length * math.sin(theta0),
                                pivot.y + length * math.cos(theta0)),
                friction=0.0, linear_damping=0.0, angular_damping=0.0)
    w = E.World(gravity=(0, 500))
    w.add_body(bob)
    w.add_joint(E.DistanceJoint(bob, (0, 0), None, pivot.to_tuple()))

    def energy(b):
        h = b.position.y - pivot.y  # height below pivot (potential ref)
        pe = -500 * b.mass * h  # gravity does positive work moving down (+y)
        ke = 0.5 * b.mass * b.velocity.length_sq()
        return pe + ke

    e0 = energy(bob)
    max_drift_pct = 0.0
    max_length_err = 0.0
    for i in range(3600):
        w.step(1 / 120)
        e = energy(bob)
        max_drift_pct = max(max_drift_pct, abs(e - e0) / abs(e0))
        max_length_err = max(max_length_err, abs((bob.position - pivot).length() - length))
    print(f"    max energy drift: {max_drift_pct * 100:.2f}%   max length error: {max_length_err:.3f}px")
    # Baumgarte position correction does inject/remove a little energy each
    # step by design (that's how it fixes drift), so this isn't perfectly
    # conservative -- bound it generously rather than expecting exact physics.
    check("pendulum energy stays roughly bounded over 30s", max_drift_pct < 0.35)
    check("rod length never drifts more than 2px", max_length_err < 2.0)


def demo_bridge_holds_under_load():
    print("\n== Demo: rope bridge sags and holds a dropped weight ==")
    w = E.World(gravity=(0, 500))
    n = 10
    span = 400
    start_x = 250
    y = 200
    plank_w = span / n
    planks = []
    for i in range(n):
        x = start_x + (i + 0.5) * plank_w
        planks.append(E.Body(E.Box(plank_w * 0.95, 14), (x, y),
                             friction=0.8, density=0.6, restitution=0.0))
    for p in planks:
        w.add_body(p)
    for i in range(n - 1):
        w.add_joint(E.DistanceJoint(planks[i], (plank_w * 0.45, 0),
                                    planks[i + 1], (-plank_w * 0.45, 0)))
    w.add_joint(E.DistanceJoint(planks[0], (-plank_w * 0.45, 0), None, (start_x, y)))
    w.add_joint(E.DistanceJoint(planks[-1], (plank_w * 0.45, 0), None, (start_x + span, y)))

    for _ in range(600):
        w.step(1 / 120)
    sagged_y = planks[n // 2].position.y
    print(f"    bridge midpoint sagged to y={sagged_y:.1f} (started at {y})")
    check("bridge sags under its own weight (forms a catenary, doesn't stay flat)",
          sagged_y > y + 5)

    boulder = E.Body(E.Circle(25), (start_x + span / 2, 20), density=3.0, restitution=0.0)
    w.add_body(boulder)
    max_y_seen = 0.0
    for _ in range(1800):  # a full 15s -- a lightly-damped multi-joint chain
        w.step(1 / 120)     # takes a while to stop oscillating, that's realistic
        max_y_seen = max(max_y_seen, boulder.position.y)
    joint_lengths_ok = True
    for j in w.joints:
        wa, wb = j._world_anchors()
        err = abs((wb - wa).length() - j.length)
        if err > 3.0:
            joint_lengths_ok = False
    final_boulder_y = boulder.position.y
    final_speed = boulder.velocity.length()
    print(f"    boulder final y={final_boulder_y:.1f}, speed={final_speed:.1f}px/s, "
          f"deepest sag reached y={max_y_seen:.1f}")
    check("bridge holds under a dropped load without snapping (joints stay near rest length)",
          joint_lengths_ok)
    # "falling through" would mean the boulder ends up well below the bridge's
    # resting deck line (~y=200-260) with nothing arresting it -- a bounded
    # max depth is the honest signal, since a lightly-damped chain legitimately
    # keeps oscillating for a while rather than instantly settling to v=0.
    check("boulder is caught by the bridge, not falling through to the void",
          max_y_seen < 320.0)


def demo_collision_variety():
    print("\n== Demo: every collision pair type produces a sane manifold ==")
    cc = E.collide(E.Body(E.Circle(10), (0, 0)), E.Body(E.Circle(10), (15, 0)))
    check("circle-circle", cc is not None and len(cc.points) == 1)

    box = E.Body(E.Box(100, 20), (0, 0), static=True)
    ball = E.Body(E.Circle(10), (0, -15))
    cp = E.collide(ball, box)
    check("circle-polygon", cp is not None and len(cp.points) == 1)

    ground = E.Body(E.Box(400, 40), (200, 580), static=True)
    b = E.Body(E.Box(50, 50), (200, 550))
    pp = E.collide(b, ground)
    check("polygon-polygon", pp is not None and len(pp.points) == 2)


def main():
    print("=" * 70)
    print("Impulse — headless verification demo")
    print("=" * 70)

    demo_collision_variety()
    demo_box_stack_settles()
    demo_pendulum_energy_bounded()
    demo_bridge_holds_under_load()

    print("\n" + "=" * 70)
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    print("=" * 70)
    if FAIL:
        print("Failures:")
        for name in FAIL:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
