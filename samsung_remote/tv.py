import logging
import socket
import threading
import time
from samsungtvws import SamsungTVWS
from wakeonlan import send_magic_packet

_LOG = logging.getLogger(__name__)


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

    On ``wake()`` (Wake-on-LAN), the connection is re-established in the
    background once the TV finishes booting, so the first key press after
    waking is fast instead of paying the cold-boot reconnect.

    Background threads (heartbeat and wake warm-up) are enabled only when
    ``heartbeat_interval`` > 0; tests pass 0 to keep behavior deterministic.
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
        self._background_enabled = bool(heartbeat_interval and heartbeat_interval > 0)
        self._stop = threading.Event()
        self._hb_thread = None
        if self._background_enabled:
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
                _LOG.warning("heartbeat: connection dead, dropping", exc_info=True)
                self._reset()

    def _wait_reachable(self, deadline: float) -> bool:
        while time.monotonic() < deadline:
            try:
                with socket.create_connection((self._host, self._port), timeout=1):
                    return True
            except OSError:
                time.sleep(0.5)
        return False

    def _send_with_retry(self, fn, label: str = "action",
                         recovery_timeout: float = 15.0):
        with self._lock:
            _LOG.info("%s: sending", label)
            start = time.monotonic()
            try:
                result = fn(self._conn())
                self._apply_keepalive(self._ws)
                _LOG.info("%s: TV responded in %d ms", label,
                          (time.monotonic() - start) * 1000)
                return result
            except Exception:
                _LOG.warning("%s: send failed, reconnecting", label,
                             exc_info=True)
                self._reset()
            deadline = time.monotonic() + recovery_timeout
            last_err = None
            attempts = 0
            while time.monotonic() < deadline:
                if not self._wait_reachable(deadline):
                    break
                attempts += 1
                start = time.monotonic()
                try:
                    result = fn(self._conn())
                    self._apply_keepalive(self._ws)
                    _LOG.info("%s: TV responded in %d ms (retry %d)", label,
                              (time.monotonic() - start) * 1000, attempts)
                    return result
                except Exception as e:
                    last_err = e
                    _LOG.warning("%s: retry %d failed", label, attempts,
                                 exc_info=True)
                    self._reset()
                    time.sleep(min(0.5 * attempts, 2.0))
            _LOG.error("%s: giving up, TV not reachable", label)
            raise last_err or TimeoutError("TV not reachable")

    def send_key(self, keycode: str) -> None:
        self._send_with_retry(lambda ws: ws.send_key(keycode),
                              label=f"key {keycode}")

    def send_keys(self, keycodes: list[str], delay: float = 0.05) -> None:
        def run(ws):
            for i, key in enumerate(keycodes):
                if i and delay:
                    time.sleep(delay)
                ws.send_key(key)
        self._send_with_retry(run, label=f"keys {keycodes}")

    def launch_app(self, app_id: str) -> None:
        self._send_with_retry(lambda ws: ws.rest_app_run(app_id),
                              label=f"launch app {app_id}")

    def wake(self) -> None:
        if not self._mac:
            raise ValueError("No MAC configured for Wake-on-LAN")
        _LOG.info("wake: sending Wake-on-LAN packet to %s", self._mac)
        send_magic_packet(self._mac)
        with self._lock:
            self._reset()
        # Re-establish the websocket in the background while the TV boots, so
        # the first key press after waking is fast. Returns immediately.
        self._start_warmup()

    def _start_warmup(self, boot_timeout: float = 60.0) -> None:
        if not self._background_enabled:
            return
        threading.Thread(
            target=self._warmup, args=(boot_timeout,), daemon=True
        ).start()

    def _warmup(self, boot_timeout: float = 60.0) -> None:
        # Wait for the TV to answer on the port (cold boot can take seconds),
        # then open the websocket, retrying because the port may accept before
        # the remote endpoint is ready.
        _LOG.info("warmup: waiting for TV to boot (timeout %ds)", boot_timeout)
        deadline = time.monotonic() + boot_timeout
        if not self._wait_reachable(deadline):
            _LOG.warning("warmup: TV not reachable within %ds, giving up",
                         boot_timeout)
            return
        while time.monotonic() < deadline:
            with self._lock:
                try:
                    self._ensure_open()
                    _LOG.info("warmup: websocket established")
                    return
                except Exception:
                    _LOG.debug("warmup: not ready yet, retrying", exc_info=True)
                    self._reset()
            time.sleep(1.0)
        _LOG.warning("warmup: could not open websocket before timeout")

    def _ensure_open(self) -> None:
        # Force the websocket open without sending a key, so it is warm and
        # ready. open() is a no-op on the real client if already connected.
        ws = self._conn()
        opener = getattr(ws, "open", None)
        if callable(opener):
            opener()
        self._apply_keepalive(ws)

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
