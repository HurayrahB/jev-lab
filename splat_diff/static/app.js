// Splat Diff front end: load two splats, align B onto A (server), render matched views, send them to Jev (server).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  SparkRenderer, SplatEdit, SplatEditRgbaBlendMode, SplatEditSdf, SplatEditSdfType, SplatMesh,
} from "@sparkjsdev/spark";

const SIZE = 1024;          // render size sent to Jev (docs allow 280..1568 px per side)
const SAMPLE = 20000;       // splat centers sent to the server for alignment
const FOV = 40;
const VIEWS = [
  ...[0, 45, 90, 135, 180, 225, 270, 315].map((az) => ({ az, el: 10 })),
  ...[45, 135, 225, 315].map((az) => ({ az, el: 40 })),
];
const SIDES = { 0: "front", 45: "front-right", 90: "right", 135: "back-right", 180: "back", 225: "back-left", 270: "left", 315: "front-left" };
const viewLabel = (v) => `${SIDES[v.az]} (azimuth ${v.az}°), ${v.el}° above`;

const $ = (s) => document.querySelector(s);
const canvas = $("#view");
const renderer = new THREE.WebGLRenderer({ canvas, preserveDrawingBuffer: true, antialias: false });
renderer.setPixelRatio(1);
renderer.setSize(SIZE, SIZE, false);
renderer.setClearColor(0x808080);

const scene = new THREE.Scene();
const spark = new SparkRenderer({ renderer });
scene.add(spark);
const camera = new THREE.PerspectiveCamera(FOV, 1, 0.01, 1000);
const controls = new OrbitControls(camera, canvas);

// world: "which way is up" for the whole scene (most 3DGS .ply files are y-down, hence the X flip).
// Inside it, A sits in its own file coordinates and bHolder carries the B->A alignment matrix.
const world = new THREE.Group();
world.quaternion.set(1, 0, 0, 0);
scene.add(world);
const bHolder = new THREE.Group();
bHolder.matrixAutoUpdate = false;
world.add(bHolder);

// Crop: everything outside a sphere around the object fades to zero opacity.
const cropSdf = new SplatEditSdf({ type: SplatEditSdfType.SPHERE, radius: 1, opacity: 0 });
const cropEdit = new SplatEdit({ rgbaBlendMode: SplatEditRgbaBlendMode.MULTIPLY, invert: true, softEdge: 0.02 });
cropEdit.add(cropSdf); // must be in the scene graph, or its world matrix never updates
world.add(cropEdit);

const state = { a: null, b: null, align: null, matrix: new THREE.Matrix4(), mode: "blink", views: null, thresholds: {} };
window.splatDiff = { state, scene, world, camera, spark, cropEdit, cropSdf, THREE }; // for poking at it from devtools

// ---------- loading ----------
const pendingUrlLoads = [];
for (const drop of document.querySelectorAll(".drop")) {
  const input = drop.querySelector("input");
  const side = drop.dataset.side;
  input.addEventListener("change", () => input.files[0] && load(side, input.files[0]));
  const fromUrl = new URLSearchParams(location.search).get(side); // ?a=nike/nike_reference.ply
  if (fromUrl) {
    pendingUrlLoads.push(fetch(`/data/${fromUrl}`).then((r) => {
      if (!r.ok) throw new Error(`data/${fromUrl}: ${r.status}`);
      return r.blob();
    }).then((blob) => new File([blob], fromUrl.split("/").pop())).then((file) => [side, file]));
  }
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault(); drop.classList.remove("over");
    if (e.dataTransfer.files[0]) load(side, e.dataTransfer.files[0]);
  });
}

async function load(side, file) {
  busy(`Loading ${file.name}…`);
  try {
    const mesh = new SplatMesh({ fileBytes: await file.arrayBuffer(), fileName: file.name });
    await mesh.initialized;
    const old = state[side];
    if (old) { old.mesh.parent.remove(old.mesh); old.mesh.dispose?.(); }
    (side === "a" ? world : bHolder).add(mesh);
    state[side] = { mesh, name: file.name, sample: sampleSplats(mesh) };
    document.querySelector(`.drop[data-side=${side}] small`).textContent =
      `${file.name} · ${state[side].sample.total.toLocaleString()} splats`;
    state.views = null;
    if (state.a && state.b) await runAlign();
    else frameCamera(boundsOf(mesh));
  } catch (e) {
    showError(`Could not load ${file.name}: ${e.message}`);
  }
  busy(null);
  refresh();
}

function sampleSplats(mesh) {
  const total = mesh.packedSplats?.numSplats ?? mesh.numSplats ?? 0;
  const stride = Math.max(1, Math.floor(total / SAMPLE));
  const points = [], opacity = [], scale = [];
  mesh.forEachSplat((i, center, scales, _q, alpha) => {
    if (i % stride) return;
    points.push([center.x, center.y, center.z]);
    opacity.push(alpha);
    scale.push(Math.max(scales.x, scales.y, scales.z));
  });
  return { points, opacity, scale, total: total || points.length * stride };
}

function boundsOf(mesh) {
  const pts = state.a?.mesh === mesh ? state.a.sample.points : state.b?.sample.points ?? [];
  const c = new THREE.Vector3();
  for (const p of pts) c.add(new THREE.Vector3(...p));
  c.divideScalar(Math.max(1, pts.length));
  const d = pts.map((p) => c.distanceTo(new THREE.Vector3(...p))).sort((x, y) => x - y);
  return { center: c.toArray(), radius: d[Math.floor(d.length * 0.9)] || 1 };
}

// ---------- alignment ----------
async function runAlign() {
  busy("Aligning B onto A…");
  const body = { a: state.a.sample, b: state.b.sample };
  const res = await api("/api/align", body);
  state.align = res;
  state.matrix.fromArray(res.matrix.flat()).transpose(); // server sends row-major
  applyAlignment();
  frameCamera(res.crop);
  showMetrics();
}

function applyAlignment() {
  bHolder.matrix.copy(state.matrix);
  bHolder.matrixWorldNeedsUpdate = true;
  const crop = state.align?.crop;
  if (crop) {
    cropSdf.position.fromArray(crop.center);
    cropSdf.radius = crop.radius * Number($("#crop").value);
  }
}

$("#realign").addEventListener("click", async () => {
  if (!(state.a && state.b)) return;
  try { await runAlign(); } catch (e) { showError(e.message); }
  busy(null); refresh();
});

for (const btn of document.querySelectorAll("[data-rot]")) {
  btn.addEventListener("click", () => {
    const [target, axis] = btn.dataset.rot.split(":");
    const r = new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(...{ x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1] }[axis]), Math.PI / 2);
    if (target === "w") {
      world.quaternion.premultiply(new THREE.Quaternion().setFromRotationMatrix(r));
    } else if (state.align) {
      // rotate B about the crop center, in A's coordinates
      const c = new THREE.Vector3(...state.align.crop.center);
      const about = new THREE.Matrix4().makeTranslation(c.x, c.y, c.z).multiply(r).multiply(new THREE.Matrix4().makeTranslation(-c.x, -c.y, -c.z));
      state.matrix.premultiply(about);
      applyAlignment();
    }
    state.views = null;
    if (state.align) frameCamera(state.align.crop);
    refresh();
  });
}

$("#crop").addEventListener("input", (e) => {
  $("#cropOut").textContent = `${Number(e.target.value).toFixed(2)}×`;
  applyAlignment();
});

function showMetrics() {
  const m = state.align?.metrics;
  if (!m) return void ($("#metrics").textContent = "");
  const pct = (x) => `${Math.round(x * 100)}%`;
  const warn = m.ambiguity > 0.85 ? ` <span class="warn">· another orientation fits almost as well, check Blink</span>` : "";
  $("#metrics").innerHTML =
    `Geometric overlap: A ${pct(m.a_covered)} · B ${pct(m.b_covered)} · fit error ${m.rmse.toFixed(3)} · scale B→A ${state.align.scale.toFixed(3)}${warn}`;
}

// ---------- camera & render loop ----------
function cropWorld(crop) {
  world.updateMatrixWorld(true);
  const center = world.localToWorld(new THREE.Vector3(...crop.center));
  return { center, radius: crop.radius * Number($("#crop").value) };
}

function cameraPose(crop, az, el) {
  const { center, radius } = cropWorld(crop);
  const dist = radius / Math.sin(THREE.MathUtils.degToRad(FOV / 2)) * 1.05;
  const a = THREE.MathUtils.degToRad(az), e = THREE.MathUtils.degToRad(el);
  const pos = new THREE.Vector3(Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e)).multiplyScalar(dist).add(center);
  return { pos, center, near: Math.max(dist - radius * 2, dist / 1000), far: dist + radius * 2 };
}

function frameCamera(crop) {
  const p = cameraPose(crop, 30, 20);
  camera.position.copy(p.pos);
  camera.near = p.near / 10; camera.far = p.far * 10; camera.updateProjectionMatrix();
  controls.target.copy(p.center);
  controls.update();
}

let blinkOn = false;
setInterval(() => { blinkOn = !blinkOn; }, 700);
let capturing = false;

renderer.setAnimationLoop(() => {
  if (capturing) return;
  const showA = { a: true, b: false, overlay: true, blink: !blinkOn }[state.mode];
  const showB = { a: false, b: true, overlay: true, blink: blinkOn }[state.mode];
  setVisible(showA, showB, state.mode === "overlay");
  $("#tag").textContent = !(state.a || state.b) ? "load two models"
    : state.mode === "overlay" ? "overlay: A orange · B blue"
    : showA ? `A · ${state.a?.name ?? "—"}` : `B · ${state.b?.name ?? "—"}`;
  controls.update();
  renderer.render(scene, camera);
});

function setVisible(showA, showB, tint) {
  if (state.a) { state.a.mesh.visible = showA; state.a.mesh.recolor.set(tint ? 0xffb070 : 0xffffff); }
  if (state.b) { state.b.mesh.visible = showB; state.b.mesh.recolor.set(tint ? 0x70b0ff : 0xffffff); }
}

for (const btn of document.querySelectorAll("[data-mode]")) {
  btn.addEventListener("click", () => {
    state.mode = btn.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((b) => b.classList.toggle("on", b === btn));
  });
}

// ---------- capture & compare ----------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function renderSettled(cam) {
  // Spark sorts splats asynchronously; render until the sort for this camera has gone idle.
  // Timers, not requestAnimationFrame (paused in background tabs). Spark schedules its sorts with
  // timers too, so an unfocused/background tab still captures slowly (~1 s per sort): keep it in front.
  let idle = 0;
  const start = performance.now();
  for (let i = 0; performance.now() - start < 6000; i++) {
    await spark.update({ scene, camera: cam });
    renderer.render(scene, cam);
    await sleep(25);
    idle = !spark.sorting && !spark.sortDirty ? idle + 1 : 0;
    if (i >= 3 && idle >= 2) break;
  }
  renderer.render(scene, cam);
  return new Promise((r) => canvas.toBlob(r, "image/png"));
}

// Dolly the camera so A's object fills ~85% of the frame from this side (B shares the camera).
// Perspective makes near parts grow faster than far ones, so refine over a few passes.
function fitToObject(cam, center) {
  const crop = state.align.crop;
  const c = new THREE.Vector3(...crop.center);
  const r = crop.radius * Number($("#crop").value);
  world.updateMatrixWorld(true);
  const pts = state.a.sample.points
    .map((p) => new THREE.Vector3(...p))
    .filter((v) => v.distanceTo(c) <= r)
    .map((v) => v.applyMatrix4(world.matrixWorld));
  if (pts.length < 50) return;
  const v = new THREE.Vector3();
  for (let pass = 0; pass < 4; pass++) {
    cam.updateMatrixWorld(true);
    const extents = pts.map((p) => {
      v.copy(p).project(cam);
      return v.z > 1 || v.z < -1 ? Infinity : Math.max(Math.abs(v.x), Math.abs(v.y));
    }).sort((x, y) => x - y);
    const extent = Math.min(extents[Math.floor(extents.length * 0.99)], 4);
    if (Math.abs(extent - 0.85) < 0.03) break;
    const offset = cam.position.clone().sub(center);
    offset.multiplyScalar(pass === 0 ? extent / 0.85 : Math.sqrt(extent / 0.85)); // damped after the first guess
    cam.position.copy(center).add(offset);
    cam.near = offset.length() / 1000;
    cam.far = offset.length() + r * 4;
    cam.updateProjectionMatrix();
  }
}

async function captureViews() {
  const cam = new THREE.PerspectiveCamera(FOV, 1, 0.01, 1000);
  const out = [];
  capturing = true;
  try {
    for (const [i, v] of VIEWS.entries()) {
      busy(`Rendering view ${i + 1} / ${VIEWS.length}…`);
      const p = cameraPose(state.align.crop, v.az, v.el);
      cam.position.copy(p.pos); cam.near = p.near; cam.far = p.far;
      cam.up.set(0, 1, 0); cam.lookAt(p.center); cam.updateProjectionMatrix();
      fitToObject(cam, p.center);
      setVisible(true, false, false);
      const a = await renderSettled(cam);
      setVisible(false, true, false);
      const b = await renderSettled(cam);
      out.push({ label: viewLabel(v), a, b });
    }
  } finally {
    capturing = false;
  }
  return out;
}

$("#compare").addEventListener("click", async () => {
  showError("");
  try {
    const shots = await captureViews();
    busy(`Asking Jev about ${shots.length} view pairs…`);
    const form = new FormData();
    form.append("meta", JSON.stringify({
      views: shots.map((s) => s.label),
      names: { a: state.a.name, b: state.b.name },
      align: state.align,
      thresholds: state.thresholds,
    }));
    shots.forEach((s, i) => { form.append(`a_${i}`, s.a, `a_${i}.png`); form.append(`b_${i}`, s.b, `b_${i}.png`); });
    const res = await fetch("/api/compare", { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
    const data = await res.json();
    state.views = data.views.map((v, i) => ({ ...v, urls: [URL.createObjectURL(shots[i].a), URL.createObjectURL(shots[i].b)] }));
    $("#runName").textContent = `saved to runs/${data.run}`;
    showResult(data.result);
  } catch (e) {
    showError(e.message);
  }
  busy(null);
  refresh();
});

// ---------- results ----------
const CATS = { shape_diff: "shape", part_diff: "missing/extra part", color_diff: "color/material", any_diff: "any difference" };
const TITLES = { same: "Same object", different: "Different", uncertain: "Uncertain", alignment_failed: "Alignment failed" };

function showResult(r) {
  const th = { ...DEFAULTS, ...state.thresholds };
  const cats = Object.entries(r.categories).map(([k, c]) =>
    `<div class="cat"><span>${CATS[k]}</span><div class="bar"><i style="width:${c.evidence * 100}%"></i></div><span>${c.evidence.toFixed(2)}</span></div>`).join("");
  $("#result").innerHTML =
    `<div class="verdict v-${r.verdict}"><b>${TITLES[r.verdict]}</b>${r.reason}</div>
     ${cats ? `<h2>Evidence (${ordinal(th.support)}-strongest view)</h2>${cats}` : ""}
     <p class="hint">${r.usable_views} of ${state.views.length} views counted as aligned.</p>`;
  renderTable(th);
}

function renderTable(th) {
  const cell = (p) => `<td class="${p >= th.different ? "hi" : p <= th.same ? "lo" : ""}">${p.toFixed(2)}</td>`;
  $("#views tbody").innerHTML = state.views.map((v) =>
    `<tr class="${v.viewpoint_match < th.viewpoint_min ? "dim" : ""}"><td>${v.view}</td>
      <td><div class="pair"><img src="${v.urls[0]}" alt="A"><img src="${v.urls[1]}" alt="B"></div></td>
      <td>${v.viewpoint_match.toFixed(2)}</td>${["shape_diff", "part_diff", "color_diff", "any_diff"].map((k) => cell(v[k])).join("")}</tr>`).join("");
  $("#views").hidden = false;
}

const ordinal = (n) => ["", "1st", "2nd", "3rd", "4th"][n] ?? `${n}th`;
const DEFAULTS = { different: 0.5, same: 0.25, viewpoint_min: 0.5, support: 2, min_views: 6 };

for (const input of document.querySelectorAll("[data-th]")) {
  const out = input.nextElementSibling;
  out.textContent = input.value;
  input.addEventListener("input", async () => {
    out.textContent = input.value;
    state.thresholds[input.dataset.th] = Number(input.value);
    if (!state.views) return;
    const r = await api("/api/aggregate", { views: state.views.map(({ urls, ...v }) => v), thresholds: state.thresholds });
    showResult(r);
  });
}

// ---------- helpers ----------
async function api(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

function busy(msg) {
  $("#busy").textContent = msg ?? "";
  $("#busy").classList.toggle("on", !!msg);
}

(async () => {
  for (const p of pendingUrlLoads) {
    try { await load(...(await p)); } catch (e) { showError(e.message); }
  }
  if (new URLSearchParams(location.search).has("auto") && !$("#compare").disabled) $("#compare").click();
})();

function showError(msg) { $("#error").textContent = msg; }

function refresh() {
  const ready = !!(state.a && state.b && state.align);
  $("#compare").disabled = !ready;
  document.querySelectorAll("[data-rot^='b:'], #realign").forEach((b) => (b.disabled = !ready));
}
refresh();
