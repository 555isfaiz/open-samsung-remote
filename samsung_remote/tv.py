import socket
import threading
import time
from samsungtvws import SamsungTVWS
from wakeonlan import send_magic_packet


class TVController:
    """Talks to a Samsung TV (2020+) over WSS, owns the pairing token.

    The TV silently closes the remote websocket after it has been idle for a
    few minutes, and home routers drop idle NAT flows. A dead-but-not-reset
    socket is the worst case: the next key press stalls on TCP retransmits
    before the failure surfaces, which is the "sudden long delay" symptom.

    Two defenses keep that off the key-press path:
    1. A background heartbeat pings the websocket every ``heartbeat_interval``
       seconds, keeping it warm so the TV never idle-closes it.
    2. TCP keepalive + TCP_USER_TIMEOUT on the socket bound how long a silently
       dropped connection can stall before the kernel tears it down.
    """

    def __init__(self, host, port, token_file, mac=None, name="WebRemote",
                 ws_factory=SamsungTVWS, heartbeat_interval=30.0):
        self._host = host
        self._port = port
        self._token_file = token_file
        self._mac = mac
        self._name = name
        self._ws_factory = ws_factory
        self._ws = None
        self._keepalive_set = False
        self._lock = threading.Lock()
        self._heartbeat_interval = heartbeat_interval
        self._stop = threading.Event()
        self._hb_thread = None
        if heartbeat_interval and heartbeat_interval > 0:
            self._hb_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True
            )
            self._hb_thread.start()

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
        self._keepalive_set = False

    def _apply_keepalive(self, ws):
        # Set once per connection. Bounds how long a dead socket can stall a
        # send before the kernel surfaces the error. Best-effort and
        # platform-dependent: missing options are skipped.
        if self._keepalive_set:
            return
        sock = getattr(getattr(ws, "connection", None), "sock", None)
        if sock is None:
            return
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        for opt_name, value in (
            ("TCP_KEEPIDLE", 20),        # Linux: idle seconds before probes
            ("TCP_KEEPINTVL", 10),       # seconds between probes
            ("TCP_KEEPCNT", 3),          # failed probes before drop
            ("TCP_KEEPALIVE", 20),       # macOS equivalent of KEEPIDLE
            ("TCP_USER_TIMEOUT", 30000), # Linux: ms an unacked send may stall
        ):
            opt = getattr(socket, opt_name, None)
            if opt is None:
                continue
            try:
                sock.setsockopt(socket.IPPROTO_TCP, opt, value)
            except OSError:
                pass
        self._keepalive_set = True

    def _heartbeat_loop(self):
        # Event.wait doubles as the sleep and the stop signal.
        while not self._stop.wait(self._heartbeat_interval):
            self._heartbeat_tick()

    def _heartbeat_tick(self):
        with self._lock:
            ws = self._ws
            conn = getattr(ws, "connection", None) if ws is not None else None
            if conn is None:
                return
            try:
                conn.ping()
                self._apply_keepalive(ws)
            except Exception:
                # Connection is dead; drop it so the next key press (or the
                # next tick) rebuilds a fresh one instead of stalling on it.
                self._reset()

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
                result = fn(self._conn())
                self._apply_keepalive(self._ws)
                return result
            except Exception:
                self._reset()
            deadline = time.monotonic() + recovery_timeout
            last_err = None
            attempts = 0
            while time.monotonic() < deadline:
                if not self._wait_reachable(deadline):
                    break
                try:
                    result = fn(self._conn())
                    self._apply_keepalive(self._ws)
                    return result
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

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._reset()
