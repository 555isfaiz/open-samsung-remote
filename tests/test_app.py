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
    def boom(_): raise OSError("connection refused")
    tv.send_key = boom
    r = client.post("/key/KEY_VOLUP")
    assert r.status_code == 503
    assert r.get_json()["ok"] is False


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
