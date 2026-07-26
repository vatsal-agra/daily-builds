"""A from-scratch 2D constraint-based rigid body engine: semi-implicit
Euler integration plus a sequential-impulse (Gauss-Seidel) solver for

  * revolute joints — a 2-row point-to-point position constraint so two
    bodies share a hinge point, a 1-row PD-servo motor constraint (target
    angle tracked via a velocity-level impulse, clamped to a max torque),
    and a 1-row one-sided angle-limit constraint,
  * ground contact — a half-plane at y=0, per-corner non-penetration with
    Coulomb friction,

with Baumgarte position-bias stabilization for constraint drift. This is
the same family of algorithm real 2D engines like Box2D use (Catto,
"Iterative Dynamics with Temporal Coherence", 2005); nothing here calls
into an external physics library.
"""
from . import vecmath as vm

GRAVITY = (0.0, -9.81)
BAUMGARTE = 0.2
SLOP = 0.005
SOLVER_ITERATIONS = 10
RESTITUTION = 0.0
FRICTION = 0.9
# Positional (Baumgarte) error is clamped before it is turned into a bias
# velocity. Without this, a single-frame transient (a limb snapping hard
# into its angle limit, a corner briefly tunneling into the ground) can
# produce a large separation `c`; multiplied by BAUMGARTE/dt (=48 at
# dt=1/240) that becomes an explosive velocity correction that then
# cascades through the rest of the joint chain on the next step. Real
# engines (Box2D's b2_maxLinearCorrection) clamp this for exactly this
# reason.
MAX_LINEAR_CORRECTION = 0.2
MAX_ANGULAR_CORRECTION = 0.2


def _clamp_len(vec, max_len):
    n = vm.length(vec)
    if n <= max_len or n < 1e-12:
        return vec
    return vm.scale(vec, max_len / n)


class RigidBody:
    __slots__ = ("mass", "inv_mass", "inertia", "inv_inertia", "hl", "hw",
                 "pos", "angle", "vel", "ang_vel", "name")

    def __init__(self, mass, inertia, half_length, half_width, pos, angle, name=""):
        self.mass = mass
        self.inertia = inertia
        self.inv_mass = 0.0 if mass <= 0 else 1.0 / mass
        self.inv_inertia = 0.0 if inertia <= 0 else 1.0 / inertia
        self.hl = half_length
        self.hw = half_width
        self.pos = pos
        self.angle = angle
        self.vel = (0.0, 0.0)
        self.ang_vel = 0.0
        self.name = name

    def local_to_world(self, local_pt):
        return vm.add(self.pos, vm.rotate(local_pt, self.angle))

    def corners(self):
        hl, hw = self.hl, self.hw
        pts = [(hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw)]
        return [self.local_to_world(p) for p in pts]

    def point_velocity(self, r_world_offset):
        return vm.add(self.vel, vm.cross_sv(self.ang_vel, r_world_offset))


class RevoluteJoint:
    """Connects body_a to body_b at anchor points given in each body's
    local frame. `rest_angle` is the neutral world angle-B minus angle-A
    at equilibrium; the motor tracks a target relative angle each step;
    `limit_span` bounds the relative angle to [rest-span, rest+span]."""

    def __init__(self, body_a, body_b, anchor_a, anchor_b, rest_angle,
                 limit_span, max_motor_torque=35.0, servo_kp=55.0):
        self.a = body_a
        self.b = body_b
        self.anchor_a = anchor_a
        self.anchor_b = anchor_b
        self.rest_angle = rest_angle
        self.limit_span = limit_span
        self.max_motor_torque = max_motor_torque
        self.servo_kp = servo_kp
        self.target_angle = rest_angle  # updated by the controller each step


def _solve_point2point(joint, dt):
    a, b = joint.a, joint.b
    ra = vm.rotate(joint.anchor_a, a.angle)
    rb = vm.rotate(joint.anchor_b, b.angle)
    world_a = vm.add(a.pos, ra)
    world_b = vm.add(b.pos, rb)

    k11 = a.inv_mass + b.inv_mass + a.inv_inertia * ra[1] * ra[1] + b.inv_inertia * rb[1] * rb[1]
    k12 = -a.inv_inertia * ra[0] * ra[1] - b.inv_inertia * rb[0] * rb[1]
    k22 = a.inv_mass + b.inv_mass + a.inv_inertia * ra[0] * ra[0] + b.inv_inertia * rb[0] * rb[0]
    det = k11 * k22 - k12 * k12
    if abs(det) < 1e-9:
        return
    inv_det = 1.0 / det

    cdot = vm.sub(b.point_velocity(rb), a.point_velocity(ra))
    c = _clamp_len(vm.sub(world_b, world_a), MAX_LINEAR_CORRECTION)
    bias = vm.scale(c, BAUMGARTE / dt)
    rhs = vm.add(cdot, bias)

    imp_x = -inv_det * (k22 * rhs[0] - k12 * rhs[1])
    imp_y = -inv_det * (-k12 * rhs[0] + k11 * rhs[1])
    impulse = (imp_x, imp_y)

    a.vel = vm.sub(a.vel, vm.scale(impulse, a.inv_mass))
    a.ang_vel -= a.inv_inertia * vm.cross(ra, impulse)
    b.vel = vm.add(b.vel, vm.scale(impulse, b.inv_mass))
    b.ang_vel += b.inv_inertia * vm.cross(rb, impulse)


def _solve_motor(joint, dt):
    a, b = joint.a, joint.b
    inv_i_sum = a.inv_inertia + b.inv_inertia
    if inv_i_sum <= 0:
        return 0.0
    rel_angle = b.angle - a.angle
    desired_rel_vel = joint.servo_kp * (joint.target_angle - rel_angle)
    cdot = (b.ang_vel - a.ang_vel) - desired_rel_vel
    impulse = -cdot / inv_i_sum
    max_impulse = joint.max_motor_torque * dt
    impulse = max(-max_impulse, min(max_impulse, impulse))
    a.ang_vel -= a.inv_inertia * impulse
    b.ang_vel += b.inv_inertia * impulse
    return impulse


def _solve_limit(joint, dt):
    a, b = joint.a, joint.b
    inv_i_sum = a.inv_inertia + b.inv_inertia
    if inv_i_sum <= 0:
        return
    rel_angle = b.angle - a.angle
    hi = joint.rest_angle + joint.limit_span
    lo = joint.rest_angle - joint.limit_span
    cdot = b.ang_vel - a.ang_vel
    if rel_angle > hi:
        c = min(rel_angle - hi, MAX_ANGULAR_CORRECTION)
        bias = BAUMGARTE / dt * c
        impulse = -(cdot + bias) / inv_i_sum
        impulse = min(impulse, 0.0)
        a.ang_vel -= a.inv_inertia * impulse
        b.ang_vel += b.inv_inertia * impulse
    elif rel_angle < lo:
        c = max(rel_angle - lo, -MAX_ANGULAR_CORRECTION)
        bias = BAUMGARTE / dt * c
        impulse = -(cdot + bias) / inv_i_sum
        impulse = max(impulse, 0.0)
        a.ang_vel -= a.inv_inertia * impulse
        b.ang_vel += b.inv_inertia * impulse


class Contact:
    __slots__ = ("body", "r", "penetration", "acc_normal")

    def __init__(self, body, r, penetration):
        self.body = body
        self.r = r
        self.penetration = penetration
        self.acc_normal = 0.0


def _gather_contacts(bodies, ground_y):
    contacts = []
    for body in bodies:
        for corner in body.corners():
            if corner[1] < ground_y:
                r = vm.sub(corner, body.pos)
                contacts.append(Contact(body, r, ground_y - corner[1]))
    return contacts


def _solve_contact(c, dt):
    body = c.body
    normal = (0.0, 1.0)
    tangent = (1.0, 0.0)
    r = c.r

    k_n = body.inv_mass + body.inv_inertia * (vm.cross(r, normal) ** 2)
    if k_n <= 0:
        return
    vp = body.point_velocity(r)
    vn = vm.dot(vp, normal)
    bias = BAUMGARTE / dt * min(max(0.0, c.penetration - SLOP), MAX_LINEAR_CORRECTION)
    restitution_term = -RESTITUTION * min(vn, 0.0) if vn < -0.5 else 0.0
    lam = -(vn - bias - restitution_term) / k_n
    new_acc = max(0.0, c.acc_normal + lam)
    lam = new_acc - c.acc_normal
    c.acc_normal = new_acc
    impulse_n = vm.scale(normal, lam)
    body.vel = vm.add(body.vel, vm.scale(impulse_n, body.inv_mass))
    body.ang_vel += body.inv_inertia * vm.cross(r, impulse_n)

    k_t = body.inv_mass + body.inv_inertia * (vm.cross(r, tangent) ** 2)
    if k_t <= 0:
        return
    vp = body.point_velocity(r)
    vt = vm.dot(vp, tangent)
    lam_t = -vt / k_t
    max_friction = FRICTION * c.acc_normal
    lam_t = max(-max_friction, min(max_friction, lam_t))
    impulse_t = vm.scale(tangent, lam_t)
    body.vel = vm.add(body.vel, vm.scale(impulse_t, body.inv_mass))
    body.ang_vel += body.inv_inertia * vm.cross(r, impulse_t)


class World:
    def __init__(self, bodies, joints, ground_y=0.0, gravity=GRAVITY):
        self.bodies = bodies
        self.joints = joints
        self.ground_y = ground_y
        self.gravity = gravity
        self.motor_energy = 0.0  # sum of |motor impulse| from each step's final GS pass

    def step(self, dt):
        for body in self.bodies:
            if body.inv_mass > 0:
                body.vel = vm.add(body.vel, vm.scale(self.gravity, dt))

        contacts = _gather_contacts(self.bodies, self.ground_y)

        for it in range(SOLVER_ITERATIONS):
            last = it == SOLVER_ITERATIONS - 1
            for joint in self.joints:
                impulse = _solve_motor(joint, dt)
                if last:
                    self.motor_energy += abs(impulse)
                _solve_limit(joint, dt)
                _solve_point2point(joint, dt)
            for c in contacts:
                _solve_contact(c, dt)

        for body in self.bodies:
            if body.inv_mass > 0:
                body.pos = vm.add(body.pos, vm.scale(body.vel, dt))
                body.angle += body.ang_vel * dt
