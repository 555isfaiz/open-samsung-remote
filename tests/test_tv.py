from samsung_remote.tv import TVController


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


def test_heartbeat_resets_when_ping_fails():
    tv = make_controller()
    fake = FakeWS()
    fake.connection = FakeConn(ping_raises=True)
    tv._ws = fake
    tv._heartbeat_tick()
    assert tv._ws is None  # dead connection dropped


def test_heartbeat_tick_noop_without_connection():
    tv = make_controller()
    tv._ws = None
    tv._heartbeat_tick()  # must not raise


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
