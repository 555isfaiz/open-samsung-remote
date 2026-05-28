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

The project ships a Helm chart at `chart/`. All cluster nodes must be on the same
LAN/subnet as the TV: the Deployment runs with `hostNetwork: true` so that the
Wake-on-LAN magic packet leaves the node's real interface (the pod overlay drops
L2 broadcasts). The pairing token lives on a PVC so it survives restarts.

### CI build (self-hosted GitHub Actions runner)

On every push to `main`, `.github/workflows/build.yml` builds the image and pushes
two tags to the private registry:

- `rp.images.local/open-samsung-remote:<short-sha>`
- `rp.images.local/open-samsung-remote:latest`

The runner machine must have Docker installed, be able to resolve `rp.images.local`,
and be authenticated to the registry (either via `docker login` once on the host,
or via a workflow step using `secrets.REGISTRY_USER` / `secrets.REGISTRY_PASS`).

### Manual deploy with Helm

```bash
kubectl create namespace samsung-remote

cat > my-values.yaml <<'EOF'
image:
  repository: rp.images.local/open-samsung-remote
  tag: <short-sha>          # from the build job
tv:
  host: 192.168.1.50        # real TV IP
  mac: "AA:BB:CC:DD:EE:FF"  # real TV MAC for Wake-on-LAN
ingress:
  enabled: true
  host: tv.lan.example      # DNS pointing at your ingress controller
EOF

helm upgrade --install samsung-remote chart \
  -f my-values.yaml \
  -n samsung-remote

kubectl -n samsung-remote rollout status deploy/samsung-remote
```

Update: bump `image.tag`, re-run `helm upgrade --install`. `imagePullPolicy: Always`
plus a new tag triggers a rolling restart.

Uninstall: `helm uninstall samsung-remote -n samsung-remote` (PVC is retained;
delete with `kubectl delete pvc samsung-remote-token -n samsung-remote`).

### Argo CD deploy

The Application manifest lives at `argo/application.yaml`. It points Argo at the
Helm chart in this repo and exposes `image.repository`, `image.tag`, `tv.host`,
`tv.mac`, `tv.name`, and `ingress.host` as parameters editable in the Argo UI.

One-shot install:
```bash
kubectl apply -f argo/application.yaml -n argocd
```

Or via the Argo CD UI:

1. (Public repo, optional but cleaner) Settings > Repositories > Connect Repo via
   HTTPS using the repo URL.
2. Applications > New App > Edit as YAML > paste the contents of
   `argo/application.yaml` > Create. Argo will sync within seconds.
3. To change values without a git commit, open the app > Parameters tab > Edit,
   then Save. Argo re-syncs immediately.

Sync policy is `automated` with `prune` and `selfHeal`, plus `CreateNamespace=true`
so the target namespace is created on first sync.

## Keys

Standard Tizen key set: `KEY_POWER`, `KEY_UP/DOWN/LEFT/RIGHT`, `KEY_ENTER`,
`KEY_VOLUP/VOLDOWN/MUTE`, `KEY_CHUP/CHDOWN`, `KEY_0`-`KEY_9`, `KEY_HDMI1`-`KEY_HDMI4`,
`KEY_PLAY/PAUSE/STOP/REWIND/FF`, and more.
