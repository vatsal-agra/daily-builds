# Murmur
Flocking laboratory (JavaScript, no dependencies). **Status: Phase 4 — stretch features (GA tuner, snapshot replay, browser UI) + polish done.**

Done: seeded boids engine with grid spatial hash (== brute force), metric/topological neighbourhoods, order-parameter instruments + noise sweep + density comparison CLI, predators and obstacles.

    node murmur.js help
    node --test test/engine.test.js

See PLAN.md. Full docs arrive in the final phase.

Open `index.html` in a browser for the live UI. `node murmur.js tune` runs the genetic tuner.
