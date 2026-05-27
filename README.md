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
`KEY_VOLUP/VOLDOWN/MUTE`, `KEY_CHUP/CHDOWN`, `KEY_0`-`KEY_9`, `KEY_HDMI1`-`KEY_HDMI4`,
`KEY_PLAY/PAUSE/STOP/REWIND/FF`, and more.
