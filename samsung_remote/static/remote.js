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
document.querySelectorAll("[data-kodi]").forEach((b) =>
  b.addEventListener("click", () => post(`/kodi/action/${b.dataset.kodi}`))
);

// Kodi text: fills Kodi's on-screen keyboard (must be open) and submits it.
const kodiForm = document.getElementById("kodi-text");
kodiForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = kodiForm.querySelector("input");
  if (!input.value) return;
  await post("/kodi/text", { text: input.value, done: true });
  input.value = "";
});

// D-pad: press sends one key; holding an arrow repeats it. A repeat is skipped
// while the previous request is still in flight so presses never pile up and
// keep scrolling after release.
const REPEAT_DELAY = 400; // ms before auto-repeat starts
const REPEAT_EVERY = 120; // ms between repeats
document.querySelectorAll("[data-dpad]").forEach((b) => {
  const key = b.dataset.dpad;
  const repeats = key !== "KEY_ENTER";
  let timer = null, inflight = false;
  const send = async () => {
    if (inflight) return;
    inflight = true;
    try { await post(`/key/${key}`); } finally { inflight = false; }
  };
  const stop = () => {
    clearTimeout(timer); clearInterval(timer); timer = null;
    b.classList.remove("pressed");
  };
  b.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    b.setPointerCapture(e.pointerId);
    b.classList.add("pressed");
    send();
    if (repeats) timer = setTimeout(() => { timer = setInterval(send, REPEAT_EVERY); }, REPEAT_DELAY);
  });
  ["pointerup", "pointercancel", "lostpointercapture"].forEach((ev) =>
    b.addEventListener(ev, stop)
  );
  b.addEventListener("contextmenu", (e) => e.preventDefault());
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
  document.getElementById("kodi").hidden = !cfg.kodi;
}
buildGrids();
