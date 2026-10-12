import base64
import io
import json
import pytest
from samsung_remote.kodi import KodiController, KodiError


class FakeOpener:
    def __init__(self, response=None):
        self.requests = []
        self.responses = response if isinstance(response, list) else None
        self.response = response or {"jsonrpc": "2.0", "id": 1, "result": "OK"}

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        response = self.responses.pop(0) if self.responses is not None else self.response
        return io.BytesIO(json.dumps(response).encode())

    def body(self, i=-1):
        return json.loads(self.requests[i].data)


def test_action_posts_jsonrpc_to_kodi():
    opener = FakeOpener()
    kodi = KodiController("192.168.1.103", 8080, opener=opener)
    kodi.action("home")
    req = opener.requests[0]
    assert req.full_url == "http://192.168.1.103:8080/jsonrpc"
    assert req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/json"
    assert req.get_header("Authorization") is None
    body = opener.body()
    assert body["jsonrpc"] == "2.0" and body["method"] == "Input.Home"
    assert "params" not in body


def test_action_with_params():
    opener = FakeOpener()
    KodiController("h", opener=opener).action("video_addons")
    body = opener.body()
    assert body["method"] == "GUI.ActivateWindow"
    assert body["params"] == {"window": "videos", "parameters": ["addons://sources/video/"]}


def active_players(*players):
    return {"jsonrpc": "2.0", "id": 1, "result": list(players)}


@pytest.mark.parametrize("media,window", [
    ("video", "fullscreenvideo"),
    ("audio", "visualisation"),
    ("picture", "slideshow"),
])
def test_back_to_player_opens_active_media_view(media, window):
    opener = FakeOpener([active_players({"playerid": 1, "type": media}),
                         {"result": "OK"}])
    KodiController("h", opener=opener).action("back_to_player")
    assert [opener.body(i)["method"] for i in range(2)] == [
        "Player.GetActivePlayers", "GUI.ActivateWindow"]
    assert opener.body()["params"] == {"window": window}


def test_back_to_player_without_active_media_does_not_navigate_back():
    opener = FakeOpener([active_players()])
    with pytest.raises(KodiError, match="no active player"):
        KodiController("h", opener=opener).action("back_to_player")
    assert len(opener.requests) == 1


def test_stop_playing_stops_each_active_player():
    opener = FakeOpener([active_players(
        {"playerid": 0, "type": "audio"}, {"playerid": 1, "type": "video"}),
        {"result": "OK"}, {"result": "OK"}])
    KodiController("h", opener=opener).action("stop_playing")
    assert [(opener.body(i)["method"], opener.body(i).get("params"))
            for i in range(3)] == [
                ("Player.GetActivePlayers", None),
                ("Player.Stop", {"playerid": 0}),
                ("Player.Stop", {"playerid": 1}),
            ]


@pytest.mark.parametrize("media,window", [
    ("video", "videoplaylist"),
    ("audio", "musicplaylist"),
    (None, "videoplaylist"),
])
def test_playlist_opens_media_playlist(media, window):
    players = [] if media is None else [{"playerid": 1, "type": media}]
    opener = FakeOpener([active_players(*players), {"result": "OK"}])
    KodiController("h", opener=opener).action("playlist")
    assert [opener.body(i)["method"] for i in range(2)] == [
        "Player.GetActivePlayers", "GUI.ActivateWindow"]
    assert opener.body()["params"] == {"window": window}


def test_basic_auth_header():
    opener = FakeOpener()
    KodiController("h", username="kodi", password="secret", opener=opener).action("osd")
    expected = "Basic " + base64.b64encode(b"kodi:secret").decode()
    assert opener.requests[0].get_header("Authorization") == expected


def test_unknown_action_raises_value_error():
    opener = FakeOpener()
    with pytest.raises(ValueError):
        KodiController("h", opener=opener).action("nope")
    assert opener.requests == []


def test_send_text():
    opener = FakeOpener()
    KodiController("h", opener=opener).send_text("star wars")
    body = opener.body()
    assert body["method"] == "Input.SendText"
    assert body["params"] == {"text": "star wars", "done": True}


def test_jsonrpc_error_raises():
    opener = FakeOpener({"jsonrpc": "2.0", "id": 1,
                         "error": {"code": -32601, "message": "Method not found."}})
    with pytest.raises(KodiError, match="Method not found"):
        KodiController("h", opener=opener).action("home")


def test_request_ids_increment():
    opener = FakeOpener()
    kodi = KodiController("h", opener=opener)
    kodi.action("home")
    kodi.action("osd")
    assert opener.body(0)["id"] != opener.body(1)["id"]
