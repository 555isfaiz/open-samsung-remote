import os
import time
from flask import Flask, jsonify, request, send_from_directory

from .config import load_config
from .tv import TVController

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(config, tv):
    app = Flask(__name__, static_folder=None)

    def ok():
        return jsonify({"ok": True})

    def fail(msg, code=503):
        return jsonify({"ok": False, "error": msg}), code

    @app.post("/key/<keycode>")
    def key(keycode):
        try:
            tv.send_key(keycode)
            return ok()
        except Exception as e:
            return fail(str(e))

    @app.post("/keys")
    def keys():
        body = request.get_json(silent=True) or {}
        raw = body.get("keys", [])
        if not isinstance(raw, list):
            return fail("keys must be a list", 400)
        try:
            tv.send_keys(raw)
            return ok()
        except Exception as e:
            return fail(str(e))

    @app.post("/app/<app_id>")
    def launch(app_id):
        try:
            tv.launch_app(app_id)
            return ok()
        except Exception as e:
            return fail(str(e))

    @app.post("/macro/<name>")
    def macro(name):
        steps = config.macros.get(name)
        if steps is None:
            return fail(f"unknown macro: {name}", 404)
        try:
            run_macro(tv, steps)
            return ok()
        except ValueError as e:
            return fail(str(e), 400)
        except Exception as e:
            return fail(str(e))

    @app.post("/wol")
    def wol():
        try:
            tv.wake()
            return ok()
        except ValueError as e:
            return fail(str(e), 400)

    @app.get("/health")
    def health():
        return jsonify({"server": "ok", "tv_reachable": tv.reachable()})

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


def create_app_from_env():
    cfg = load_config(os.environ.get("CONFIG_PATH", "config.yaml"))
    tv = TVController(
        host=cfg.tv.host, port=cfg.tv.port, token_file=cfg.tv.token_file,
        mac=cfg.tv.mac, name=cfg.tv.name,
    )
    return create_app(cfg, tv)
