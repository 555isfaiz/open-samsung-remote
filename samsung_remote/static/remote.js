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

// Latency diagnostics: compare the full round trip with the server's own time
// (Server-Timing header), and break the network part down with the Resource
// Timing API (queueing, DNS, TCP/TLS connect, waiting for the response).
const SLOW_MS = 1000;
function phases(url) {
  const e = performance.getEntriesByName(new URL(url, location.href).href).pop();
  if (!e) return null;
  const d = (a, b) => (a && b ? Math.round(b - a) : 0);
  return {
    queued: d(e.startTime, e.domainLookupStart || e.connectStart || e.requestStart),
    dns: d(e.domainLookupStart, e.domainLookupEnd),
    connect: d(e.connectStart, e.connectEnd),          // includes TLS
    tls: d(e.secureConnectionStart, e.connectEnd),
    reused: e.connectStart === e.connectEnd,
    ttfb: d(e.requestStart, e.responseStart),          // send -> first byte
    proto: e.nextHopProtocol,
  };
}
function reportTiming(path, res, t0) {
  const total = Math.round(performance.now() - t0);
  if (total < SLOW_MS) return;
  const m = /dur=([\d.]+)/.exec(res.headers.get("Server-Timing") || "");
  const server = m ? Math.round(parseFloat(m[1])) : null;
  const ph = phases(path);
  console.warn(`slow ${path}: total ${total}ms, server ${server}ms`, ph);
  toast(`Slow: ${total}ms total, server ${server ?? "?"}ms`);
  navigator.sendBeacon?.("/client-timing",
    JSON.stringify({ path, total, server, phases: ph }));
}

// Keep the phone -> server path warm while the page is visible: an idle
// HTTPS connection gets closed (ingress keepalive), and the next press then
// pays DNS + TCP + TLS again. A tiny GET every 15s keeps it open and the DNS
// entry cached; also warm it immediately when the page comes back to view.
const WARM_EVERY = 15000;
const warm = () => {
  if (document.visibilityState === "visible")
    fetch("/health", { cache: "no-store" }).catch(() => {});
};
setInterval(warm, WARM_EVERY);
document.addEventListener("visibilitychange", warm);
window.addEventListener("pageshow", warm);

async function post(path, body) {
  try {
    const t0 = performance.now();
    const res = await fetch(path, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();  // complete the response so its timing entry exists
    reportTiming(path, res, t0);
    if (!res.ok) {
      let data = {};
      try { data = JSON.parse(text); } catch {}
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
