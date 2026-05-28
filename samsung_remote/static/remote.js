// Block Safari pinch + double-tap zoom that survive viewport meta.
["gesturestart", "gesturechange", "gestureend"].forEach((ev) =>
  document.addEventListener(ev, (e) => e.preventDefault(), { passive: false })
);
let _lastTouchEnd = 0;
document.addEventListener("touchend", (e) => {
  const now = Date.now();
  if (now - _lastTouchEnd < 300) e.preventDefault();
  _lastTouchEnd = now;
}, { passive: false });

const toast = (msg) => {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2000);
};

async function post(path, body) {
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      toast(data.error || `Error ${res.status}`);
    }
  } catch (e) {
    toast("TV unreachable");
  }
}

// Wire static buttons.
document.querySelectorAll("[data-key]").forEach((b) =>
  b.addEventListener("click", () => post(`/key/${b.dataset.key}`))
);
document.querySelectorAll("[data-wol]").forEach((b) =>
  b.addEventListener("click", () => post("/wol"))
);

// Gesture pad: swipe -> arrow key, tap -> enter.
const pad = document.getElementById("gesturepad");
let sx = 0, sy = 0;
const THRESHOLD = 30; // px before a move counts as a swipe
pad.addEventListener("touchstart", (e) => {
  const t = e.touches[0];
  sx = t.clientX; sy = t.clientY;
}, { passive: true });
pad.addEventListener("touchend", (e) => {
  const t = e.changedTouches[0];
  const dx = t.clientX - sx, dy = t.clientY - sy;
  pad.classList.add("flash");
  setTimeout(() => pad.classList.remove("flash"), 120);
  if (Math.abs(dx) < THRESHOLD && Math.abs(dy) < THRESHOLD) {
    post("/key/KEY_ENTER");
    return;
  }
  let key;
  if (Math.abs(dx) > Math.abs(dy)) key = dx > 0 ? "KEY_RIGHT" : "KEY_LEFT";
  else key = dy > 0 ? "KEY_DOWN" : "KEY_UP";
  post(`/key/${key}`);
});

// Build app + macro grids from /config.
async function buildGrids() {
  let cfg;
  try {
    cfg = await (await fetch("/config")).json();
  } catch {
    return;
  }
  const apps = document.getElementById("apps");
  cfg.apps.forEach((a) => {
    const b = document.createElement("button");
    b.className = "btn";
    b.textContent = a.name;
    b.addEventListener("click", () => post(`/app/${a.id}`));
    apps.appendChild(b);
  });
  const macros = document.getElementById("macros");
  cfg.macros.forEach((name) => {
    const b = document.createElement("button");
    b.className = "btn";
    b.textContent = name;
    b.addEventListener("click", () => post(`/macro/${name}`));
    macros.appendChild(b);
  });
}
buildGrids();
