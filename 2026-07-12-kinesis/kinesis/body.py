"""Expands a Genome into a phenotype: a list of RigidBody segments and
RevoluteJoint connections, positioned by forward kinematics so every
joint's anchor points exactly coincide in the creature's rest pose (so
the physics solver starts from zero constraint error), plus a list of
JointBinding records the controller uses to drive each joint's motor
target from its CPG each simulation tick.

``mirror`` on a genome node produces a second attached copy at the same
attach point on the opposite face of the parent (attach_side flipped,
rest_angle flipped), with its CPG phase shifted by pi -- the standard
way a 2D sagittal-plane creature encodes an alternating limb pair
without true left/right 3D geometry.
"""
import math
from . import vecmath as vm
from .physics import RigidBody, RevoluteJoint

DENSITY = 1.3
GROUND_CLEARANCE = 0.03
ALPHA_TARGET = 130.0  # rad/s^2 of angular acceleration a joint's motor can deliver, size-independent


class JointBinding:
    __slots__ = ("joint", "cpg", "phase_shift")

    def __init__(self, joint, cpg, phase_shift):
        self.joint = joint
        self.cpg = cpg
        self.phase_shift = phase_shift


class Phenotype:
    def __init__(self, bodies, joints, bindings, root_body):
        self.bodies = bodies
        self.joints = joints
        self.bindings = bindings
        self.root_body = root_body

    def update_controller(self, base_freq, t):
        for b in self.bindings:
            b.joint.target_angle = b.joint.rest_angle + b.cpg.target_angle(
                base_freq, t, b.phase_shift
            )


def build_phenotype(genome):
    bodies = []
    joints = []
    bindings = []

    def make_body(length, width, pos, angle):
        mass = DENSITY * length * width
        inertia = mass * (length * length + width * width) / 12.0
        b = RigidBody(mass, inertia, length / 2.0, width / 2.0, pos, angle)
        bodies.append(b)
        return b

    root_body = make_body(genome.root.length, genome.root.width, (0.0, 0.0), 0.0)

    def attach(node, parent_body, mirror):
        sign = -1.0 if mirror else 1.0
        anchor_local_parent = (node.attach_t * parent_body.hl, node.attach_side * sign * parent_body.hw)
        world_anchor = parent_body.local_to_world(anchor_local_parent)
        rest_angle = node.rest_angle * sign
        child_world_angle = parent_body.angle + rest_angle
        child_hl = node.length / 2.0
        anchor_local_child = (-child_hl, 0.0)
        offset = vm.rotate(anchor_local_child, child_world_angle)
        child_pos = vm.sub(world_anchor, offset)
        child_body = make_body(node.length, node.width, child_pos, child_world_angle)

        # Motor torque is scaled to the child segment's own moment of
        # inertia (torque = ALPHA_TARGET * inertia) rather than a single
        # global constant. Body plans span a wide size range (LEN_RANGE /
        # WID_RANGE differ up to ~4x), and inertia falls off with the
        # square of length -- a fixed torque cap gives tiny limbs an
        # effectively enormous angular acceleration (alpha = torque / I),
        # which let evolution "win" by discovering high-frequency
        # limb-spinning launches instead of real gaits.
        max_torque = ALPHA_TARGET * child_body.inertia
        joint = RevoluteJoint(parent_body, child_body, anchor_local_parent,
                               anchor_local_child, rest_angle, node.limit_span,
                               max_motor_torque=max_torque)
        joints.append(joint)
        bindings.append(JointBinding(joint, node.cpg, math.pi if mirror else 0.0))

        for grandchild in node.children:
            attach(grandchild, child_body, mirror=False)
            if grandchild.mirror:
                attach(grandchild, child_body, mirror=True)

    for child in genome.root.children:
        attach(child, root_body, mirror=False)
        if child.mirror:
            attach(child, root_body, mirror=True)

    _lift_above_ground(bodies)
    return Phenotype(bodies, joints, bindings, root_body)


def _lift_above_ground(bodies):
    min_y = min(c[1] for body in bodies for c in body.corners())
    shift = GROUND_CLEARANCE - min_y
    if shift == 0.0:
        return
    for body in bodies:
        body.pos = (body.pos[0], body.pos[1] + shift)
