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
    # /health is liveness only: must not probe the TV, so the readiness probe
    # stays green even when the TV is asleep (otherwise the UI to wake it
    # would be unreachable).
    client, tv = ctx
    r = client.get("/health")
    assert r.get_json() == {"server": "ok"}


def test_tv_status_route_reports_reachability(ctx):
    client, tv = ctx
    r = client.get("/tv-status")
    assert r.get_json() == {"tv_reachable": True}


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


# Fix 1: non-OSError from TV should still return 503, not 500
def test_non_oserror_tv_failure_returns_503(ctx):
    client, tv = ctx
    def boom(_): raise RuntimeError("boom")
    tv.send_key = boom
    r = client.post("/key/KEY_VOLUP")
    assert r.status_code == 503
    assert r.get_json()["ok"] is False


# Fix 2: /keys with a string value should return 400
def test_keys_string_value_returns_400(ctx):
    client, tv = ctx
    r = client.post("/keys", json={"keys": "KEY_UP"})
    assert r.status_code == 400
    body = r.get_json()
    assert body["ok"] is False
    assert "list" in body["error"]


# Fix 2: /keys with an int value should return 400
def test_keys_int_value_returns_400(ctx):
    client, tv = ctx
    r = client.post("/keys", json={"keys": 42})
    assert r.status_code == 400
    body = r.get_json()
    assert body["ok"] is False


# Fix 3: macro with an unknown step key should return 400
def test_macro_bad_step_returns_400(ctx):
    client, tv = ctx
    # Inject a macro with a bogus step key into the config
    from samsung_remote.config import Config, TVConfig, AppEntry
    cfg = Config(
        tv=TVConfig(host="1.2.3.4", token_file="/tmp/t", mac="AA:BB:CC:DD:EE:FF"),
        apps=[],
        macros={"bad": [{"typo_key": "KEY_UP"}]},
    )
    from samsung_remote.app import create_app
    bad_app = create_app(cfg, tv)
    bad_client = bad_app.test_client()
    r = bad_client.post("/macro/bad")
    assert r.status_code == 400
    body = r.get_json()
    assert body["ok"] is False
    assert "unknown macro step" in body["error"]


class FakeKodi:
    def __init__(self):
        self.actions = []
        self.texts = []

    def action(self, name):
        if name == "nope":
            raise ValueError(f"unknown kodi action: {name}")
        self.actions.append(name)

    def send_text(self, text, done=True): self.texts.append((text, done))


@pytest.fixture
def kodi_ctx():
    cfg = Config(tv=TVConfig(host="1.2.3.4", token_file="/tmp/t"))
    kodi = FakeKodi()
    return create_app(cfg, FakeTV(), kodi).test_client(), kodi


def test_kodi_action_route(kodi_ctx):
    client, kodi = kodi_ctx
    r = client.post("/kodi/action/home")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert kodi.actions == ["home"]


def test_kodi_unknown_action_returns_400(kodi_ctx):
    client, kodi = kodi_ctx
    r = client.post("/kodi/action/nope")
    assert r.status_code == 400


def test_kodi_failure_returns_503(kodi_ctx):
    client, kodi = kodi_ctx
    def boom(_): raise OSError("connection refused")
    kodi.action = boom
    r = client.post("/kodi/action/home")
    assert r.status_code == 503
    assert r.get_json()["ok"] is False


def test_kodi_text_route(kodi_ctx):
    client, kodi = kodi_ctx
    r = client.post("/kodi/text", json={"text": "star wars"})
    assert r.status_code == 200
    assert kodi.texts == [("star wars", True)]


def test_kodi_text_requires_string(kodi_ctx):
    client, kodi = kodi_ctx
    r = client.post("/kodi/text", json={"text": 5})
    assert r.status_code == 400
    assert kodi.texts == []


def test_kodi_routes_404_when_not_configured(ctx):
    client, tv = ctx
    assert client.post("/kodi/action/home").status_code == 404
    assert client.post("/kodi/text", json={"text": "x"}).status_code == 404


def test_config_route_reports_kodi_flag(ctx, kodi_ctx):
    assert ctx[0].get("/config").get_json()["kodi"] is False
    assert kodi_ctx[0].get("/config").get_json()["kodi"] is True
