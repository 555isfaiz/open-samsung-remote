import socket
import threading
import time
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
        self._lock = threading.Lock()

    def _conn(self):
        # Lazily build the connection so import never blocks on the network.
        # key_press_delay=0 disables the library's 1s post-send sleep.
        if self._ws is None:
            self._ws = self._ws_factory(
                host=self._host, port=self._port,
                token_file=self._token_file, name=self._name,
                key_press_delay=0, timeout=5,
            )
        return self._ws

    def _reset(self):
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None

    def _wait_reachable(self, deadline: float) -> bool:
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((self._host, self._port), timeout=1):
                    return True
            except OSError:
                time.sleep(0.5)
        return False

    def _send_with_retry(self, fn, recovery_timeout: float = 15.0):
        with self._lock:
            try:
                return fn(self._conn())
            except Exception:
                self._reset()
            deadline = time.monotonic() + recovery_timeout
            last_err = None
            attempts = 0
            while time.monotonic() < deadline:
                if not self._wait_reachable(deadline):
                    break
                try:
                    return fn(self._conn())
                except Exception as e:
                    last_err = e
                    self._reset()
                    attempts += 1
                    time.sleep(min(0.5 * attempts, 2.0))
            raise last_err or TimeoutError("TV not reachable")

    def send_key(self, keycode: str) -> None:
        self._send_with_retry(lambda ws: ws.send_key(keycode))

    def send_keys(self, keycodes: list[str], delay: float = 0.05) -> None:
        def run(ws):
            for i, key in enumerate(keycodes):
                if i and delay:
                    time.sleep(delay)
                ws.send_key(key)
        self._send_with_retry(run)

    def launch_app(self, app_id: str) -> None:
        self._send_with_retry(lambda ws: ws.rest_app_run(app_id))

    def wake(self) -> None:
        if not self._mac:
            raise ValueError("No MAC configured for Wake-on-LAN")
        send_magic_packet(self._mac)
        with self._lock:
            self._reset()

    def reachable(self) -> bool:
        try:
            with socket.create_connection((self._host, self._port), timeout=2):
                return True
        except OSError:
            return False
