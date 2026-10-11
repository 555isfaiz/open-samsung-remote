import base64
import itertools
import json
import logging
import urllib.request

_LOG = logging.getLogger(__name__)

# Whitelisted shortcuts: name -> (JSON-RPC method, params).
ACTIONS = {
    "home":         ("Input.Home", {}),
    "osd":          ("Input.ShowOSD", {}),
    "video_addons": ("GUI.ActivateWindow",
                     {"window": "videos", "parameters": ["addons://sources/video/"]}),
    "backspace":    ("Input.ExecuteAction", {"action": "backspace"}),
}


class KodiError(Exception):
    pass


class KodiController:
    """Talks to Kodi's JSON-RPC over HTTP (Settings > Services > Control >
    "Allow remote control via HTTP")."""

    def __init__(self, host, port=8080, username=None, password=None,
                 opener=urllib.request.urlopen, timeout=5):
        self._url = f"http://{host}:{port}/jsonrpc"
        self._auth = None
        if username:
            raw = f"{username}:{password or ''}".encode()
            self._auth = "Basic " + base64.b64encode(raw).decode()
        self._opener = opener
        self._timeout = timeout
        self._ids = itertools.count(1)

    def call(self, method, params=None):
        body = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params:
            body["params"] = params
        headers = {"Content-Type": "application/json"}
        if self._auth:
            headers["Authorization"] = self._auth
        req = urllib.request.Request(
            self._url, data=json.dumps(body).encode(), headers=headers,
            method="POST",
        )
        _LOG.debug("kodi -> %s %s", method, params)
        with self._opener(req, timeout=self._timeout) as res:
            data = json.loads(res.read())
        if "error" in data:
            raise KodiError(data["error"].get("message", str(data["error"])))
        return data.get("result")

    def action(self, name):
        if name not in ACTIONS:
            raise ValueError(f"unknown kodi action: {name}")
        method, params = ACTIONS[name]
        return self.call(method, params)

    def send_text(self, text, done=True):
        # Only has an effect while Kodi's on-screen keyboard is open.
        return self.call("Input.SendText", {"text": text, "done": done})
