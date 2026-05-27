# Samsung TV Web Remote — Design

Date: 2026-05-27

## Goal

A phone-friendly web page that controls a Samsung TV over the local network, plus
extras a physical remote cannot do (macros, favorite-app grid, gesture pad).
Deployable as a container into a Kubernetes cluster on the same network as the TV.

## Stack

- Backend: Python 3.12, Flask, served by gunicorn in production.
- TV control: `samsungtvws` library (handles pairing handshake, token storage,
  WebSocket framing, Wake-on-LAN magic packet).
- Frontend: static HTML + CSS + vanilla JS. No framework. Served by Flask itself
  (same origin, so no CORS needed).
- TV target: 2020 or newer (Tizen 5.5+), WebSocket on port 8002 with TLS.

## Architecture

```
Phone browser ──HTTP/JSON──> Flask server ──WSS(8002 TLS)──> Samsung TV
  (static web UI)            (token + macros)              (Tizen key API)
```

The middle server exists because browsers cannot open a WebSocket to the TV's
self-signed cert with custom auth. The server holds the pairing token and exposes
a plain JSON HTTP API the web UI calls.

## Components

| Unit          | Responsibility                                                        | Depends on        |
|---------------|-----------------------------------------------------------------------|-------------------|
| `config.yaml` | TV host/IP, name, port, WoL MAC, favorite app IDs, macro definitions  | —                 |
| `tv.py`       | Wrap `samsungtvws`: `connect()`, `send_key()`, `send_keys()`, `launch_app()`, `wake()`. Owns token file path. | samsungtvws    |
| `app.py`      | Flask app: routes, config loading, serves static UI                   | tv.py, config     |
| `static/`     | `index.html`, `style.css`, `remote.js` — CSS-grid remote, app grid, macro buttons, gesture pad | —   |

### Interfaces

`tv.py` exposes a `TVController` class so it can be mocked in tests by injecting a
fake `SamsungTVWS`:

```python
class TVController:
    def __init__(self, host, port, token_file, mac, ws_factory=SamsungTVWS): ...
    def send_key(self, keycode: str) -> None
    def send_keys(self, keycodes: list[str], delay: float = 0.1) -> None
    def launch_app(self, app_id: str) -> None
    def wake(self) -> None          # Wake-on-LAN magic packet
    def reachable(self) -> bool
```

## HTTP API

| Method | Path                 | Body                | Action                                  |
|--------|----------------------|---------------------|-----------------------------------------|
| POST   | `/key/<keycode>`     | —                   | Send one Tizen key                      |
| POST   | `/keys`              | `{"keys": [...]}`   | Send a batch of keys (gesture/macros)   |
| POST   | `/app/<app_id>`      | —                   | Launch app by Tizen app ID              |
| POST   | `/macro/<name>`      | —                   | Run a config-defined sequence           |
| POST   | `/wol`               | —                   | Send Wake-on-LAN magic packet           |
| GET    | `/health`            | —                   | `{server: ok, tv_reachable: bool}`      |
| GET    | `/config`            | —                   | Favorite apps + macro names for the UI  |
| GET    | `/`                  | —                   | Serve the web UI                        |

All POST responses: `{"ok": true}` on success, `{"ok": false, "error": "..."}` with
a non-2xx status on failure.

## v1 Features

1. **Working remote** — power, navigation (up/down/left/right/enter/return/exit/home),
   volume (up/down/mute), channel (up/down), number pad 0-9, color buttons, media
   transport (play/pause/stop/rew/ff), source/HDMI.
2. **Favorite apps grid** — quick-launch buttons defined in config by Tizen app ID.
3. **Macros** — named sequences in config: ordered list of keys, app launches, and
   delays. One UI button runs the whole sequence server-side.
4. **Gesture pad** — touch surface. JS computes dominant axis + direction on
   touchend, maps swipe to KEY_UP/DOWN/LEFT/RIGHT, tap (no movement) to KEY_ENTER.
   Debounced so one swipe sends one key.
5. **Wake-on-LAN** — power on from full standby (TV must have WoL enabled in its
   network settings).

## Config format

```yaml
tv:
  host: 192.168.1.50
  port: 8002
  name: WebRemote
  mac: "AA:BB:CC:DD:EE:FF"   # for Wake-on-LAN
  token_file: /data/token.txt
apps:
  - { name: Netflix,    id: "11101200001" }
  - { name: YouTube,    id: "111299001912" }
  - { name: Prime,      id: "3201512006785" }
  - { name: "Disney+",  id: "3201901017640" }
macros:
  movie_night:
    - { wol: true }
    - { delay: 8 }
    - { key: KEY_HDMI2 }
    - { delay: 1 }
    - { app: "3201512006785" }   # Prime
```

## Error handling

- TV unreachable → HTTP 503, UI shows a toast.
- Not yet paired → first key triggers the TV's "Allow this device?" prompt; UI shows
  a hint to accept on the TV. Token is then written to `token_file`.
- WoL is fire-and-forget — no ack expected; always returns ok if the packet was sent.

## Testing

- `pytest`: route → keycode mapping, macro expansion (delays/keys/apps order), config
  parsing. `TVController` constructed with a fake `ws_factory` so no real TV needed.
- Manual smoke test against the real TV for pairing + each button group.

## Deployment

### Dockerfile

- Base `python:3.12-slim`. Install requirements. Copy app + static. Run gunicorn
  binding `0.0.0.0:5000`. Non-root user.

### Kubernetes (`k8s/`)

- **Deployment** — single replica. `hostNetwork: true` is REQUIRED so the
  Wake-on-LAN magic packet broadcasts on the node's real LAN interface (the pod
  overlay network NATs and drops L2 broadcasts). `nodeSelector` pins the pod to a
  node that sits on the same subnet as the TV.
- **PVC** — mounted at `/data` so the pairing token survives pod restarts.
- **ConfigMap** — holds `config.yaml`, mounted into the container.
- **Service** — exposes the UI. With `hostNetwork: true` the app is already on the
  node's IP:5000; a NodePort/Service is provided for convenience/ingress.

### Network requirements

- Cluster nodes must be on the same LAN/subnet as the TV for both unicast WSS and
  WoL broadcast to work.
- TV network settings: enable Wake-on-LAN (sometimes "Power On with Mobile").

## Out of scope (later)

- Per-family-member layouts, search injection, picture-in-picture, recently-used
  sorting, long-press repeat. v1 ships the core + the four chosen extras.
