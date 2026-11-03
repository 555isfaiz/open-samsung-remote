import threading

from websocket import ABNF, WebSocketTimeoutException

from samsung_remote import tv as tv_mod
from samsung_remote.tv import TVController, _Reader


class FakeWS:
    """Stand-in for SamsungTVWS (matches the methods TVController calls)."""
    last = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.keys = []
        self.apps_run = []
        self.connection = None
        FakeWS.last = self

    def send_key(self, key):
        self.keys.append(key)

    def rest_app_run(self, app_id):
        self.apps_run.append(app_id)

    def close(self):
        pass


def make_controller(ws_factory=FakeWS):
    # heartbeat_interval=0 disables the background thread for deterministic tests.
    return TVController(
        host="1.2.3.4", port=8002, token_file="/tmp/token.txt",
        mac="AA:BB:CC:DD:EE:FF", name="Test", ws_factory=ws_factory,
        heartbeat_interval=0,
    )


def test_send_key_forwards_to_ws():
    tv = make_controller()
    tv.send_key("KEY_VOLUP")
    assert FakeWS.last.keys == ["KEY_VOLUP"]


def test_send_keys_sends_each_in_order():
    tv = make_controller()
    tv.send_keys(["KEY_UP", "KEY_ENTER"], delay=0)
    assert FakeWS.last.keys == ["KEY_UP", "KEY_ENTER"]


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


class FakeSock:
    def __init__(self):
        self.opts = []

    def setsockopt(self, *args):
        self.opts.append(args)


class FakeConn:
    def __init__(self, ping_raises=False):
        self.pings = 0
        self.ping_raises = ping_raises
        self.sock = FakeSock()
        self.connected = True

    def ping(self):
        self.pings += 1
        if self.ping_raises:
            raise OSError("dead socket")

    def close(self):
        self.connected = False


def test_heartbeat_pings_live_connection():
    tv = make_controller()
    fake = FakeWS()
    fake.connection = FakeConn()
    tv._ws = fake
    tv._heartbeat_tick()
    assert fake.connection.pings == 1


def test_heartbeat_reconnects_when_ping_fails(monkeypatch):
    tv = make_controller()
    monkeypatch.setattr(tv, "reachable", lambda: True)
    dead = FakeWS()
    dead.connection = FakeConn(ping_raises=True)
    tv._ws = dead
    tv._heartbeat_tick()
    # Dead connection dropped and replaced with a fresh one (kept warm).
    assert tv._ws is not None
    assert tv._ws is not dead


def test_heartbeat_tick_without_connection_waits_when_unreachable(monkeypatch):
    tv = make_controller()
    monkeypatch.setattr(tv, "reachable", lambda: False)
    tv._ws = None
    tv._heartbeat_tick()  # must not raise
    assert tv._ws is None


def test_heartbeat_opens_cold_connection_when_reachable(monkeypatch):
    opened = []

    class WSOpenable(FakeWS):
        def open(self):
            opened.append(self)
            self.connection = FakeConn()

    tv = make_controller(ws_factory=WSOpenable)
    monkeypatch.setattr(tv, "reachable", lambda: True)
    tv._heartbeat_tick()
    assert len(opened) == 1  # warmed before any key press
    tv.send_key("KEY_OK")
    assert tv._ws is opened[0] and opened[0].keys == ["KEY_OK"]


def test_heartbeat_cold_open_failure_is_quiet(monkeypatch):
    class WSBroken(FakeWS):
        def open(self):
            raise OSError("not ready")

    tv = make_controller(ws_factory=WSBroken)
    monkeypatch.setattr(tv, "reachable", lambda: True)
    tv._heartbeat_tick()  # must not raise
    assert tv._ws is None  # retried on next tick


def test_power_off_key_marks_tv_off_and_pauses_heartbeat():
    tv = make_controller()
    tv.send_key("KEY_POWER")
    assert tv._tv_on is False


def test_heartbeat_paused_when_tv_off():
    tv = make_controller()
    fake = FakeWS()
    fake.connection = FakeConn()
    tv._ws = fake
    tv._tv_on = False
    tv._heartbeat_tick()
    assert fake.connection.pings == 0  # paused: no ping while off


def test_wake_marks_tv_on(monkeypatch):
    monkeypatch.setattr("samsung_remote.tv.send_magic_packet", lambda mac: None)
    tv = make_controller()
    tv._tv_on = False
    tv.wake()
    assert tv._tv_on is True


def test_wake_triggers_warmup(monkeypatch):
    tv = make_controller()
    called = {}
    monkeypatch.setattr(tv, "_start_warmup", lambda: called.setdefault("v", True))
    monkeypatch.setattr("samsung_remote.tv.send_magic_packet", lambda mac: None)
    tv.wake()
    assert called.get("v") is True


def test_warmup_opens_connection_when_reachable(monkeypatch):
    opened = {}

    class WSOpenable(FakeWS):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.connection = FakeConn()

        def open(self):
            opened["yes"] = True

    tv = make_controller(ws_factory=WSOpenable)
    monkeypatch.setattr(tv, "_wait_reachable", lambda deadline: True)
    tv._warmup(boot_timeout=1)
    assert opened.get("yes") is True


def test_warmup_skips_when_unreachable(monkeypatch):
    tv = make_controller()
    monkeypatch.setattr(tv, "_wait_reachable", lambda deadline: False)
    tv._warmup(boot_timeout=1)
    assert tv._ws is None  # never opened


def test_send_applies_tcp_keepalive():
    made = {}

    class WSWithConn(FakeWS):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.connection = FakeConn()
            made["ws"] = self

    tv = make_controller(ws_factory=WSWithConn)
    tv.send_key("KEY_OK")
    # At least SO_KEEPALIVE was set on the underlying socket.
    assert made["ws"].connection.sock.opts


def test_heartbeat_skips_reconnect_when_unreachable(monkeypatch):
    tv = make_controller()
    monkeypatch.setattr(tv, "reachable", lambda: False)
    dead = FakeWS()
    dead.connection = FakeConn(ping_raises=True)
    tv._ws = dead
    tv._heartbeat_tick()
    assert tv._ws is None  # dropped, no retry loop holding the lock


class ScriptedConn(FakeConn):
    """Feeds _Reader a scripted sequence of frames / exceptions."""

    def __init__(self, script):
        super().__init__()
        self.script = list(script)
        self.done = threading.Event()

    def recv_data_frame(self, control_frame=False):
        if not self.script:
            self.done.set()
            raise OSError("closed")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, None


def test_reader_records_pong_and_survives_timeouts():
    conn = ScriptedConn([
        ABNF.OPCODE_PING, WebSocketTimeoutException("quiet"),
        ABNF.OPCODE_TEXT, ABNF.OPCODE_PONG,
    ])
    r = _Reader(conn)
    assert r.dead.wait(2)  # script exhausted -> socket "closed"
    assert r.pong.is_set()


def test_reader_marks_dead_on_close_frame():
    conn = ScriptedConn([ABNF.OPCODE_CLOSE, ABNF.OPCODE_PONG])
    r = _Reader(conn)
    assert r.dead.wait(2)
    assert not r.pong.is_set()  # stopped at CLOSE


def test_send_reconnects_first_when_reader_saw_close():
    tv = make_controller()
    stale = FakeWS()
    tv._ws = stale
    reader = type("R", (), {})()
    reader.dead = threading.Event()
    reader.dead.set()
    tv._reader = reader
    tv.send_key("KEY_OK")
    assert tv._ws is not stale  # fresh connection used
    assert stale.keys == []
    assert tv._ws.keys == ["KEY_OK"]


def test_heartbeat_reconnects_when_no_pong(monkeypatch):
    monkeypatch.setattr(tv_mod, "_PONG_TIMEOUT", 0.01)
    tv = make_controller()
    monkeypatch.setattr(tv, "reachable", lambda: True)
    silent = FakeWS()
    silent.connection = FakeConn()
    tv._ws = silent
    reader = type("R", (), {})()
    reader.dead = threading.Event()
    reader.pong = threading.Event()  # never set: TV doesn't answer
    tv._reader = reader
    tv._heartbeat_tick()
    assert silent.connection.pings == 1
    assert tv._ws is not silent
