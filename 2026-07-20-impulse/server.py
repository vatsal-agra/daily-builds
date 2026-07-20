#!/usr/bin/env python3
"""
Impulse sandbox server.

stdlib-only HTTP backend. Runs the physics World on a fixed-timestep
background thread, streams live state to the browser over Server-Sent
Events, and accepts small REST commands (spawn a shape, drag a body,
change gravity/restitution/friction, pause/step/reset, load/save scenes).

The browser never simulates physics — engine.World is the single source
of truth, driven headlessly here and by the test suite identically.
"""

import json
import os
import sys
import threading
import time
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
SCENES_DIR = os.path.join(HERE, "scenes")

CANVAS_W = 900
CANVAS_H = 600
WALL_THICKNESS = 40
STEP_DT = 1.0 / 120.0
BROADCAST_HZ = 60.0

MIN_RADIUS, MAX_RADIUS = 6, 60
MIN_SIZE, MAX_SIZE = 10, 140
GRAB_RADIUS = 400  # how far the mouse can "reach" to grab a body (px)


class SimState:
    """All mutable simulation state, guarded by one lock. Simple and
    correct beats fine-grained locking for a sandbox this size."""

    def __init__(self):
        self.lock = threading.RLock()
        self.world = E.World(gravity=(0.0, 520.0))
        self.paused = False
        self.single_step = False
        self.debug = False
        self.spawn_defaults = {"restitution": 0.3, "friction": 0.4, "density": 1.0}
        self.mouse_joint = None
        self.mouse_grabbed_body = None
        self.version = 0
        self.condition = threading.Condition(self.lock)
        self.build_room()

    def build_room(self):
        self.world.clear()
        self.mouse_joint = None
        self.mouse_grabbed_body = None
        floor = E.Body(E.Box(CANVAS_W + 200, WALL_THICKNESS),
                        (CANVAS_W / 2, CANVAS_H + WALL_THICKNESS / 2 - 2),
                        static=True, friction=0.6, restitution=0.1, name="floor")
        left = E.Body(E.Box(WALL_THICKNESS, CANVAS_H * 4),
                       (-WALL_THICKNESS / 2 + 2, CANVAS_H / 2),
                       static=True, friction=0.3, restitution=0.2, name="left_wall")
        right = E.Body(E.Box(WALL_THICKNESS, CANVAS_H * 4),
                        (CANVAS_W + WALL_THICKNESS / 2 - 2, CANVAS_H / 2),
                        static=True, friction=0.3, restitution=0.2, name="right_wall")
        for b in (floor, left, right):
            self.world.add_body(b)

    def bump_version(self):
        self.version += 1
        self.condition.notify_all()


STATE = SimState()


# --------------------------------------------------------------------------
# Physics thread
# --------------------------------------------------------------------------

def physics_loop():
    last = time.monotonic()
    accumulator = 0.0
    last_broadcast = 0.0
    broadcast_period = 1.0 / BROADCAST_HZ
    while True:
        now = time.monotonic()
        frame_dt = now - last
        last = now
        # clamp to avoid spiral-of-death on hiccups (e.g. debugger pause)
        frame_dt = min(frame_dt, 0.1)
        accumulator += frame_dt

        with STATE.lock:
            if STATE.paused and not STATE.single_step:
                accumulator = 0.0
            else:
                steps_taken = 0
                while accumulator >= STEP_DT and steps_taken < 8:
                    STATE.world.step(STEP_DT)
                    accumulator -= STEP_DT
                    steps_taken += 1
                    if STATE.single_step:
                        STATE.single_step = False
                        accumulator = 0.0
                        break
                # despawn anything that has flown absurdly far off-scene
                _cull_stray_bodies()

        if now - last_broadcast >= broadcast_period:
            last_broadcast = now
            with STATE.lock:
                STATE.bump_version()

        time.sleep(0.002)


def _cull_stray_bodies():
    world = STATE.world
    stray = [b for b in world.bodies
             if not b.static and (b.position.y > CANVAS_H * 6 or abs(b.position.x) > CANVAS_W * 6)]
    for b in stray:
        world.remove_body(b)
        if STATE.mouse_grabbed_body is b:
            _release_mouse_locked()


def _release_mouse_locked():
    if STATE.mouse_joint is not None and STATE.mouse_joint in STATE.world.joints:
        STATE.world.joints.remove(STATE.mouse_joint)
    STATE.mouse_joint = None
    STATE.mouse_grabbed_body = None


# --------------------------------------------------------------------------
# Scene helpers
# --------------------------------------------------------------------------

def body_from_dict(d):
    if d["shape"] == "circle":
        shape = E.Circle(d["radius"])
    else:
        shape = E.Polygon([E.Vec2(x, y) for x, y in d["vertices"]])
    body = E.Body(shape, (d["x"], d["y"]), angle=d.get("angle", 0.0),
                  restitution=d.get("restitution", 0.3), friction=d.get("friction", 0.4),
                  static=d.get("static", False), density=d.get("density", 1.0),
                  name=d.get("name"))
    return body


def export_scene():
    with STATE.lock:
        world = STATE.world
        return {
            "gravity": [world.gravity.x, world.gravity.y],
            "bodies": [b.to_dict() | {"density": (b.mass / _area_of(b.shape)) if not b.static and _area_of(b.shape) > 0 else 1.0}
                       for b in world.bodies if b.name not in ("floor", "left_wall", "right_wall")],
        }


def _area_of(shape):
    if shape.kind == "circle":
        return 3.141592653589793 * shape.radius ** 2
    m, _ = shape.mass_data(1.0)
    return m


def import_scene(data):
    with STATE.lock:
        STATE.build_room()
        STATE.paused = False
        STATE.single_step = False
        if "gravity" in data:
            STATE.world.gravity = E.Vec2(*data["gravity"])
        for bd in data.get("bodies", []):
            STATE.world.add_body(body_from_dict(bd))
        STATE.bump_version()


PRESET_SCENES = {}


def _register_presets():
    def pyramid():
        bodies = []
        rows = 6
        size = 40
        base_x = CANVAS_W / 2
        base_y = CANVAS_H - 4
        for row in range(rows):
            n = rows - row
            y = base_y - (row + 0.5) * size
            start_x = base_x - (n * size) / 2
            for i in range(n):
                x = start_x + (i + 0.5) * size
                bodies.append({"shape": "box", "x": x, "y": y, "w": size - 2, "h": size - 2,
                               "restitution": 0.05, "friction": 0.7})
        return {"gravity": [0, 520], "bodies": bodies}

    def bridge():
        bodies = []
        joints = []
        n = 12
        span = 500
        start_x = (CANVAS_W - span) / 2
        y = 220
        plank_w = span / n
        anchors = []
        for i in range(n):
            x = start_x + (i + 0.5) * plank_w
            bodies.append({"shape": "box", "x": x, "y": y, "w": plank_w * 0.95, "h": 16,
                           "restitution": 0.05, "friction": 0.8, "density": 0.6})
            anchors.append((x, y))
        return {"gravity": [0, 520], "bodies": bodies, "chain": True,
                "chain_span": span, "chain_start_x": start_x, "chain_y": y, "chain_n": n,
                "chain_plank_w": plank_w}

    def stack():
        bodies = []
        for i in range(8):
            bodies.append({"shape": "circle", "x": CANVAS_W / 2 + (5 if i % 2 else -5),
                           "y": CANVAS_H - 30 - i * 42, "radius": 20,
                           "restitution": 0.3, "friction": 0.3})
        return {"gravity": [0, 520], "bodies": bodies}

    def cradle():
        import math
        bodies = []
        n = 5
        r = 22
        spacing = r * 2
        start_x = CANVAS_W / 2 - (n * spacing) / 2
        y_top = 120
        length = 200
        pull_angle = math.radians(45)
        strings = []
        for i in range(n):
            pivot_x = start_x + i * spacing + r
            if i == 0:
                # pull the first ball back and up so it swings in and strikes the rest
                x = pivot_x - length * math.sin(pull_angle)
                y = y_top + length * math.cos(pull_angle)
            else:
                x = pivot_x
                y = y_top + length
            bodies.append({"shape": "circle", "x": x, "y": y, "radius": r,
                           "restitution": 0.98, "friction": 0.02, "density": 1.0,
                           "linear_damping": 0.0})
            strings.append({"body": i, "world": [pivot_x, y_top], "length": length})
        return {"gravity": [0, 520], "bodies": bodies, "strings": strings}

    PRESET_SCENES["pyramid"] = pyramid
    PRESET_SCENES["bridge"] = bridge
    PRESET_SCENES["stack"] = stack
    PRESET_SCENES["cradle"] = cradle


_register_presets()


def load_preset(name):
    if name not in PRESET_SCENES:
        raise KeyError(name)
    data = PRESET_SCENES[name]()
    with STATE.lock:
        STATE.build_room()
        STATE.paused = False
        STATE.single_step = False
        STATE.world.gravity = E.Vec2(*data["gravity"])
        made = []
        for bd in data["bodies"]:
            if bd["shape"] == "circle":
                shape = E.Circle(bd["radius"])
            else:
                shape = E.Polygon(E.box_vertices(bd["w"], bd["h"]))
            body = E.Body(shape, (bd["x"], bd["y"]),
                          restitution=bd.get("restitution", 0.3),
                          friction=bd.get("friction", 0.4),
                          density=bd.get("density", 1.0),
                          linear_damping=bd.get("linear_damping", 0.01),
                          angular_damping=bd.get("angular_damping", 0.01))
            STATE.world.add_body(body)
            made.append(body)

        if data.get("chain"):
            # connect adjacent planks with distance joints to form a rope bridge,
            # and pin the two ends to fixed world anchors.
            n = data["chain_n"]
            plank_w = data["chain_plank_w"]
            y = data["chain_y"]
            for i in range(n - 1):
                a, b = made[i], made[i + 1]
                STATE.world.add_joint(E.DistanceJoint(a, (plank_w * 0.45, 0), b, (-plank_w * 0.45, 0)))
            left_anchor = (data["chain_start_x"], y)
            right_anchor = (data["chain_start_x"] + data["chain_span"], y)
            STATE.world.add_joint(E.DistanceJoint(made[0], (-plank_w * 0.45, 0), None, left_anchor))
            STATE.world.add_joint(E.DistanceJoint(made[-1], (plank_w * 0.45, 0), None, right_anchor))

        if "strings" in data:
            for s in data["strings"]:
                body = made[s["body"]]
                STATE.world.add_joint(E.DistanceJoint(body, (0, 0), None, tuple(s["world"]), length=s["length"]))

        STATE.bump_version()


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "Impulse/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep stdout quiet; use --verbose flag pattern if needed later

    # ---- helpers ----
    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message, status=400):
        self._send_json({"error": message}, status=status)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("invalid JSON body")

    def _serve_static_file(self, rel_path):
        safe_path = os.path.normpath(os.path.join(STATIC_DIR, rel_path))
        if not safe_path.startswith(STATIC_DIR):
            self.send_error(403, "Forbidden")
            return
        if not os.path.isfile(safe_path):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(safe_path)[1]
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(safe_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- routing ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                self._serve_static_file("index.html")
            elif path.startswith("/static/"):
                self._serve_static_file(path[len("/static/"):])
            elif path == "/events":
                self._handle_sse()
            elif path == "/api/scenes":
                self._send_json({"scenes": sorted(PRESET_SCENES.keys())})
            elif path == "/api/scene/export":
                self._send_json(export_scene())
            elif path == "/api/state":
                with STATE.lock:
                    self._send_json(STATE.world.to_dict())
            else:
                self.send_error(404, "Not Found")
        except BrokenPipeError:
            pass

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
        except ValueError as e:
            self._send_error_json(str(e))
            return
        try:
            if path == "/api/spawn":
                self._handle_spawn(body)
            elif path == "/api/grab":
                self._handle_grab(body)
            elif path == "/api/drag":
                self._handle_drag(body)
            elif path == "/api/release":
                self._handle_release(body)
            elif path == "/api/reset":
                with STATE.lock:
                    STATE.build_room()
                    STATE.paused = False
                    STATE.single_step = False
                    STATE.bump_version()
                self._send_json({"ok": True})
            elif path == "/api/params":
                self._handle_params(body)
            elif path == "/api/pause":
                with STATE.lock:
                    STATE.paused = bool(body.get("paused", not STATE.paused))
                self._send_json({"paused": STATE.paused})
            elif path == "/api/step":
                with STATE.lock:
                    STATE.single_step = True
                    STATE.paused = True
                self._send_json({"ok": True})
            elif path == "/api/scene/load":
                name = body.get("name", "")
                try:
                    load_preset(name)
                    self._send_json({"ok": True})
                except KeyError:
                    self._send_error_json(f"unknown scene '{name}'", 404)
            elif path == "/api/scene/import":
                try:
                    import_scene(body)
                    self._send_json({"ok": True})
                except (KeyError, TypeError, ValueError) as e:
                    self._send_error_json(f"invalid scene: {e}")
            else:
                self.send_error(404, "Not Found")
        except BrokenPipeError:
            pass
        except Exception as e:  # last-resort guard so one bad request can't kill the server
            self._send_error_json(f"internal error: {e}", 500)

    # ---- SSE ----
    def _handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_seen = -1
        try:
            while True:
                with STATE.condition:
                    while STATE.version == last_seen:
                        STATE.condition.wait(timeout=1.0)
                    last_seen = STATE.version
                    state_dict = STATE.world.to_dict()
                    state_dict["paused"] = STATE.paused
                    payload = json.dumps(state_dict)
                chunk = f"data: {payload}\n\n".encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    # ---- command handlers ----
    def _handle_spawn(self, body):
        shape_kind = body.get("shape")
        try:
            x = float(body["x"])
            y = float(body["y"])
        except (KeyError, TypeError, ValueError):
            self._send_error_json("x and y are required numbers")
            return
        x = max(-200.0, min(CANVAS_W + 200.0, x))
        y = max(-200.0, min(CANVAS_H + 200.0, y))

        with STATE.lock:
            defaults = STATE.spawn_defaults
        restitution = _clamp_float(body.get("restitution", defaults["restitution"]), 0.0, 1.0)
        friction = _clamp_float(body.get("friction", defaults["friction"]), 0.0, 2.0)
        density = _clamp_float(body.get("density", defaults["density"]), 0.05, 20.0)

        try:
            if shape_kind == "circle":
                radius = _clamp_float(body.get("radius", 20), MIN_RADIUS, MAX_RADIUS)
                shape = E.Circle(radius)
            elif shape_kind == "box":
                w = _clamp_float(body.get("w", 40), MIN_SIZE, MAX_SIZE)
                h = _clamp_float(body.get("h", 40), MIN_SIZE, MAX_SIZE)
                shape = E.Box(w, h)
            else:
                self._send_error_json("shape must be 'circle' or 'box'")
                return
            new_body = E.Body(shape, (x, y), density=density,
                              restitution=restitution, friction=friction)
        except ValueError as e:
            self._send_error_json(str(e))
            return

        with STATE.lock:
            if len(STATE.world.bodies) > 400:
                self._send_error_json("too many bodies (limit 400) — reset the scene", 429)
                return
            STATE.world.add_body(new_body)
            STATE.bump_version()
        self._send_json({"ok": True})

    def _handle_grab(self, body):
        try:
            x, y = float(body["x"]), float(body["y"])
        except (KeyError, TypeError, ValueError):
            self._send_error_json("x and y are required")
            return
        with STATE.lock:
            _release_mouse_locked()
            world = STATE.world
            target = E.Vec2(x, y)
            best = None
            best_dist = GRAB_RADIUS
            for b in world.bodies:
                if b.static:
                    continue
                d = (b.position - target).length()
                r = b.shape.aabb_radius()
                margin = max(d - r, 0.0)
                if margin < best_dist:
                    best_dist = margin
                    best = b
            if best is None:
                self._send_json({"grabbed": False})
                return
            local_anchor = (target - best.position).rotated(-best.angle)
            k = max(best.mass, 1.0) * 550.0
            c = max(best.mass, 1.0) * 45.0
            joint = E.SpringJoint(best, (local_anchor.x, local_anchor.y), None,
                                  (x, y), rest_length=0.0, stiffness=k, damping=c)
            world.add_joint(joint)
            STATE.mouse_joint = joint
            STATE.mouse_grabbed_body = best
            self._send_json({"grabbed": True})

    def _handle_drag(self, body):
        try:
            x, y = float(body["x"]), float(body["y"])
        except (KeyError, TypeError, ValueError):
            self._send_error_json("x and y are required")
            return
        with STATE.lock:
            if STATE.mouse_joint is not None:
                STATE.mouse_joint.anchor_b_local = E.Vec2(x, y)
        self._send_json({"ok": True})

    def _handle_release(self, body):
        with STATE.lock:
            _release_mouse_locked()
        self._send_json({"ok": True})

    def _handle_params(self, body):
        with STATE.lock:
            if "gravity" in body:
                g = _clamp_float(body["gravity"], -2000.0, 2000.0)
                STATE.world.gravity = E.Vec2(0.0, g)
            if "restitution" in body:
                STATE.spawn_defaults["restitution"] = _clamp_float(body["restitution"], 0.0, 1.0)
            if "friction" in body:
                STATE.spawn_defaults["friction"] = _clamp_float(body["friction"], 0.0, 2.0)
        self._send_json({"ok": True})


def _clamp_float(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = lo
    if v != v:  # NaN guard
        v = lo
    return max(lo, min(hi, v))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    threading.Thread(target=physics_loop, daemon=True).start()
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Impulse sandbox running at http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
