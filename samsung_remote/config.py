from dataclasses import dataclass, field
import yaml


@dataclass
class TVConfig:
    host: str
    token_file: str
    port: int = 8002
    name: str = "WebRemote"
    mac: str | None = None


@dataclass
class AppEntry:
    name: str
    id: str


@dataclass
class Config:
    tv: TVConfig
    apps: list[AppEntry] = field(default_factory=list)
    macros: dict[str, list[dict]] = field(default_factory=dict)


def load_config(path: str) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    tv_raw = raw.get("tv", {})
    tv = TVConfig(
        host=tv_raw["host"],
        token_file=tv_raw["token_file"],
        port=tv_raw.get("port", 8002),
        name=tv_raw.get("name", "WebRemote"),
        mac=tv_raw.get("mac"),
    )
    apps = [AppEntry(name=a["name"], id=str(a["id"])) for a in raw.get("apps", [])]
    macros = raw.get("macros", {}) or {}
    return Config(tv=tv, apps=apps, macros=macros)
