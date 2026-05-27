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
