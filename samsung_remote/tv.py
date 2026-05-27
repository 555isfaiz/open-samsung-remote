import socket
from samsungtvws import SamsungTVWS
from wakeonlan import send_magic_packet


class TVController:
    """Talks to a Samsung TV (2020+) over WSS, owns the pairing token."""

    def __init__(self, host, port, token_file, mac=None, name="WebRemote",
                 ws_factory=SamsungTVWS):
        self._host = host
        self._port = port
        self._token_file = token_file
        self._mac = mac
        self._name = name
        self._ws_factory = ws_factory
        self._ws = None

    def _conn(self):
        # Lazily build the connection so import never blocks on the network.
        if self._ws is None:
            self._ws = self._ws_factory(
                host=self._host, port=self._port,
                token_file=self._token_file, name=self._name,
            )
        return self._ws

    def send_key(self, keycode: str) -> None:
        self._conn().shortcuts().send_key(keycode)

    def send_keys(self, keycodes: list[str], delay: float = 0.1) -> None:
        import time
        remote = self._conn().shortcuts()
        for i, key in enumerate(keycodes):
            if i and delay:
                time.sleep(delay)
            remote.send_key(key)

    def launch_app(self, app_id: str) -> None:
        self._conn().rest_app_run(app_id)

    def wake(self) -> None:
        if not self._mac:
            raise ValueError("No MAC configured for Wake-on-LAN")
        send_magic_packet(self._mac)

    def reachable(self) -> bool:
        try:
            with socket.create_connection((self._host, self._port), timeout=2):
                return True
        except OSError:
            return False
