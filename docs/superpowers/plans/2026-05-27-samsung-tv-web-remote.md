# Samsung TV Web Remote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phone-friendly web page that controls a Samsung TV (2020+) over the local network, with macros, favorite-app launch, gesture pad, and Wake-on-LAN, deployable as a container to a Kubernetes cluster on the TV's network.

**Architecture:** A Flask server holds the TV pairing token and exposes a JSON HTTP API. A static web UI (vanilla JS) served by the same Flask app calls that API. The server talks to the TV over WSS (port 8002, TLS) via the `samsungtvws` library. WoL is an L2 broadcast, so the k8s pod runs with `hostNetwork: true`.

**Tech Stack:** Python 3.12, Flask, gunicorn, samsungtvws, PyYAML, pytest, Docker, Kubernetes.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `requirements.txt` | Runtime deps |
| `requirements-dev.txt` | Test deps |
| `config.example.yaml` | Sample config (TV host, apps, macros) |
| `samsung_remote/__init__.py` | Package marker |
| `samsung_remote/config.py` | Load + validate `config.yaml` into a `Config` dataclass |
| `samsung_remote/tv.py` | `TVController` wrapping samsungtvws (inject `ws_factory` for tests) |
| `samsung_remote/app.py` | Flask app factory, routes, serves static UI |
| `samsung_remote/static/index.html` | Remote layout |
| `samsung_remote/static/style.css` | CSS-grid remote styling |
| `samsung_remote/static/remote.js` | Button POSTs, gesture pad, app/macro grids, toasts |
| `tests/test_config.py` | Config parsing tests |
| `tests/test_tv.py` | TVController behavior tests (fake ws) |
| `tests/test_app.py` | Flask route tests (fake TVController) |
| `wsgi.py` | gunicorn entrypoint (`app = create_app()`) |
| `Dockerfile` | Container build |
| `k8s/configmap.yaml` | config.yaml as ConfigMap |
| `k8s/pvc.yaml` | Token persistence |
| `k8s/deployment.yaml` | Deployment (hostNetwork, nodeSelector, volumes) |
| `k8s/service.yaml` | NodePort service |
| `README.md` | Setup, pairing, deploy |

---

## Task 1: Project skeleton + dependencies

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `samsung_remote/__init__.py`, `pytest.ini`

- [ ] **Step 1: Write requirements files**

`requirements.txt`:
```
flask==3.0.3
samsungtvws[async,encrypted]==2.7.2
PyYAML==6.0.2
gunicorn==23.0.0
wakeonlan==3.1.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.3.3
```

- [ ] **Step 2: Create package marker + pytest config**

`samsung_remote/__init__.py`: (empty file)

`pytest.ini`:
```ini
[pytest]
testpaths = tests
```

- [ ] **Step 3: Install deps**

Run: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt`
Expected: installs without error.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt requirements-dev.txt samsung_remote/__init__.py pytest.ini
git commit -m "chore: project skeleton and dependencies"
```

---

## Task 2: Config loader

**Files:**
- Create: `samsung_remote/config.py`
- Create: `config.example.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import textwrap
from samsung_remote.config import load_config

def test_load_config_parses_tv_apps_macros(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        tv:
          host: 192.168.1.50
          port: 8002
          name: WebRemote
          mac: "AA:BB:CC:DD:EE:FF"
          token_file: /data/token.txt
        apps:
          - { name: Netflix, id: "11101200001" }
        macros:
          movie_night:
            - { wol: true }
            - { delay: 8 }
            - { key: KEY_HDMI2 }
            - { app: "11101200001" }
    """))
    cfg = load_config(str(p))
    assert cfg.tv.host == "192.168.1.50"
    assert cfg.tv.port == 8002
    assert cfg.tv.mac == "AA:BB:CC:DD:EE:FF"
    assert cfg.apps[0].name == "Netflix"
    assert cfg.apps[0].id == "11101200001"
    assert cfg.macros["movie_night"][0] == {"wol": True}
    assert cfg.macros["movie_night"][1] == {"delay": 8}

def test_load_config_defaults_port_8002(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("tv:\n  host: 1.2.3.4\n  token_file: /data/token.txt\n")
    cfg = load_config(str(p))
    assert cfg.tv.port == 8002
    assert cfg.apps == []
    assert cfg.macros == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samsung_remote.config'`

- [ ] **Step 3: Write minimal implementation**

`samsung_remote/config.py`:
```python
from dataclasses import dataclass, field
import yaml


@dataclass
class TVConfig:
    host: str
    token_file: str
    port: int = 8002
    name: str = "WebRemote"
    mac: str | None = None


@dataclass
class AppEntry:
    name: str
    id: str


@dataclass
class Config:
    tv: TVConfig
    apps: list[AppEntry] = field(default_factory=list)
    macros: dict[str, list[dict]] = field(default_factory=dict)


def load_config(path: str) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    tv_raw = raw.get("tv", {})
    tv = TVConfig(
        host=tv_raw["host"],
        token_file=tv_raw["token_file"],
        port=tv_raw.get("port", 8002),
        name=tv_raw.get("name", "WebRemote"),
        mac=tv_raw.get("mac"),
    )
    apps = [AppEntry(name=a["name"], id=str(a["id"])) for a in raw.get("apps", [])]
    macros = raw.get("macros", {}) or {}
    return Config(tv=tv, apps=apps, macros=macros)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Write config.example.yaml**

`config.example.yaml`:
```yaml
tv:
  host: 192.168.1.50
  port: 8002
  name: WebRemote
  mac: "AA:BB:CC:DD:EE:FF"   # for Wake-on-LAN; find via your router or `arp`
  token_file: /data/token.txt
apps:
  - { name: Netflix,   id: "11101200001" }
  - { name: YouTube,   id: "111299001912" }
  - { name: Prime,     id: "3201512006785" }
  - { name: "Disney+", id: "3201901017640" }
macros:
  movie_night:
    - { wol: true }
    - { delay: 8 }
    - { key: KEY_HDMI2 }
    - { delay: 1 }
    - { app: "3201512006785" }
```

- [ ] **Step 6: Commit**

```bash
git add samsung_remote/config.py config.example.yaml tests/test_config.py
git commit -m "feat: config loader for TV, apps, and macros"
```

---

## Task 3: TVController

**Files:**
- Create: `samsung_remote/tv.py`
- Test: `tests/test_tv.py`

- [ ] **Step 1: Write the failing test**

`tests/test_tv.py`:
```python
from samsung_remote.tv import TVController


class FakeRemote:
    def __init__(self):
        self.keys = []

    def send_key(self, key):
        self.keys.append(key)


class FakeWS:
    """Stand-in for SamsungTVWS."""
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.remote = FakeRemote()
        self.apps_run = []
        FakeWS.last = self

    def shortcuts(self):
        return self.remote

    def rest_app_run(self, app_id):
        self.apps_run.append(app_id)


def make_controller():
    return TVController(
        host="1.2.3.4", port=8002, token_file="/tmp/token.txt",
        mac="AA:BB:CC:DD:EE:FF", name="Test", ws_factory=FakeWS,
    )


def test_send_key_forwards_to_ws():
    tv = make_controller()
    tv.send_key("KEY_VOLUP")
    assert FakeWS.last.remote.keys == ["KEY_VOLUP"]


def test_send_keys_sends_each_in_order():
    tv = make_controller()
    tv.send_keys(["KEY_UP", "KEY_ENTER"], delay=0)
    assert FakeWS.last.remote.keys == ["KEY_UP", "KEY_ENTER"]


def test_launch_app_calls_rest_app_run():
    tv = make_controller()
    tv.launch_app("11101200001")
    assert FakeWS.last.apps_run == ["11101200001"]


def test_wake_sends_magic_packet(monkeypatch):
    sent = {}
    def fake_send(mac):
        sent["mac"] = mac
    monkeypatch.setattr("samsung_remote.tv.send_magic_packet", fake_send)
    tv = make_controller()
    tv.wake()
    assert sent["mac"] == "AA:BB:CC:DD:EE:FF"


def test_ws_factory_receives_port_and_token():
    make_controller().send_key("KEY_HOME")
    assert FakeWS.last.kwargs["port"] == 8002
    assert FakeWS.last.kwargs["token_file"] == "/tmp/token.txt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tv.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samsung_remote.tv'`

- [ ] **Step 3: Write minimal implementation**

`samsung_remote/tv.py`:
```python
import socket
from samsungtvws import SamsungTVWS
from wakeonlan import send_magic_packet


class TVController:
    """Talks to a Samsung TV (2020+) over WSS, owns the pairing token."""

    def __init__(self, host, port, token_file, mac=None, name="WebRemote",
                 ws_factory=SamsungTVWS):
        self._host = host
        self._port = port
        self._token_file = token_file
        self._mac = mac
        self._name = name
        self._ws_factory = ws_factory
        self._ws = None

    def _conn(self):
        # Lazily build the connection so import never blocks on the network.
        if self._ws is None:
            self._ws = self._ws_factory(
                host=self._host, port=self._port,
                token_file=self._token_file, name=self._name,
            )
        return self._ws

    def send_key(self, keycode: str) -> None:
        self._conn().shortcuts().send_key(keycode)

    def send_keys(self, keycodes: list[str], delay: float = 0.1) -> None:
        import time
        remote = self._conn().shortcuts()
        for i, key in enumerate(keycodes):
            if i and delay:
                time.sleep(delay)
            remote.send_key(key)

    def launch_app(self, app_id: str) -> None:
        self._conn().rest_app_run(app_id)

    def wake(self) -> None:
        if not self._mac:
            raise ValueError("No MAC configured for Wake-on-LAN")
        send_magic_packet(self._mac)

    def reachable(self) -> bool:
        try:
            with socket.create_connection((self._host, self._port), timeout=2):
                return True
        except OSError:
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tv.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add samsung_remote/tv.py tests/test_tv.py
git commit -m "feat: TVController wrapping samsungtvws with WoL and reachability"
```

---

## Task 4: Flask app factory + key/app/wol/health/config routes

**Files:**
- Create: `samsung_remote/app.py`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

`tests/test_app.py`:
```python
import pytest
from samsung_remote.app import create_app
from samsung_remote.config import Config, TVConfig, AppEntry


class FakeTV:
    def __init__(self):
        self.keys = []
        self.batches = []
        self.apps = []
        self.woke = False
        self._reachable = True

    def send_key(self, k): self.keys.append(k)
    def send_keys(self, ks, delay=0.1): self.batches.append(ks)
    def launch_app(self, a): self.apps.append(a)
    def wake(self): self.woke = True
    def reachable(self): return self._reachable


@pytest.fixture
def ctx():
    cfg = Config(
        tv=TVConfig(host="1.2.3.4", token_file="/tmp/t", mac="AA:BB:CC:DD:EE:FF"),
        apps=[AppEntry(name="Netflix", id="11101200001")],
        macros={"movie": [{"key": "KEY_HDMI2"}, {"delay": 0}, {"app": "11101200001"}]},
    )
    tv = FakeTV()
    app = create_app(cfg, tv)
    return app.test_client(), tv


def test_key_route(ctx):
    client, tv = ctx
    r = client.post("/key/KEY_VOLUP")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert tv.keys == ["KEY_VOLUP"]


def test_keys_batch_route(ctx):
    client, tv = ctx
    r = client.post("/keys", json={"keys": ["KEY_UP", "KEY_ENTER"]})
    assert r.status_code == 200
    assert tv.batches == [["KEY_UP", "KEY_ENTER"]]


def test_app_route(ctx):
    client, tv = ctx
    client.post("/app/11101200001")
    assert tv.apps == ["11101200001"]


def test_wol_route(ctx):
    client, tv = ctx
    client.post("/wol")
    assert tv.woke is True


def test_health_route(ctx):
    client, tv = ctx
    r = client.get("/health")
    assert r.get_json() == {"server": "ok", "tv_reachable": True}


def test_config_route_exposes_apps_and_macro_names(ctx):
    client, tv = ctx
    body = client.get("/config").get_json()
    assert body["apps"] == [{"name": "Netflix", "id": "11101200001"}]
    assert body["macros"] == ["movie"]


def test_unreachable_tv_returns_503(ctx):
    client, tv = ctx
    tv._reachable = True  # reachable() not used by send; simulate send failure
    def boom(_): raise OSError("connection refused")
    tv.send_key = boom
    r = client.post("/key/KEY_VOLUP")
    assert r.status_code == 503
    assert r.get_json()["ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'samsung_remote.app'`

- [ ] **Step 3: Write minimal implementation**

`samsung_remote/app.py`:
```python
import os
from flask import Flask, jsonify, request, send_from_directory

from .config import load_config
from .tv import TVController

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(config, tv):
    app = Flask(__name__, static_folder=None)

    def ok():
        return jsonify({"ok": True})

    def fail(msg, code=503):
        return jsonify({"ok": False, "error": msg}), code

    @app.post("/key/<keycode>")
    def key(keycode):
        try:
            tv.send_key(keycode)
            return ok()
        except OSError as e:
            return fail(str(e))

    @app.post("/keys")
    def keys():
        body = request.get_json(silent=True) or {}
        try:
            tv.send_keys(list(body.get("keys", [])))
            return ok()
        except OSError as e:
            return fail(str(e))

    @app.post("/app/<app_id>")
    def launch(app_id):
        try:
            tv.launch_app(app_id)
            return ok()
        except OSError as e:
            return fail(str(e))

    @app.post("/macro/<name>")
    def macro(name):
        steps = config.macros.get(name)
        if steps is None:
            return fail(f"unknown macro: {name}", 404)
        try:
            run_macro(tv, steps)
            return ok()
        except OSError as e:
            return fail(str(e))

    @app.post("/wol")
    def wol():
        try:
            tv.wake()
            return ok()
        except ValueError as e:
            return fail(str(e), 400)

    @app.get("/health")
    def health():
        return jsonify({"server": "ok", "tv_reachable": tv.reachable()})

    @app.get("/config")
    def get_config():
        return jsonify({
            "apps": [{"name": a.name, "id": a.id} for a in config.apps],
            "macros": list(config.macros.keys()),
        })

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:path>")
    def static_files(path):
        return send_from_directory(STATIC_DIR, path)

    return app


def run_macro(tv, steps):
    """Execute a macro: ordered keys, app launches, delays, and WoL."""
    import time
    for step in steps:
        if "delay" in step:
            time.sleep(step["delay"])
        elif "key" in step:
            tv.send_key(step["key"])
        elif "app" in step:
            tv.launch_app(step["app"])
        elif step.get("wol"):
            tv.wake()


def create_app_from_env():
    cfg = load_config(os.environ.get("CONFIG_PATH", "config.yaml"))
    tv = TVController(
        host=cfg.tv.host, port=cfg.tv.port, token_file=cfg.tv.token_file,
        mac=cfg.tv.mac, name=cfg.tv.name,
    )
    return create_app(cfg, tv)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Add a macro execution test**

Append to `tests/test_app.py`:
```python
def test_macro_route_runs_steps_in_order(ctx):
    client, tv = ctx
    r = client.post("/macro/movie")
    assert r.status_code == 200
    assert tv.keys == ["KEY_HDMI2"]
    assert tv.apps == ["11101200001"]

def test_macro_unknown_returns_404(ctx):
    client, tv = ctx
    r = client.post("/macro/nope")
    assert r.status_code == 404
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_app.py -v`
Expected: PASS (9 passed)

- [ ] **Step 7: Commit**

```bash
git add samsung_remote/app.py tests/test_app.py
git commit -m "feat: Flask routes for keys, apps, macros, WoL, health, config"
```

---

## Task 5: WSGI entrypoint

**Files:**
- Create: `wsgi.py`

- [ ] **Step 1: Write wsgi.py**

`wsgi.py`:
```python
from samsung_remote.app import create_app_from_env

app = create_app_from_env()
```

- [ ] **Step 2: Verify it imports (with a config present)**

Run: `cp config.example.yaml config.yaml && CONFIG_PATH=config.yaml python -c "import wsgi; print('ok')"`
Expected: prints `ok` (no network call happens at import — connection is lazy).

- [ ] **Step 3: Commit**

```bash
git add wsgi.py
git commit -m "feat: gunicorn wsgi entrypoint"
```

---

## Task 6: Web UI — HTML structure

**Files:**
- Create: `samsung_remote/static/index.html`

- [ ] **Step 1: Write index.html**

`samsung_remote/static/index.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <meta name="theme-color" content="#111" />
  <title>TV Remote</title>
  <link rel="stylesheet" href="/static/style.css" />
</head>
<body>
  <div id="toast" class="toast"></div>

  <main class="remote">
    <div class="row top">
      <button class="btn power" data-key="KEY_POWER">⏻</button>
      <button class="btn" data-wol="1">Wake</button>
      <button class="btn" data-key="KEY_SOURCE">Source</button>
    </div>

    <div class="row">
      <button class="btn" data-key="KEY_VOLUP">Vol +</button>
      <button class="btn" data-key="KEY_HOME">Home</button>
      <button class="btn" data-key="KEY_CHUP">Ch +</button>
    </div>
    <div class="row">
      <button class="btn" data-key="KEY_MUTE">Mute</button>
      <button class="btn" data-key="KEY_MENU">Menu</button>
      <button class="btn" data-key="KEY_CHDOWN">Ch -</button>
    </div>
    <div class="row">
      <button class="btn" data-key="KEY_VOLDOWN">Vol -</button>
      <button class="btn" data-key="KEY_RETURN">Back</button>
      <button class="btn" data-key="KEY_EXIT">Exit</button>
    </div>

    <!-- Gesture pad doubles as the d-pad: swipe = arrows, tap = enter -->
    <div id="gesturepad" class="gesturepad">Swipe / tap</div>

    <div class="row">
      <button class="btn" data-key="KEY_REWIND">⏪</button>
      <button class="btn" data-key="KEY_PLAY">⏯</button>
      <button class="btn" data-key="KEY_FF">⏩</button>
    </div>

    <section>
      <h2>Apps</h2>
      <div id="apps" class="grid"></div>
    </section>

    <section>
      <h2>Macros</h2>
      <div id="macros" class="grid"></div>
    </section>
  </main>

  <script src="/static/remote.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add samsung_remote/static/index.html
git commit -m "feat: web UI HTML structure"
```

---

## Task 7: Web UI — CSS

**Files:**
- Create: `samsung_remote/static/style.css`

- [ ] **Step 1: Write style.css**

`samsung_remote/static/style.css`:
```css
* { box-sizing: border-box; }
body {
  margin: 0; background: #111; color: #eee;
  font: 16px/1.3 system-ui, sans-serif;
  -webkit-tap-highlight-color: transparent;
}
.remote { max-width: 420px; margin: 0 auto; padding: 16px; }
.row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 10px; }
.btn {
  background: #2a2a2a; color: #eee; border: none; border-radius: 12px;
  padding: 18px 0; font-size: 16px; cursor: pointer; user-select: none;
}
.btn:active { background: #3d6; color: #111; }
.btn.power { background: #922; }
.gesturepad {
  height: 200px; margin: 14px 0; border-radius: 16px;
  background: #1c1c1c; border: 2px dashed #444;
  display: flex; align-items: center; justify-content: center;
  color: #666; touch-action: none; user-select: none;
}
.gesturepad.flash { background: #3d6; color: #111; }
section h2 { font-size: 14px; color: #888; margin: 18px 0 8px; text-transform: uppercase; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.toast {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
  background: #922; color: #fff; padding: 10px 18px; border-radius: 10px;
  opacity: 0; transition: opacity .2s; pointer-events: none; z-index: 10;
}
.toast.show { opacity: 1; }
```

- [ ] **Step 2: Commit**

```bash
git add samsung_remote/static/style.css
git commit -m "feat: web UI styling"
```

---

## Task 8: Web UI — JavaScript (POST, gesture pad, dynamic grids)

**Files:**
- Create: `samsung_remote/static/remote.js`

- [ ] **Step 1: Write remote.js**

`samsung_remote/static/remote.js`:
```javascript
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
```

- [ ] **Step 2: Manual sanity check**

Run: `CONFIG_PATH=config.yaml python -c "from samsung_remote.app import create_app_from_env; c=create_app_from_env().test_client(); r=c.get('/'); print(r.status_code); print(b'gesturepad' in r.data)"`
Expected: prints `200` then `True`.

- [ ] **Step 3: Commit**

```bash
git add samsung_remote/static/remote.js
git commit -m "feat: web UI behavior — buttons, gesture pad, app/macro grids"
```

---

## Task 9: Dockerfile

**Files:**
- Create: `Dockerfile`, `.dockerignore`

- [ ] **Step 1: Write .dockerignore**

`.dockerignore`:
```
.venv
__pycache__
*.pyc
tests
docs
config.yaml
token.txt
data
.git
```

- [ ] **Step 2: Write Dockerfile**

`Dockerfile`:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY samsung_remote ./samsung_remote
COPY wsgi.py .

# Non-root; /data holds the pairing token (mounted as a volume in k8s).
RUN useradd -m app && mkdir /data && chown app /data
USER app

ENV CONFIG_PATH=/config/config.yaml
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--timeout", "30", "wsgi:app"]
```

> Note: `--workers 1` is deliberate — the pairing token and TV WebSocket are a single
> shared resource; multiple workers would each try to pair separately.

- [ ] **Step 3: Build to verify**

Run: `docker build -t samsung-remote:dev .`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: container image"
```

---

## Task 10: Kubernetes manifests

**Files:**
- Create: `k8s/configmap.yaml`, `k8s/pvc.yaml`, `k8s/deployment.yaml`, `k8s/service.yaml`

- [ ] **Step 1: Write configmap.yaml**

`k8s/configmap.yaml`:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: samsung-remote-config
data:
  config.yaml: |
    tv:
      host: 192.168.1.50
      port: 8002
      name: WebRemote
      mac: "AA:BB:CC:DD:EE:FF"
      token_file: /data/token.txt
    apps:
      - { name: Netflix,   id: "11101200001" }
      - { name: YouTube,   id: "111299001912" }
      - { name: Prime,     id: "3201512006785" }
      - { name: "Disney+", id: "3201901017640" }
    macros:
      movie_night:
        - { wol: true }
        - { delay: 8 }
        - { key: KEY_HDMI2 }
        - { delay: 1 }
        - { app: "3201512006785" }
```

- [ ] **Step 2: Write pvc.yaml**

`k8s/pvc.yaml`:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: samsung-remote-token
spec:
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 64Mi
```

- [ ] **Step 3: Write deployment.yaml**

`k8s/deployment.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: samsung-remote
  labels: { app: samsung-remote }
spec:
  replicas: 1
  strategy: { type: Recreate }   # single token/PVC; no rolling overlap
  selector:
    matchLabels: { app: samsung-remote }
  template:
    metadata:
      labels: { app: samsung-remote }
    spec:
      # hostNetwork REQUIRED: Wake-on-LAN is an L2 broadcast that the pod
      # overlay network NATs/drops. On host network the magic packet goes out
      # the node's real LAN interface, same subnet as the TV.
      hostNetwork: true
      dnsPolicy: ClusterFirstWithHostNet
      # Pin to a node on the TV's subnet. Set this label on that node:
      #   kubectl label node <node> tv-network=true
      nodeSelector:
        tv-network: "true"
      containers:
        - name: samsung-remote
          image: samsung-remote:dev   # push to your registry and update this
          ports:
            - containerPort: 5000
              hostPort: 5000
          env:
            - name: CONFIG_PATH
              value: /config/config.yaml
          volumeMounts:
            - { name: config, mountPath: /config }
            - { name: token,  mountPath: /data }
          readinessProbe:
            httpGet: { path: /health, port: 5000 }
            initialDelaySeconds: 5
            periodSeconds: 15
      volumes:
        - name: config
          configMap: { name: samsung-remote-config }
        - name: token
          persistentVolumeClaim: { claimName: samsung-remote-token }
```

- [ ] **Step 4: Write service.yaml**

`k8s/service.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: samsung-remote
spec:
  type: NodePort
  selector:
    app: samsung-remote
  ports:
    - port: 5000
      targetPort: 5000
      nodePort: 30080
```

> Note: with `hostNetwork: true` the UI is already reachable at `http://<node-ip>:5000`.
> The NodePort Service is provided for ingress/discovery convenience.

- [ ] **Step 5: Validate manifests (dry run, if a cluster is reachable)**

Run: `kubectl apply --dry-run=client -f k8s/`
Expected: each manifest reports `(dry run)` with no schema errors.
(If no cluster is configured, skip — the YAML is still committed.)

- [ ] **Step 6: Commit**

```bash
git add k8s/
git commit -m "feat: kubernetes manifests with hostNetwork for WoL"
```

---

## Task 11: README + full test run

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

`README.md`:
````markdown
# Samsung TV Web Remote

A phone-friendly web remote for Samsung TVs (2020+), with macros, favorite-app
launch, a gesture pad, and Wake-on-LAN. Runs as a small Flask server you can drop
on a Pi or deploy to a Kubernetes cluster on your TV's network.

## Local run

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp config.example.yaml config.yaml   # edit host + mac
CONFIG_PATH=config.yaml gunicorn --bind 0.0.0.0:5000 --workers 1 wsgi:app
```

Open `http://<server-ip>:5000` on your phone. The first key press triggers an
"Allow this device?" prompt on the TV. Accept it once; the token is saved to the
path in `token_file` and reused after that.

## Tests

```bash
pytest
```

## Docker

```bash
docker build -t samsung-remote:dev .
docker run --network host \
  -v "$PWD/config.yaml:/config/config.yaml" \
  -v samsung-remote-data:/data \
  samsung-remote:dev
```
`--network host` matters: Wake-on-LAN is an L2 broadcast and will not cross the
default bridge network.

## Kubernetes

1. Label a node that sits on the TV's subnet:
   `kubectl label node <node> tv-network=true`
2. Edit `k8s/configmap.yaml` (TV host + MAC) and the image in `k8s/deployment.yaml`.
3. `kubectl apply -f k8s/`
4. Open `http://<node-ip>:5000`.

`hostNetwork: true` is required so the WoL magic packet leaves the node's real LAN
interface. The pairing token lives on a PVC so it survives restarts.

## Keys

Standard Tizen key set: `KEY_POWER`, `KEY_UP/DOWN/LEFT/RIGHT`, `KEY_ENTER`,
`KEY_VOLUP/VOLDOWN/MUTE`, `KEY_CHUP/CHDOWN`, `KEY_0`–`KEY_9`, `KEY_HDMI1`–`KEY_HDMI4`,
`KEY_PLAY/PAUSE/STOP/REWIND/FF`, and more.
````

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass (config + tv + app: ~16 tests).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with setup, pairing, Docker, and k8s instructions"
```

---

## Self-Review Notes

- **Spec coverage:** remote keys (Tasks 6/8), favorite apps (Tasks 4/8 `/app` + grid),
  macros (Task 4 `run_macro` + `/macro`), gesture pad (Task 8), WoL (Tasks 3/4 + k8s
  hostNetwork in Task 10), config-driven apps/macros (Task 2), error toasts (Task 8),
  503 handling (Task 4), token persistence (Task 10 PVC), Docker + k8s (Tasks 9/10).
- **Type consistency:** `TVController` method names (`send_key`, `send_keys`,
  `launch_app`, `wake`, `reachable`) match between Task 3 definition, Task 4 FakeTV,
  and `app.py` calls. Config field names (`tv.host/port/mac/token_file/name`, `apps[].name/id`,
  `macros`) match between Task 2, Task 4 fixture, and k8s ConfigMap.
- **No placeholders:** every code step shows complete code; every run step shows the command + expected output.
