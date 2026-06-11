// DOM smoke test for the generated map HTML, run under jsdom.
// Usage: NODE_PATH=<dir with jsdom> node tests/dom_check.js <world.html>
"use strict";
const fs = require("fs");
const { JSDOM } = require("jsdom");

const path = process.argv[2];
if (!path) { console.error("usage: node dom_check.js <world.html>"); process.exit(2); }
const html = fs.readFileSync(path, "utf8");

const errors = [];
const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  beforeParse(window) {
    window.addEventListener("error", (e) => errors.push(e.message));
  },
});
const { window } = dom;
const { document } = window;

function fail(msg) { console.error("FAIL:", msg); process.exit(1); }
function ok(msg) { console.log("ok -", msg); }

if (errors.length) fail("script errors on load: " + errors.join("; "));
ok("inline script ran without errors");

const svg = document.getElementById("map");
if (!svg) fail("no #map svg");
const layers = ["biome", "elevation", "temperature", "moisture"].map((n) =>
  document.getElementById("layer-" + n)
);
if (layers.some((l) => !l)) fail("missing raster layer images");
if (layers[0].getAttribute("opacity") !== "1") fail("biome layer not visible by default");
ok("all four raster layers present, biome visible");

// Layer switching
const btn = document.querySelector('button[data-layer="temperature"]');
btn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
if (layers[2].getAttribute("opacity") !== "1" || layers[0].getAttribute("opacity") !== "0")
  fail("layer switch did not toggle opacities");
if (!btn.classList.contains("active")) fail("layer button active state");
ok("layer switcher toggles raster visibility");

// Pointer events must not throw in a DOM without PointerEvent/getScreenCTM
const wrap = document.getElementById("map-wrap");
for (const [type, opts] of [
  ["pointerdown", { clientX: 50, clientY: 50 }],
  ["pointermove", { clientX: 70, clientY: 60 }],
  ["pointerup", {}],
  ["wheel", { deltaY: -120, clientX: 50, clientY: 50 }],
]) {
  wrap.dispatchEvent(new window.MouseEvent(type, { bubbles: true, cancelable: true, ...opts }));
}
const vb = svg.getAttribute("viewBox");
if (!/^[-\d. ]+$/.test(vb) || vb.includes("NaN") || vb.includes("Infinity"))
  fail("viewBox corrupted after pointer events: " + vb);
ok("pointer/wheel events safe, viewBox sane: " + vb);

// Embedded data integrity
const meta = JSON.parse(html.match(/const META = (\{.*?\});\n/s)[1]);
const packed = JSON.parse(html.match(/const PACKED = (\{.*?\});\n/s)[1]);
const n = meta.width * meta.height;
for (const key of ["elev", "temp", "moist", "biome"]) {
  if (packed[key].length !== n * 2) fail(`packed ${key} length ${packed[key].length} != ${n * 2}`);
  if (!/^[0-9a-f]+$/.test(packed[key])) fail(`packed ${key} not hex`);
}
ok("packed inspector data: 4 fields, correct length, valid hex");

// Gazetteer fly-to (only when settlements exist)
const town = document.querySelector("#gazetteer .town");
if (town) {
  town.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  const vb2 = svg.getAttribute("viewBox").split(" ").map(Number);
  if (vb2.some((v) => !isFinite(v))) fail("fly-to produced bad viewBox");
  if (vb2[2] >= meta.width && meta.width > 40) fail("fly-to did not zoom in");
  ok("gazetteer fly-to zooms the viewBox");
} else {
  ok("no settlements in this map (gazetteer empty state present: " +
     !!document.querySelector("#gazetteer .empty") + ")");
}

console.log("DOM smoke test passed");
