(function () {
  'use strict';

  const T = window.Torque;
  const Vec2 = T.Vec2;

  const canvas = document.getElementById('canvas');
  const ctx = canvas.getContext('2d');

  // ---- world setup -------------------------------------------------

  const WORLD_WIDTH = 22; // world units spanned by the play area, walls included
  const WORLD_HEIGHT = 14;
  const GROUND_THICKNESS = 1;

  const world = new T.World({ gravity: new Vec2(0, -10) });
  let ground, leftWall, rightWall, ceiling;

  function buildEnclosure() {
    ground = world.addBody(new T.Body(T.box(WORLD_WIDTH, GROUND_THICKNESS), {
      position: new Vec2(0, -GROUND_THICKNESS / 2),
      isStatic: true,
      friction: 0.6,
    }));
    leftWall = world.addBody(new T.Body(T.box(GROUND_THICKNESS, WORLD_HEIGHT * 2), {
      position: new Vec2(-WORLD_WIDTH / 2 - GROUND_THICKNESS / 2, WORLD_HEIGHT),
      isStatic: true,
      friction: 0.3,
    }));
    rightWall = world.addBody(new T.Body(T.box(GROUND_THICKNESS, WORLD_HEIGHT * 2), {
      position: new Vec2(WORLD_WIDTH / 2 + GROUND_THICKNESS / 2, WORLD_HEIGHT),
      isStatic: true,
      friction: 0.3,
    }));
  }
  buildEnclosure();

  // ---- camera: world (y-up, origin at ground center) <-> screen ----

  const camera = { scale: 40, offsetX: 0, offsetY: 0 };

  function resizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = Math.max(1, Math.floor(rect.width * dpr));
    canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    camera.scale = Math.min(rect.width / WORLD_WIDTH, rect.height / (WORLD_HEIGHT * 1.15));
    camera.offsetX = rect.width / 2;
    camera.offsetY = rect.height - 24; // small margin below the ground line
  }

  function worldToScreen(p) {
    return { x: camera.offsetX + p.x * camera.scale, y: camera.offsetY - p.y * camera.scale };
  }

  function screenToWorld(x, y) {
    return new Vec2((x - camera.offsetX) / camera.scale, (camera.offsetY - y) / camera.scale);
  }

  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  // ---- spawning ------------------------------------------------------

  const PALETTE = ['#5eead4', '#60a5fa', '#f472b6', '#facc15', '#a78bfa', '#fb923c', '#4ade80'];
  let paletteIndex = 0;
  function nextColor() {
    const c = PALETTE[paletteIndex % PALETTE.length];
    paletteIndex++;
    return c;
  }

  const materials = { restitution: 0.3, friction: 0.4 };

  function makeShape(kind, size) {
    switch (kind) {
      case 'circle':
        return new T.Circle(size);
      case 'box':
        return T.box(size * 1.7, size * 1.7);
      case 'triangle':
        return new T.Polygon([
          new Vec2(-size, -size * 0.6),
          new Vec2(size, -size * 0.6),
          new Vec2(0, size * 0.9),
        ]);
      case 'pentagon':
        return T.regularPolygon(5, size);
      default:
        throw new Error('unknown shape kind: ' + kind);
    }
  }

  function spawn(kind, position, opts) {
    opts = opts || {};
    const size = opts.size !== undefined ? opts.size : 0.5;
    const shape = opts.shape || makeShape(kind, size);
    const body = new T.Body(shape, {
      position: position.clone(),
      angle: opts.angle || 0,
      density: 1,
      restitution: opts.restitution !== undefined ? opts.restitution : materials.restitution,
      friction: opts.friction !== undefined ? opts.friction : materials.friction,
      isStatic: !!opts.isStatic,
      userData: { color: opts.color || nextColor() },
    });
    world.addBody(body);
    return body;
  }

  function clearWorld() {
    stopDrag();
    world.clear();
    buildEnclosure();
  }

  // ---- presets ---------------------------------------------------------

  function presetStack() {
    clearWorld();
    const n = 6;
    for (let i = 0; i < n; i++) {
      spawn('box', new Vec2((Math.random() - 0.5) * 0.05, 0.5 + i * 1.02), { size: 0.5, restitution: 0.1 });
    }
  }

  function presetCradle() {
    clearWorld();
    const n = 5;
    const r = 0.5;
    const railY = 6;
    const startX = -((n - 1) * r);
    const rail = world.addBody(new T.Body(T.box(0.3, 0.3), { position: new Vec2(0, railY), isStatic: true }));
    let firstBall = null;
    for (let i = 0; i < n; i++) {
      const x = startX + i * (2 * r);
      const ball = spawn('circle', new Vec2(x, railY - 3), { size: r, restitution: 0.98, friction: 0.05 });
      world.addJoint(new T.DistanceJoint(rail, ball, new Vec2(x, railY), new Vec2(0, 0)));
      if (i === 0) firstBall = ball;
    }
    // pull the first ball out to the side to start the cradle swinging
    firstBall.position.x -= 2.2;
    firstBall.position.y += 0.05;
  }

  function presetPendulum() {
    clearWorld();
    // a DistanceJoint (fixed-length rod) between the pivot and the bob's
    // own center -- a RevoluteJoint pinned at the pivot's position would
    // instead rigidly coincide the pivot with whatever point on the bob
    // was 4 units from its center, which is a valid constraint but not
    // what "a ball on a string" means visually or physically here.
    const anchor = world.addBody(new T.Body(new T.Circle(0.15), { position: new Vec2(0, 9), isStatic: true }));
    const bob = spawn('circle', new Vec2(4, 9), { size: 0.6, restitution: 0.6, friction: 0.2 });
    world.addJoint(new T.DistanceJoint(anchor, bob, new Vec2(0, 0), new Vec2(0, 0)));
  }

  function presetChain() {
    clearWorld();
    const anchor = world.addBody(new T.Body(new T.Circle(0.1), { position: new Vec2(-4, 10), isStatic: true }));
    let prev = anchor;
    const linkW = 0.9;
    for (let i = 0; i < 8; i++) {
      const x = -4 + linkW * (i + 0.5);
      const link = spawn('box', new Vec2(x, 10), {
        shape: T.box(linkW, 0.25),
        restitution: 0.1,
        friction: 0.3,
      });
      world.addJoint(new T.RevoluteJoint(prev, link, new Vec2(-4 + linkW * i, 10)));
      prev = link;
    }
  }

  function presetDominoes() {
    clearWorld();
    const n = 10;
    const spacing = 0.9;
    const startX = -((n - 1) * spacing) / 2;
    for (let i = 0; i < n; i++) {
      const b = world.addBody(new T.Body(T.box(0.18, 1.1), {
        position: new Vec2(startX + i * spacing, 0.55),
        density: 1,
        friction: 0.5,
        restitution: 0.05,
        userData: { color: nextColor() },
      }));
      if (i === 0) {
        // negative: tips the top toward +x, into the row (Vec2.rotate is
        // CCW-positive, which would tip this one away from the others)
        b.angle = -0.35;
        b.angularVelocity = -1.5;
      }
    }
  }

  const PRESETS = {
    stack: presetStack,
    cradle: presetCradle,
    pendulum: presetPendulum,
    chain: presetChain,
    dominoes: presetDominoes,
  };

  // ---- pointer interaction: spawn on click, drag to grab -------------

  let selectedTool = 'circle';
  let dragBody = null;
  let dragMouseBody = null;
  let dragJoint = null;
  let dragLocalAnchor = null;
  let pointerDownPos = null;
  let pointerMoved = false;

  function pointInBody(body, worldPoint) {
    if (body.shape.type === 'circle') {
      return Vec2.distance(body.position, worldPoint) <= body.shape.radius;
    }
    const local = Vec2.rotate(Vec2.sub(worldPoint, body.position), -body.angle);
    const verts = body.shape.vertices;
    const normals = body.shape.normals;
    for (let i = 0; i < normals.length; i++) {
      if (Vec2.dot(normals[i], Vec2.sub(local, verts[i])) > 0) return false;
    }
    return true;
  }

  function hitTest(worldPoint) {
    for (let i = world.bodies.length - 1; i >= 0; i--) {
      const b = world.bodies[i];
      if (b.isStatic) continue;
      if (pointInBody(b, worldPoint)) return b;
    }
    return null;
  }

  function startDrag(body, worldPoint) {
    body.setAwake(true);
    dragBody = body;
    dragLocalAnchor = Vec2.rotate(Vec2.sub(worldPoint, body.position), -body.angle);
    dragMouseBody = new T.Body(new T.Circle(0.05), { position: worldPoint.clone(), isStatic: true });
    dragJoint = new T.RevoluteJoint(dragMouseBody, body, worldPoint);
    world.addJoint(dragJoint);
  }

  function updateDrag(worldPoint) {
    if (dragMouseBody) dragMouseBody.position = worldPoint.clone();
    if (dragBody && dragBody.isSleeping) dragBody.setAwake(true);
  }

  function stopDrag() {
    if (dragJoint) world.removeJoint(dragJoint);
    dragBody = null;
    dragMouseBody = null;
    dragJoint = null;
    dragLocalAnchor = null;
  }

  canvas.addEventListener('pointerdown', (e) => {
    const rect = canvas.getBoundingClientRect();
    const worldPoint = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
    pointerDownPos = worldPoint;
    pointerMoved = false;
    const hit = hitTest(worldPoint);
    if (hit) {
      startDrag(hit, worldPoint);
      canvas.setPointerCapture(e.pointerId);
    }
  });

  canvas.addEventListener('pointermove', (e) => {
    if (!pointerDownPos) return;
    const rect = canvas.getBoundingClientRect();
    const worldPoint = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
    if (Vec2.distance(worldPoint, pointerDownPos) > 0.08) pointerMoved = true;
    if (dragBody) updateDrag(worldPoint);
  });

  canvas.addEventListener('pointerup', (e) => {
    const rect = canvas.getBoundingClientRect();
    const worldPoint = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
    if (dragBody) {
      stopDrag();
    } else if (pointerDownPos && !pointerMoved) {
      const clamped = new Vec2(
        Math.max(-WORLD_WIDTH / 2 + 0.6, Math.min(WORLD_WIDTH / 2 - 0.6, worldPoint.x)),
        Math.max(0.6, Math.min(WORLD_HEIGHT * 1.8, worldPoint.y))
      );
      spawn(selectedTool, clamped);
    }
    pointerDownPos = null;
    pointerMoved = false;
  });

  canvas.addEventListener('pointercancel', stopDrag);

  // ---- controls --------------------------------------------------------

  document.querySelectorAll('[data-spawn]').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-spawn]').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      selectedTool = btn.getAttribute('data-spawn');
    });
  });

  document.querySelectorAll('[data-preset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const fn = PRESETS[btn.getAttribute('data-preset')];
      if (fn) fn();
    });
  });

  const restitutionInput = document.getElementById('restitution');
  const frictionInput = document.getElementById('friction');
  const gravityInput = document.getElementById('gravity');
  const valRestitution = document.getElementById('val-restitution');
  const valFriction = document.getElementById('val-friction');
  const valGravity = document.getElementById('val-gravity');

  restitutionInput.addEventListener('input', () => {
    materials.restitution = parseFloat(restitutionInput.value);
    valRestitution.textContent = materials.restitution.toFixed(2);
  });
  frictionInput.addEventListener('input', () => {
    materials.friction = parseFloat(frictionInput.value);
    valFriction.textContent = materials.friction.toFixed(2);
  });
  gravityInput.addEventListener('input', () => {
    const g = parseFloat(gravityInput.value);
    world.gravity.y = g;
    valGravity.textContent = g.toFixed(1);
  });

  let running = true;
  const btnPause = document.getElementById('btn-pause');
  btnPause.addEventListener('click', () => {
    running = !running;
    btnPause.textContent = running ? 'Pause' : 'Resume';
    btnPause.classList.toggle('paused', !running);
  });
  document.getElementById('btn-step').addEventListener('click', () => {
    world.step(1 / 120);
  });
  document.getElementById('btn-clear').addEventListener('click', clearWorld);

  let showDebug = false;
  document.getElementById('show-debug').addEventListener('change', (e) => {
    showDebug = e.target.checked;
  });

  // ---- render ------------------------------------------------------

  function drawBody(body) {
    const p = worldToScreen(body.position);
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(-body.angle);

    const color = (body.userData && body.userData.color) || '#94a3b8';
    ctx.fillStyle = body.isSleeping ? dim(color, 0.45) : color;
    ctx.strokeStyle = 'rgba(0,0,0,0.4)';
    ctx.lineWidth = 1.5;

    if (body.shape.type === 'circle') {
      const r = body.shape.radius * camera.scale;
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      // a spoke so rotation is visible
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(r, 0);
      ctx.strokeStyle = 'rgba(0,0,0,0.5)';
      ctx.stroke();
    } else {
      const verts = body.shape.vertices;
      ctx.beginPath();
      ctx.moveTo(verts[0].x * camera.scale, -verts[0].y * camera.scale);
      for (let i = 1; i < verts.length; i++) {
        ctx.lineTo(verts[i].x * camera.scale, -verts[i].y * camera.scale);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  function dim(hex, factor) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgb(${Math.round(r * factor)}, ${Math.round(g * factor)}, ${Math.round(b * factor)})`;
  }

  function drawJoint(joint) {
    const pA = Vec2.add(joint.bodyA.position, Vec2.rotate(joint.localAnchorA, joint.bodyA.angle));
    const pB = Vec2.add(joint.bodyB.position, Vec2.rotate(joint.localAnchorB, joint.bodyB.angle));
    const sA = worldToScreen(pA);
    const sB = worldToScreen(pB);
    ctx.strokeStyle = '#64748b';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(sA.x, sA.y);
    ctx.lineTo(sB.x, sB.y);
    ctx.stroke();
  }

  function render() {
    const rect = canvas.getBoundingClientRect();
    const grad = ctx.createLinearGradient(0, 0, 0, rect.height);
    grad.addColorStop(0, getCss('--canvas-bg-top'));
    grad.addColorStop(1, getCss('--canvas-bg-bottom'));
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, rect.width, rect.height);

    // ground line
    const groundTop = worldToScreen(new Vec2(0, 0));
    ctx.strokeStyle = getCss('--ground');
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, groundTop.y);
    ctx.lineTo(rect.width, groundTop.y);
    ctx.stroke();

    for (let i = 0; i < world.joints.length; i++) drawJoint(world.joints[i]);

    for (let i = 0; i < world.bodies.length; i++) {
      const b = world.bodies[i];
      if (b === ground || b === leftWall || b === rightWall) continue;
      drawBody(b);
    }

    if (dragBody && dragMouseBody) {
      const s = worldToScreen(dragMouseBody.position);
      ctx.fillStyle = '#f8fafc';
      ctx.beginPath();
      ctx.arc(s.x, s.y, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    if (showDebug) {
      ctx.fillStyle = '#f87171';
      for (let i = 0; i < world.contacts.length; i++) {
        const con = world.contacts[i];
        for (let j = 0; j < con.points.length; j++) {
          const s = worldToScreen(con.points[j].point);
          ctx.beginPath();
          ctx.arc(s.x, s.y, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }

  function getCss(varName) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  }

  // ---- fixed-step loop with a real-time accumulator ------------------

  const FIXED_DT = 1 / 120;
  const MAX_SUBSTEPS = 5;
  let accumulator = 0;
  let lastTime = performance.now();
  let fpsFrames = 0;
  let fpsLastSample = lastTime;

  const statBodies = document.getElementById('stat-bodies');
  const statSleeping = document.getElementById('stat-sleeping');
  const statFps = document.getElementById('stat-fps');

  function tick(now) {
    requestAnimationFrame(tick);
    let dt = (now - lastTime) / 1000;
    lastTime = now;
    if (dt > 0.25) dt = 0.25; // clamp huge hitches (tab backgrounded, debugger pause)

    if (running) {
      accumulator += dt;
      let steps = 0;
      while (accumulator >= FIXED_DT && steps < MAX_SUBSTEPS) {
        world.step(FIXED_DT);
        accumulator -= FIXED_DT;
        steps++;
      }
      if (steps === MAX_SUBSTEPS) accumulator = 0; // avoid a death spiral on a slow device
    }

    render();

    fpsFrames++;
    if (now - fpsLastSample > 400) {
      const fps = Math.round((fpsFrames * 1000) / (now - fpsLastSample));
      statFps.textContent = fps + ' fps';
      fpsFrames = 0;
      fpsLastSample = now;
    }
    let asleep = 0;
    for (let i = 0; i < world.bodies.length; i++) if (world.bodies[i].isSleeping) asleep++;
    statBodies.textContent = world.bodies.length + ' bodies';
    statSleeping.textContent = asleep + ' asleep';
  }

  presetStack();
  requestAnimationFrame(tick);

  window.__torqueDebug = { world: world, worldToScreen: worldToScreen };
})();
