import textwrap
from samsung_remote.config import load_config

def test_load_config_parses_tv_apps_macros(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent("""
        tv:
          host: 192.168.1.50
          port: 8002
          name: WebRemote
          mac: "AA:BB:CC:DD:EE:FF"
          token_file: /data/token.txt
        apps:
          - { name: Netflix, id: "11101200001" }
        macros:
          movie_night:
            - { wol: true }
            - { delay: 8 }
            - { key: KEY_HDMI2 }
            - { app: "11101200001" }
    """))
    cfg = load_config(str(p))
    assert cfg.tv.host == "192.168.1.50"
    assert cfg.tv.port == 8002
    assert cfg.tv.mac == "AA:BB:CC:DD:EE:FF"
    assert cfg.apps[0].name == "Netflix"
    assert cfg.apps[0].id == "11101200001"
    assert cfg.macros["movie_night"][0] == {"wol": True}
    assert cfg.macros["movie_night"][1] == {"delay": 8}

def test_load_config_defaults_port_8002(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("tv:\n  host: 1.2.3.4\n  token_file: /data/token.txt\n")
    cfg = load_config(str(p))
    assert cfg.tv.port == 8002
    assert cfg.apps == []
    assert cfg.macros == {}
