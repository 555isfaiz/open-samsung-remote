import logging
import os
import time
from flask import Flask, jsonify, request, send_from_directory

from .config import load_config
from .tv import TVController

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_LOG = logging.getLogger(__name__)


def create_app(config, tv):
    app = Flask(__name__, static_folder=None)

    def ok():
        return jsonify({"ok": True})

    def fail(action, msg, code=503):
        _LOG.warning("%s failed (%d): %s", action, code, msg)
        return jsonify({"ok": False, "error": msg}), code

    @app.post("/key/<keycode>")
    def key(keycode):
        _LOG.info("request: key %s", keycode)
        try:
            tv.send_key(keycode)
            return ok()
        except Exception as e:
            return fail(f"key {keycode}", str(e))

    @app.post("/keys")
    def keys():
        body = request.get_json(silent=True) or {}
        raw = body.get("keys", [])
        if not isinstance(raw, list):
            return fail("keys", "keys must be a list", 400)
        _LOG.info("request: keys %s", raw)
        try:
            tv.send_keys(raw)
            return ok()
        except Exception as e:
            return fail("keys", str(e))

    @app.post("/app/<app_id>")
    def launch(app_id):
        _LOG.info("request: launch app %s", app_id)
        try:
            tv.launch_app(app_id)
            return ok()
        except Exception as e:
            return fail(f"app {app_id}", str(e))

    @app.post("/macro/<name>")
    def macro(name):
        steps = config.macros.get(name)
        if steps is None:
            return fail(f"macro {name}", f"unknown macro: {name}", 404)
        _LOG.info("request: macro %s", name)
        try:
            run_macro(tv, steps)
            return ok()
        except ValueError as e:
            return fail(f"macro {name}", str(e), 400)
        except Exception as e:
            return fail(f"macro {name}", str(e))

    @app.post("/wol")
    def wol():
        _LOG.info("request: wol")
        try:
            tv.wake()
            return ok()
        except ValueError as e:
            return fail("wol", str(e), 400)

    @app.get("/health")
    def health():
        return jsonify({"server": "ok"})

    @app.get("/tv-status")
    def tv_status():
        return jsonify({"tv_reachable": tv.reachable()})

    @app.get("/config")
    def get_config():
        return jsonify({
            "apps": [{"name": a.name, "id": a.id} for a in config.apps],
            "macros": list(config.macros.keys()),
        })

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:path>")
    def static_files(path):
        return send_from_directory(STATIC_DIR, path)

    return app


def run_macro(tv, steps):
    """Execute a macro: ordered keys, app launches, delays, and WoL."""
    for step in steps:
        if "delay" in step:
            time.sleep(step["delay"])
        elif "key" in step:
            tv.send_key(step["key"])
        elif "app" in step:
            tv.launch_app(step["app"])
        elif step.get("wol"):
            tv.wake()
        else:
            raise ValueError(f"unknown macro step: {step}")


def _configure_logging():
    # Ensure our package logs reach stdout regardless of how gunicorn set up
    # the root logger. Level via LOG_LEVEL (default INFO).
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger = logging.getLogger("samsung_remote")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        logger.addHandler(handler)
        logger.propagate = False


def create_app_from_env():
    _configure_logging()
    cfg = load_config(os.environ.get("CONFIG_PATH", "config.yaml"))
    tv = TVController(
        host=cfg.tv.host, port=cfg.tv.port, token_file=cfg.tv.token_file,
        mac=cfg.tv.mac, name=cfg.tv.name,
    )
    return create_app(cfg, tv)
